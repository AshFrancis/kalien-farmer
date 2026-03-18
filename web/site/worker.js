/*
    Web Worker — runs the WASM engine off the main thread.
    Communicates with the main page via postMessage.
*/

let engine = null;
let wasmRun = null;
let wasmTapePtr = null;
let wasmTapeLen = null;
let currentPhase = "idle"; // "benchmark" | "run" | "idle"

// Capture engine stdout for progress parsing
function parsePrint(text) {
    // Parse: [BEAM] frame=05200 score=0041470 lives= 7 wave= 7 ...
    const m = text.match(/\[BEAM\]\s+frame=(\d+)\s+score=(\d+)\s+lives=\s*(\d+)\s+wave=\s*(\d+)/);
    if (m) {
        self.postMessage({
            type: "progress",
            phase: currentPhase,
            frame: parseInt(m[1]),
            frames: 36000,
            score: parseInt(m[2]),
            lives: parseInt(m[3]),
            wave: parseInt(m[4]),
        });
    }
}

async function init() {
    try {
        importScripts("kalien.js");
        engine = await KalienEngine({
            mainScriptUrlOrBlob: new URL("kalien.js", self.location.href).href,
            print: parsePrint,
            printErr: (t) => self.postMessage({ type: "log", text: "[stderr] " + t }),
        });
        wasmRun = engine.cwrap("wasm_run", "number",
            ["number", "number", "number", "number", "number", "number", "number", "number"]);
        wasmTapePtr = engine.cwrap("wasm_tape_ptr", "number", []);
        wasmTapeLen = engine.cwrap("wasm_tape_len", "number", []);
        self.postMessage({ type: "ready" });
    } catch (e) {
        self.postMessage({ type: "error", text: "Failed to load WASM engine: " + e.message });
    }
}

function runEngine(seed, salt, beam, threads) {
    const BRANCHES = 8, HORIZON = 20, FRAMES = 36000, WAVE = 7;
    const start = performance.now();
    const score = wasmRun(seed, salt, beam, BRANCHES, HORIZON, FRAMES, WAVE, threads);
    const elapsed = ((performance.now() - start) / 1000).toFixed(1);
    const ptr = wasmTapePtr();
    const len = wasmTapeLen();
    const tapeBytes = engine.HEAPU8.slice(ptr, ptr + len).buffer;
    return { score, tapeBytes, elapsed: parseFloat(elapsed) };
}

self.onmessage = function (e) {
    const msg = e.data;

    if (msg.type === "benchmark") {
        currentPhase = "benchmark";
        // Warmup run — JIT compiles WASM and spins up thread pool
        const warmupBeam = 1024;
        self.postMessage({ type: "benchmark_start", testBeam: warmupBeam });
        self.postMessage({ type: "log", text: "Warmup run (w=1024)..." });
        runEngine(0xDEADBEEF, 0, warmupBeam, msg.threads || 0);

        // Timed run — now WASM is optimized
        const testBeam = 4096;
        self.postMessage({ type: "benchmark_start", testBeam });
        self.postMessage({ type: "log", text: `Benchmark run (w=${testBeam})...` });
        const { score, elapsed } = runEngine(0xDEADBEEF, 0, testBeam, msg.threads || 0);

        const TARGET_SECONDS = 480;
        const maxBeam = Math.floor((TARGET_SECONDS / elapsed) * testBeam);
        // Cap at 24576 — higher widths exceed WASM 2GB memory limit
        const calibrated = Math.min(49152, Math.max(4096, Math.floor(maxBeam / 1024) * 1024));
        currentPhase = "idle";

        self.postMessage({
            type: "benchmark_result",
            testBeam,
            elapsed,
            calibratedBeam: calibrated,
            score,
        });
    } else if (msg.type === "run") {
        currentPhase = "run";
        try {
            const beam = Math.min(msg.beam, 49152); // WASM memory cap
            const { score, tapeBytes, elapsed } = runEngine(
                msg.seed, msg.salt || 0, beam, msg.threads || 0
            );
            currentPhase = "idle";
            self.postMessage(
                { type: "result", score, tapeBytes, elapsed, seed: msg.seed, seedId: msg.seedId,
                  phase: msg.phase || "qualify", pushSalt: msg.pushSalt || 0, pushTotal: msg.pushTotal || 0 },
                [tapeBytes]
            );
        } catch (e) {
            currentPhase = "idle";
            self.postMessage({ type: "error", text: "Engine error: " + e.message });
        }
    }
};

init();
