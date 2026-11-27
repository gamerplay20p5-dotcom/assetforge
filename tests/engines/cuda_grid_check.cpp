#include <ggml.h>
#include <ggml-alloc.h>
#include <ggml-backend.h>
#include <ggml-cuda.h>

#include <cassert>
#include <iostream>
#include <vector>

static void check_transpose(ggml_backend_t backend, int64_t matrices) {
    constexpr int64_t width = 4;
    constexpr int64_t height = 5;
    const size_t elements = width * height * matrices;
    ggml_context * ctx = ggml_init({ggml_graph_overhead() + 3 * ggml_tensor_overhead() + 4096, nullptr, true});
    ggml_tensor * src = ggml_new_tensor_3d(ctx, GGML_TYPE_F32, width, height, matrices);
    ggml_tensor * dst = ggml_cont(ctx, ggml_transpose(ctx, src));
    ggml_cgraph * graph = ggml_new_graph(ctx);
    ggml_build_forward_expand(graph, dst);
    ggml_backend_buffer_t buffer = ggml_backend_alloc_ctx_tensors(ctx, backend);
    assert(buffer);

    std::vector<float> source(elements), result(elements);
    for (size_t i = 0; i < elements; ++i) source[i] = static_cast<float>(i % 65521);
    ggml_backend_tensor_set(src, source.data(), 0, source.size() * sizeof(float));
    assert(ggml_backend_graph_compute(backend, graph) == GGML_STATUS_SUCCESS);
    ggml_backend_tensor_get(dst, result.data(), 0, result.size() * sizeof(float));
    for (int64_t matrix = 0; matrix < matrices; ++matrix) {
        const int64_t offset = matrix * width * height;
        for (int64_t x = 0; x < width; ++x) {
            for (int64_t y = 0; y < height; ++y) {
                assert(result[offset + x * height + y] == source[offset + y * width + x]);
            }
        }
    }
    std::cout << "grid_z=" << (matrices + 7) / 8 << " verified " << elements << " values" << std::endl;
    ggml_backend_buffer_free(buffer);
    ggml_free(ctx);
}

int main() {
    ggml_backend_t backend = ggml_backend_cuda_init(0);
    assert(backend);
    check_transpose(backend, 3);
    check_transpose(backend, 65535 * 8);
    check_transpose(backend, 65535 * 8 + 1);
    ggml_backend_free(backend);
}