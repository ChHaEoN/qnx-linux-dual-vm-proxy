// fma.cu — sustained FP32 FMA load for the Orin iGPU, with reported throughput.
//
// Purpose: give the "L4T keeps the GPU while QNX runs as a KVM guest" claim a
// number instead of an assertion. Run it alone, then again with the QNX guest
// live, and compare. Throughput here is raw FMA ALU throughput, NOT a model
// inference or GEMM figure — do not quote it as either.
#include <cstdio>
#include <cstdlib>
#include <chrono>

__global__ void fma_kernel(float *out, int iters, float a)
{
    float x = threadIdx.x * 1e-3f + blockIdx.x * 1e-6f;
    float y = 1.0000001f;
#pragma unroll 16
    for (int i = 0; i < iters; i++) {
        x = fmaf(x, y, a);
    }
    // Never true; exists only so the compiler cannot delete the loop.
    if (x == 12345.678f) {
        out[0] = x;
    }
}

int main(int argc, char **argv)
{
    int const secs   = (argc > 1) ? atoi(argv[1]) : 30;
    char const *tag  = (argc > 2) ? argv[2] : "run";
    int const blocks = 8 * 64;      // 8 SMs on Orin Nano, oversubscribed
    int const thr    = 256;
    int const iters  = 200000;

    float *d = nullptr;
    if (cudaMalloc(&d, sizeof(float)) != cudaSuccess) {
        printf("FATAL cudaMalloc failed\n");
        return 1;
    }

    cudaDeviceProp p;
    cudaGetDeviceProperties(&p, 0);
    printf("device=%s cc=%d.%d sms=%d tag=%s\n", p.name, p.major, p.minor,
           p.multiProcessorCount, tag);

    fma_kernel<<<blocks, thr>>>(d, 1000, 0.0f);   // warm up
    cudaDeviceSynchronize();

    auto const t0 = std::chrono::steady_clock::now();
    double total_flop = 0.0;
    double best = 0.0, worst = 1e18;
    int round = 0;

    for (;;) {
        auto const r0 = std::chrono::steady_clock::now();
        fma_kernel<<<blocks, thr>>>(d, iters, 0.0f);
        cudaError_t const e = cudaDeviceSynchronize();
        auto const r1 = std::chrono::steady_clock::now();

        if (e != cudaSuccess) {
            printf("FATAL kernel error: %s\n", cudaGetErrorString(e));
            return 1;
        }

        double const dt   = std::chrono::duration<double>(r1 - r0).count();
        double const flop = (double)blocks * thr * iters * 2.0;
        double const g    = flop / dt / 1e9;

        total_flop += flop;
        round++;
        if (g > best)  best = g;
        if (g < worst) worst = g;

        double const elapsed = std::chrono::duration<double>(r1 - t0).count();
        printf("round=%d gflops=%.1f elapsed=%.1f\n", round, g, elapsed);
        fflush(stdout);

        if (elapsed >= secs) {
            printf("SUMMARY tag=%s rounds=%d mean_gflops=%.1f best=%.1f worst=%.1f seconds=%.1f\n",
                   tag, round, total_flop / elapsed / 1e9, best, worst, elapsed);
            fflush(stdout);
            break;
        }
    }
    return 0;
}
