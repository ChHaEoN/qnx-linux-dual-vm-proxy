// someip_vprobe.cpp -- Phase 3b / A6 (2026-09-27, OD12's SOME/IP arm): the Linux side's C++ client
// for the guest's SOME/IP monitor (ipc-test/qnx-someip). latency_probe.py runs it and builds the
// result file from what it prints, so every arm's summary is computed by the same code.
//
// usage: someip_vprobe MODE N WARMUP INTERVAL_MS TIMEOUT_S [HOST PORT]
//   MODE tcp | udp        through vsomeip 3.4.10 ("reliable" | "unreliable"). The service's
//                         address and port come from vsomeip's configuration
//                         (VSOMEIP_CONFIGURATION): service discovery disabled, service 0x5AFE
//                         instance 0x0001 at the guest's unicast address. The application is
//                         "someip_vprobe" and hosts vsomeip's routing itself (no routingmanagerd).
//   MODE rawtcp | rawudp  the same requests on a plain POSIX socket to HOST:PORT, the SOME/IP
//                         header built by hand, no vsomeip at all: the control that separates
//                         vsomeip's cost from this client's, since both modes share every other
//                         line of this program.
//
// Each exchange: one REQUEST of method 0x0001, interface version 1, client 0x0200 in raw mode
// (vsomeip assigns its own from the configuration), session 1..0xFFFF, payload the monitor's
// 64-byte claim frame (latency_probe.py's build_frame: class 3, confidence 95, 124 us).
//   vsomeip: t0 just before application::send(), t1 at the top of the message handler vsomeip
//            calls with the response; the main thread then checks it.
//   raw:     t0 just before send(), t1 when recv() has the whole response, in the main thread.
// Checks, both modes: message type RESPONSE, return code E_OK, the request's session, a 64-byte
// payload whose seq is the request's, and the verdict byte (a reject is counted, not timed, as
// latency_probe does). Anything else is fatal: exit 5 with an "error" line, no samples.
//
// Output (stdout), one JSON object: {"rtt_ns": [...], "send_ns": [...], "rejected": R,
// "sched": {...}, "vsomeip": "3.4.10" | null, "mode": MODE}, the timed exchanges in order.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sched.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <vsomeip/vsomeip.hpp>

