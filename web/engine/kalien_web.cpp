/*
    WASM entry point for kalien beam search.
    Wraps runSearchCPU from kernel.h and serializes tape output to memory.
*/

#ifndef CPU_ONLY
#define CPU_ONLY
#endif

#include <cstdint>
#include <cstdio>
#include <chrono>
#include <vector>

#include "../../engine/ports/sim.h"
#include "../../engine/tape.h"
#include "../../engine/kernel.h"

#include <emscripten.h>

// Shared buffer for the serialized tape output.
static std::vector<uint8_t> g_tape_buf;

extern "C" {

// Run a single beam search and return a pointer to the serialized tape.
// Returns 0 on failure.  Caller reads tape via wasm_tape_ptr/wasm_tape_len.
EMSCRIPTEN_KEEPALIVE
int wasm_run(uint32_t seed, uint32_t salt, int32_t width,
             int32_t branches, int32_t horizon, int32_t frames,
             int32_t wave, int32_t threads) {

    const int32_t bytes = (frames + 1) >> 1;
    std::vector<uint8_t> tape(bytes, 0);
    int32_t outScore = 0, outFrames = 0;

    auto start = std::chrono::steady_clock::now();

    runSearchCPU(seed, salt, width, horizon, frames, wave, branches, threads,
                 &outScore, tape.data(), &outFrames, start, false);

    // Build tape file in memory (same format as native .tape files)
    Tape t;
    for (int32_t i = 0; i < outFrames; i++) {
        int b = i >> 1;
        uint8_t n = (i & 1) ? (tape[b] >> 4) : (tape[b] & 0xf);
        t.add(n);
    }

    // Serialize to buffer
    // We need access to Tape::serialize which is private, so replicate the
    // serialisation here (same logic as tape.h).
    {
        const uint32_t count = (uint32_t)outFrames;
        const uint32_t tapeBytes = (count + 1) >> 1;
        const size_t total = TAPE_HEADER_SIZE + tapeBytes + TAPE_FOOTER_SIZE;
        g_tape_buf.resize(total, 0);
        auto writeU32 = [&](size_t off, uint32_t v) {
            g_tape_buf[off + 0] = v & 0xFF;
            g_tape_buf[off + 1] = (v >> 8) & 0xFF;
            g_tape_buf[off + 2] = (v >> 16) & 0xFF;
            g_tape_buf[off + 3] = (v >> 24) & 0xFF;
        };
        writeU32(0, TAPE_MAGIC);
        g_tape_buf[4] = TAPE_VERSION;
        g_tape_buf[5] = TAPE_RULES_TAG;
        writeU32(8, seed);
        writeU32(12, count);

        // Pack nibbles from the raw beam tape
        for (int32_t i = 0; i < (int32_t)tapeBytes; i++) {
            uint8_t lo = 0, hi = 0;
            int idx0 = 2 * i;
            int idx1 = 2 * i + 1;
            if (idx0 < outFrames) {
                int b0 = idx0 >> 1;
                lo = (idx0 & 1) ? (tape[b0] >> 4) : (tape[b0] & 0xf);
            }
            if (idx1 < outFrames) {
                int b1 = idx1 >> 1;
                hi = (idx1 & 1) ? (tape[b1] >> 4) : (tape[b1] & 0xf);
            }
            g_tape_buf[TAPE_HEADER_SIZE + i] = (lo & 0x0F) | ((hi & 0x0F) << 4);
        }

        const size_t offset = TAPE_HEADER_SIZE + tapeBytes;
        writeU32(offset, (uint32_t)outScore);
        writeU32(offset + 4, crc32(g_tape_buf.data(), offset));
    }

    return outScore;
}

EMSCRIPTEN_KEEPALIVE
uint8_t* wasm_tape_ptr() {
    return g_tape_buf.data();
}

EMSCRIPTEN_KEEPALIVE
int wasm_tape_len() {
    return (int)g_tape_buf.size();
}

}  // extern "C"
