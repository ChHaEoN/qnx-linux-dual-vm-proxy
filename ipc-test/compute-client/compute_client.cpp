// compute_client.cpp — the Compute end of the cross-partition service.
//
// Runs on L4T, on the metal, where the GPU lives. Loads a TensorRT engine,
// classifies a real MNIST image, and sends the claim (class, confidence,
// its own GPU time) across the VM boundary to the QNX guest's safety monitor,
// then reports the monitor's verdict.
//
// The inference is real: a built engine, a real image, real device buffers.
// The class and confidence are computed from the network's output, never
// fabricated -- if this program could not classify, it must fail, not invent.
//
// Ground truth comes from the filename (data/mnist/<digit>.pgm), which lets a
// run show both the accept path and, with --corrupt, the monitor catching a
// claim that is out of contract.
//
// Build on the board:
//   g++ -O2 -std=c++17 -o compute_client compute_client.cpp \
//       -I/usr/include/aarch64-linux-gnu -I../common \
//       -lnvinfer -lcudart -L/usr/local/cuda/lib64
//
// NOT a benchmark. The GPU time reported is one engine execution measured with
// CUDA events; there is no warm-up discipline, no percentiles, and the RTT is
// not a latency measurement.
#include <NvInfer.h>
#include <cuda_runtime_api.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

// Wire layout — must match ipc-test/common/frame.h and the QNX monitor.
static constexpr size_t FRAME_HEADER_BYTES = 16;
static constexpr size_t FRAME_PAYLOAD_BYTES = 48;
static constexpr size_t FRAME_TOTAL_BYTES = FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES;
static constexpr uint8_t P_CLASS = 0, P_CONF = 1, P_INFER_US = 2, P_VERDICT = 6, P_REASON = 7;

static const char *reason_name(uint8_t r)
{
	switch (r) {
	case 0: return "ok";
	case 1: return "class-out-of-range";
	case 2: return "confidence-not-a-percentage";
	case 3: return "confidence-below-threshold";
	case 4: return "inference-time-implausible";
	default: return "unknown";
	}
}

class Logger : public nvinfer1::ILogger {
	void log(Severity s, const char *msg) noexcept override
	{
		if (s <= Severity::kWARNING) {
			std::fprintf(stderr, "[trt] %s\n", msg);
		}
	}
} g_logger;

// P5 binary PGM, as shipped in /usr/src/tensorrt/data/mnist/.
static bool read_pgm(const std::string &path, std::vector<uint8_t> &out, int &w, int &h)
{
	std::ifstream f(path, std::ios::binary);
	if (!f) {
		return false;
	}
	std::string magic;
	int maxval = 0;
	f >> magic >> w >> h >> maxval;
	if (magic != "P5" || w <= 0 || h <= 0) {
		return false;
	}
	f.get();                     // single whitespace byte before the raster
	out.resize(static_cast<size_t>(w) * static_cast<size_t>(h));
	f.read(reinterpret_cast<char *>(out.data()), static_cast<std::streamsize>(out.size()));
	return f.good() || f.eof();
}

