# Emscripten build for kalien WASM engine
# Requires: emsdk activated (emcc on PATH)

EMCC     = emcc
CXXFLAGS = -O3 -DNDEBUG -DCPU_ONLY -std=c++17 \
           -I../../engine -I../../engine/ports
LDFLAGS  = -s EXPORTED_FUNCTIONS='["_wasm_run","_wasm_tape_ptr","_wasm_tape_len","_malloc","_free"]' \
           -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAPU8"]' \
           -s ALLOW_MEMORY_GROWTH=1 \
           -s INITIAL_MEMORY=268435456 \
           -s MAXIMUM_MEMORY=4294967296 \
           -s USE_PTHREADS=1 \
           -s PTHREAD_POOL_SIZE='navigator.hardwareConcurrency||4' \
           -s ENVIRONMENT='web,worker' \
           -s MODULARIZE=1 \
           -s EXPORT_NAME='KalienEngine' \
           -s NO_EXIT_RUNTIME=1

OUT_DIR = ../site

.PHONY: all clean

all: $(OUT_DIR)/kalien.js

$(OUT_DIR)/kalien.js: kalien_web.cpp
	$(EMCC) $(CXXFLAGS) $(LDFLAGS) -pthread $< -o $@

clean:
	rm -f $(OUT_DIR)/kalien.js $(OUT_DIR)/kalien.wasm $(OUT_DIR)/kalien.worker.js