namespace {

constexpr std::uint16_t kService = 0x5AFE, kInstance = 0x0001, kMethod = 0x0001, kRawClient = 0x0200;
constexpr std::uint8_t kIface = 1;
constexpr std::size_t kFrame = 64, kHdr = 16, kVerdict = 16 + 6;

using clk = std::chrono::steady_clock;

struct Samples {
    std::vector<long long> rtt, sends;
    long rejected = 0;
};

std::vector<std::uint8_t> build_frame(std::uint64_t seq)
{
    std::vector<std::uint8_t> f(kFrame, 0);
    for (int i = 0; i < 8; i++)
        f[i] = static_cast<std::uint8_t>(seq >> (8 * i));
    f[16 + 0] = 3;       // class
    f[16 + 1] = 95;      // confidence
    f[16 + 2] = 124;     // inference_us, little-endian uint32
    return f;
}

std::uint16_t session_of(std::uint64_t seq)
{
    return static_cast<std::uint16_t>((seq - 1) % 0xFFFF + 1);
}

const char *policy_name(int p)
{
    switch (p) {
    case SCHED_OTHER: return "SCHED_OTHER";
    case SCHED_FIFO: return "SCHED_FIFO";
    case SCHED_RR: return "SCHED_RR";
    default: return "other";
    }
}

std::string sched_json()
{
    sched_param sp{};
    int pol = sched_getscheduler(0);
    sched_getparam(0, &sp);
    cpu_set_t set;
    CPU_ZERO(&set);
    std::string cpus;
    if (sched_getaffinity(0, sizeof set, &set) == 0) {
        for (int c = 0; c < CPU_SETSIZE; c++) {
            if (CPU_ISSET(c, &set))
                cpus += (cpus.empty() ? "" : ", ") + std::to_string(c);
        }
    }
    return "{\"sched_policy\": \"" + std::string(policy_name(pol)) + "\", \"sched_priority\": " +
           std::to_string(sp.sched_priority) + ", \"cpu_affinity\": [" + cpus + "]}";
}

[[noreturn]] void fail(const std::string &why)
{
    std::printf("{\"error\": \"%s\"}\n", why.c_str());
    std::fflush(stdout);
    std::_Exit(5);   // vsomeip's threads may be blocked; do not wait for them
}

// The checks both modes make on a response's payload; true if it is timed (not a reject).
bool check_payload(long i, const std::uint8_t *d, std::size_t len, std::uint64_t seq, Samples &s)
{
    if (len != kFrame)
        fail("sample " + std::to_string(i) + ": the reply's payload is not 64 bytes");
    std::uint64_t got = 0;
    for (int b = 0; b < 8; b++)
        got |= static_cast<std::uint64_t>(d[b]) << (8 * b);
    if (got != seq)
        fail("sample " + std::to_string(i) + ": the reply's seq is not the request's");
    if (d[kVerdict] != 0) {
        s.rejected++;
        return false;
    }
    return true;
}

void pace(double interval_ms)
{
    if (interval_ms <= 0)
        return;
    const long long ns = static_cast<long long>(interval_ms * 1e6);
    timespec ts{};
    ts.tv_sec = static_cast<time_t>(ns / 1000000000LL);
    ts.tv_nsec = static_cast<long>(ns % 1000000000LL);
    nanosleep(&ts, nullptr);
}

long long ns_between(clk::time_point a, clk::time_point b)
{
    return std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count();
}

// ---- raw: a plain socket, the header by hand

bool recv_all(int fd, std::uint8_t *p, std::size_t n)
{
    while (n > 0) {
        ssize_t k = recv(fd, p, n, 0);
        if (k <= 0)
            return false;
        p += k;
        n -= static_cast<std::size_t>(k);
    }
    return true;
}

void run_raw(bool tcp, const char *host, int port, long n, long warmup, double interval_ms, double timeout_s,
             Samples &s)
{
    int fd = socket(AF_INET, tcp ? SOCK_STREAM : SOCK_DGRAM, 0);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(static_cast<std::uint16_t>(port));
    if (fd < 0 || inet_pton(AF_INET, host, &a.sin_addr) != 1)
        fail("raw: bad socket or address");
    timeval tv{};
    tv.tv_sec = static_cast<time_t>(timeout_s);
    tv.tv_usec = static_cast<suseconds_t>((timeout_s - static_cast<double>(tv.tv_sec)) * 1e6);
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    if (connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof a) != 0)
        fail("raw: connect failed");
    if (tcp) {
        int one = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    }
    const clk::time_point origin = clk::now();
    std::uint8_t msg[kHdr + kFrame], rsp[2048];
    for (long i = 0; i < warmup + n; i++) {
        const std::uint64_t seq = static_cast<std::uint64_t>(i + 1);
        const std::uint16_t sess = session_of(seq);
        const auto f = build_frame(seq);
        const std::uint8_t h[kHdr] = {kService >> 8, kService & 0xFF, kMethod >> 8, kMethod & 0xFF, 0, 0, 0,
                                      8 + kFrame, kRawClient >> 8, kRawClient & 0xFF,
                                      static_cast<std::uint8_t>(sess >> 8), static_cast<std::uint8_t>(sess),
                                      1, kIface, 0x00, 0x00};
        std::memcpy(msg, h, kHdr);
        std::memcpy(msg + kHdr, f.data(), kFrame);
        const auto t0 = clk::now();
        std::size_t got;
        if (tcp) {
            if (send(fd, msg, sizeof msg, 0) != static_cast<ssize_t>(sizeof msg))
                fail("sample " + std::to_string(i) + ": short send");
            if (!recv_all(fd, rsp, kHdr))
                fail("sample " + std::to_string(i) + ": no reply header within the timeout");
            const std::size_t body = ((std::size_t)rsp[4] << 24 | (std::size_t)rsp[5] << 16 |
                                      (std::size_t)rsp[6] << 8 | rsp[7]) - 8;
            if (body > sizeof rsp - kHdr || !recv_all(fd, rsp + kHdr, body))
                fail("sample " + std::to_string(i) + ": no reply body within the timeout");
            got = kHdr + body;
        } else {
            if (send(fd, msg, sizeof msg, 0) != static_cast<ssize_t>(sizeof msg))
                fail("sample " + std::to_string(i) + ": short datagram");
            ssize_t k = recv(fd, rsp, sizeof rsp, 0);
            if (k < static_cast<ssize_t>(kHdr))
                fail("sample " + std::to_string(i) + ": no reply within the timeout");
            got = static_cast<std::size_t>(k);
        }
        const auto t1 = clk::now();
        if (rsp[14] != 0x80 || rsp[15] != 0x00)
            fail("sample " + std::to_string(i) + ": not an E_OK response");
        if (rsp[10] != msg[10] || rsp[11] != msg[11] || rsp[8] != msg[8] || rsp[9] != msg[9])
            fail("sample " + std::to_string(i) + ": the reply's session is not the request's");
        if (check_payload(i, rsp + kHdr, got - kHdr, seq, s) && i >= warmup) {
            s.rtt.push_back(ns_between(t0, t1));
            s.sends.push_back(ns_between(origin, t0));
        }
        pace(interval_ms);
    }
    close(fd);
}

// ---- vsomeip

struct State {
    std::mutex m;
    std::condition_variable cv;
    bool available = false;
    bool got = false;
    clk::time_point t_reply;
    std::shared_ptr<vsomeip::message> reply;
};