int main(int argc, char **argv)
{
	std::string engine_path = "mnist.engine";
	std::string host;
	int port = 7100;
	int digit = 3;
	bool corrupt = false;

	for (int i = 1; i < argc; i++) {
		std::string a = argv[i];
		if (a == "--engine" && i + 1 < argc)      engine_path = argv[++i];
		else if (a == "--host" && i + 1 < argc)   host = argv[++i];
		else if (a == "--port" && i + 1 < argc)   port = std::atoi(argv[++i]);
		else if (a == "--digit" && i + 1 < argc)  digit = std::atoi(argv[++i]);
		else if (a == "--corrupt")                corrupt = true;
		else {
			std::fprintf(stderr,
			    "usage: %s --host <ip> [--port 7100] [--engine mnist.engine]\n"
			    "          [--digit 0..9] [--corrupt]\n", argv[0]);
			return 2;
		}
	}
	if (host.empty()) {
		std::fprintf(stderr, "compute: --host is required\n");
		return 2;
	}

	// --- load the engine -------------------------------------------------
	std::ifstream ef(engine_path, std::ios::binary | std::ios::ate);
	if (!ef) {
		std::fprintf(stderr, "compute: cannot open engine %s\n", engine_path.c_str());
		return 1;
	}
	std::streamsize esz = ef.tellg();
	ef.seekg(0, std::ios::beg);
	std::vector<char> eblob(static_cast<size_t>(esz));
	ef.read(eblob.data(), esz);

	auto *runtime = nvinfer1::createInferRuntime(g_logger);
	auto *engine = runtime->deserializeCudaEngine(eblob.data(), eblob.size());
	if (!engine) {
		std::fprintf(stderr, "compute: deserializeCudaEngine failed\n");
		return 1;
	}
	auto *ctx = engine->createExecutionContext();

	const char *in_name = nullptr, *out_name = nullptr;
	for (int i = 0; i < engine->getNbIOTensors(); i++) {
		const char *n = engine->getIOTensorName(i);
		if (engine->getTensorIOMode(n) == nvinfer1::TensorIOMode::kINPUT)  in_name = n;
		else                                                               out_name = n;
	}
	if (!in_name || !out_name) {
		std::fprintf(stderr, "compute: could not identify engine IO tensors\n");
		return 1;
	}

	auto vol = [](const nvinfer1::Dims &d) {
		int64_t v = 1;
		for (int i = 0; i < d.nbDims; i++) v *= d.d[i];
		return static_cast<size_t>(v);
	};
	size_t in_elems = vol(engine->getTensorShape(in_name));
	size_t out_elems = vol(engine->getTensorShape(out_name));

	// --- real image ------------------------------------------------------
	std::string pgm = "/usr/src/tensorrt/data/mnist/" + std::to_string(digit) + ".pgm";
	std::vector<uint8_t> pix;
	int w = 0, h = 0;
	if (!read_pgm(pgm, pix, w, h) || pix.size() != in_elems) {
		std::fprintf(stderr, "compute: %s unusable (got %zu px, engine wants %zu)\n",
		             pgm.c_str(), pix.size(), in_elems);
		return 1;
	}
	// The sample PGMs are white-on-black inverted relative to the training
	// convention; the shipped samples subtract from 255 the same way.
	std::vector<float> in_host(in_elems);
	for (size_t i = 0; i < in_elems; i++) {
		in_host[i] = (255.0f - static_cast<float>(pix[i])) / 255.0f;
	}

	void *d_in = nullptr, *d_out = nullptr;
	cudaMalloc(&d_in, in_elems * sizeof(float));
	cudaMalloc(&d_out, out_elems * sizeof(float));
	cudaMemcpy(d_in, in_host.data(), in_elems * sizeof(float), cudaMemcpyHostToDevice);
	ctx->setTensorAddress(in_name, d_in);
	ctx->setTensorAddress(out_name, d_out);

	cudaStream_t stream;
	cudaStreamCreate(&stream);
	cudaEvent_t e0, e1;
	cudaEventCreate(&e0);
	cudaEventCreate(&e1);

	cudaEventRecord(e0, stream);
	bool ok = ctx->enqueueV3(stream);
	cudaEventRecord(e1, stream);
	cudaStreamSynchronize(stream);
	if (!ok) {
		std::fprintf(stderr, "compute: enqueueV3 failed\n");
		return 1;
	}
	float gpu_ms = 0.0f;
	cudaEventElapsedTime(&gpu_ms, e0, e1);

	std::vector<float> out_host(out_elems);
	cudaMemcpy(out_host.data(), d_out, out_elems * sizeof(float), cudaMemcpyDeviceToHost);

	// --- interpret the network's own output ------------------------------
	int best = 0;
	for (size_t i = 1; i < out_elems; i++) {
		if (out_host[i] > out_host[best]) best = static_cast<int>(i);
	}
	float maxv = out_host[best], sum = 0.0f;
	for (size_t i = 0; i < out_elems; i++) sum += std::exp(out_host[i] - maxv);
	float conf = 1.0f / sum;                       // softmax at the argmax
	uint32_t infer_us = static_cast<uint32_t>(gpu_ms * 1000.0f + 0.5f);

	std::printf("compute: image=%s truth=%d -> class=%d confidence=%.1f%% gpu=%.3f ms\n",
	            pgm.c_str(), digit, best, conf * 100.0f, gpu_ms);

	uint8_t claim_class = static_cast<uint8_t>(best);
	uint8_t claim_conf = static_cast<uint8_t>(conf * 100.0f + 0.5f);
	if (corrupt) {
		// Deliberately out of contract, to show the monitor rejecting it.
		claim_class = 42;
		std::printf("compute: --corrupt: claiming class=42 (out of the model's label set)\n");
	}

	// --- send the claim across the partition boundary --------------------
	int fd = socket(AF_INET, SOCK_STREAM, 0);
	sockaddr_in a{};
	a.sin_family = AF_INET;
	a.sin_port = htons(static_cast<uint16_t>(port));
	if (inet_pton(AF_INET, host.c_str(), &a.sin_addr) != 1) {
		std::fprintf(stderr, "compute: bad --host\n");
		return 2;
	}
	if (connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof(a)) != 0) {
		std::perror("compute: connect");
		return 1;
	}
	int one = 1;
	setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

	uint8_t frame[FRAME_TOTAL_BYTES]{};
	uint64_t seq = 1;                                  // never FRAME_SENTINEL_SEQ
	std::memcpy(frame, &seq, 8);
	uint64_t ts = 0;
	std::memcpy(frame + 8, &ts, 8);
	frame[FRAME_HEADER_BYTES + P_CLASS] = claim_class;
	frame[FRAME_HEADER_BYTES + P_CONF] = claim_conf;
	std::memcpy(&frame[FRAME_HEADER_BYTES + P_INFER_US], &infer_us, 4);

	if (write(fd, frame, sizeof(frame)) != static_cast<ssize_t>(sizeof(frame))) {
		std::perror("compute: write");
		return 1;
	}
	uint8_t reply[FRAME_TOTAL_BYTES];
	size_t got = 0;
	while (got < sizeof(reply)) {
		ssize_t n = read(fd, reply + got, sizeof(reply) - got);
		if (n <= 0) {
			std::fprintf(stderr, "compute: short reply (%zu bytes)\n", got);
			return 1;
		}
		got += static_cast<size_t>(n);
	}
	close(fd);

	uint8_t verdict = reply[FRAME_HEADER_BYTES + P_VERDICT];
	uint8_t reason = reply[FRAME_HEADER_BYTES + P_REASON];
	std::printf("compute: QNX safety monitor verdict=%s reason=%s\n",
	            verdict == 0 ? "ACCEPT" : "REJECT", reason_name(reason));

	return (verdict == 0) ? 0 : 3;
}