void run_vsomeip(bool reliable, long n, long warmup, double interval_ms, double timeout_s, Samples &s)
{
    State st;
    auto rt = vsomeip::runtime::get();
    auto app = rt->create_application("someip_vprobe");
    if (!app->init())
        fail("vsomeip init failed");
    app->register_availability_handler(kService, kInstance,
        [&st](vsomeip::service_t, vsomeip::instance_t, bool is_available) {
            std::lock_guard<std::mutex> g(st.m);
            st.available = is_available;
            st.cv.notify_all();
        });
    app->register_message_handler(kService, kInstance, kMethod,
        [&st](const std::shared_ptr<vsomeip::message> &msg) {
            const auto t = clk::now();
            std::lock_guard<std::mutex> g(st.m);
            st.t_reply = t;
            st.reply = msg;
            st.got = true;
            st.cv.notify_all();
        });
    app->request_service(kService, kInstance);
    std::thread runner([app] { app->start(); });
    {
        std::unique_lock<std::mutex> lk(st.m);
        if (!st.cv.wait_for(lk, std::chrono::seconds(10), [&st] { return st.available; }))
            fail("the service never became available");
    }
    const auto timeout = std::chrono::duration<double>(timeout_s);
    const clk::time_point origin = clk::now();
    for (long i = 0; i < warmup + n; i++) {
        const std::uint64_t seq = static_cast<std::uint64_t>(i + 1);
        auto req = rt->create_request(reliable);
        req->set_service(kService);
        req->set_instance(kInstance);
        req->set_method(kMethod);
        req->set_interface_version(kIface);
        auto pl = rt->create_payload();
        pl->set_data(build_frame(seq));
        req->set_payload(pl);
        {
            std::lock_guard<std::mutex> g(st.m);
            st.got = false;
            st.reply.reset();
        }
        const auto t0 = clk::now();
        app->send(req);
        std::unique_lock<std::mutex> lk(st.m);
        if (!st.cv.wait_for(lk, timeout, [&st] { return st.got; }))
            fail("sample " + std::to_string(i) + ": no reply within the timeout");
        const auto r = st.reply;
        const auto t1 = st.t_reply;
        lk.unlock();
        if (r->get_message_type() != vsomeip::message_type_e::MT_RESPONSE ||
            r->get_return_code() != vsomeip::return_code_e::E_OK)
            fail("sample " + std::to_string(i) + ": not an E_OK response");
        if (r->get_session() != req->get_session())
            fail("sample " + std::to_string(i) + ": the reply's session is not the request's");
        const auto p = r->get_payload();
        if (!p)
            fail("sample " + std::to_string(i) + ": the reply has no payload");
        if (check_payload(i, p->get_data(), p->get_length(), seq, s) && i >= warmup) {
            s.rtt.push_back(ns_between(t0, t1));
            s.sends.push_back(ns_between(origin, t0));
        }
        pace(interval_ms);
    }
    app->stop();
    runner.join();
}

}  // namespace

int main(int argc, char **argv)
{
    const std::string mode = argc > 1 ? argv[1] : "";
    const bool raw = mode == "rawtcp" || mode == "rawudp";
    if ((!raw && argc != 6) || (raw && argc != 8) ||
        (mode != "tcp" && mode != "udp" && !raw)) {
        std::fprintf(stderr, "usage: someip_vprobe tcp|udp|rawtcp|rawudp N WARMUP INTERVAL_MS TIMEOUT_S [HOST PORT]\n");
        return 2;
    }
    const long n = std::atol(argv[2]), warmup = std::atol(argv[3]);
    const double interval_ms = std::atof(argv[4]), timeout_s = std::atof(argv[5]);
    if (n < 1 || warmup < 0 || interval_ms < 0 || timeout_s <= 0) {
        std::fprintf(stderr, "someip_vprobe: bad arguments\n");
        return 2;
    }
    Samples s;
    if (raw)
        run_raw(mode == "rawtcp", argv[6], std::atoi(argv[7]), n, warmup, interval_ms, timeout_s, s);
    else
        run_vsomeip(mode == "tcp", n, warmup, interval_ms, timeout_s, s);

    std::string out = "{\"rtt_ns\": [";
    for (std::size_t k = 0; k < s.rtt.size(); k++)
        out += (k ? ", " : "") + std::to_string(s.rtt[k]);
    out += "], \"send_ns\": [";
    for (std::size_t k = 0; k < s.sends.size(); k++)
        out += (k ? ", " : "") + std::to_string(s.sends[k]);
    out += "], \"rejected\": " + std::to_string(s.rejected) + ", \"sched\": " + sched_json() +
           ", \"vsomeip\": " + (raw ? std::string("null") : "\"" VPROBE_VSOMEIP_VERSION "\"") +
           ", \"mode\": \"" + mode + "\"}";
    std::printf("%s\n", out.c_str());
    std::fflush(stdout);
    return 0;
}
