/*
    This file is part of kalien-beam project.
    Licensed under the MIT License.
    Author: Fred Kyung-jin Rezeau <hello@kyungj.in>
*/

#pragma once

#ifdef CPU_ONLY
#include "ports/sim.h"
#endif
#include "tape.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

static constexpr int CPU_MAX_BRANCHES = 8;

static const uint8_t CPU_BRANCH_BIAS[CPU_MAX_BRANCHES] = {
    0x0,       // 0: greedy.
    0x4,       // 1: thrust.
    0x1,       // 2: left.
    0x2,       // 3: right.
    0x5,       // 4: thrust+left.
    0x6,       // 5: thrust+right.
    0x8,       // 6: suppress fire.
    0x4 | 0x8, // 7: thrust, suppress fire.
};

static inline uint8_t cpuApplyBias(uint8_t greedy, int branch) {
    uint8_t bias = CPU_BRANCH_BIAS[branch];
    uint8_t out = greedy;
    out |= (bias & 0x7);
    if (bias & 0x8) {
        out &= ~0x8u;
    }
    return out & 0xf;
}

static inline uint8_t cpuClear(const Simulation& sim) {
    if (!sim.ship.canControl) {
        return 0;
    }

    const Ship& ship = sim.ship;
    int32_t best = -1;
    bool isSaucer = false;
    int64_t bestDist = INT64_MAX;

    for (int i = 0; i < 3; i++) {
        if (!sim.saucers[i].alive) {
            continue;
        }
        int32_t dx = shortDX(ship.x, sim.saucers[i].x);
        int32_t dy = shortDY(ship.y, sim.saucers[i].y);
        int32_t dist = (int32_t)sqrtf((float)((int64_t)dx * dx + (int64_t)dy * dy));
        int32_t speed = SHIP_BSPEED_Q88 >> 4;
        int32_t frames = (speed > 0) ? dist / speed : 999;
        uint8_t angle = (uint8_t)simAtan2(dy, dx);
        int32_t delta = ((int32_t)angle - (int32_t)ship.angle + 256) & 0xff;
        if (delta > 128) {
            delta = 256 - delta;
        }
        int64_t time = ((int64_t)delta + frames) >> 2;
        if (time < bestDist) {
            bestDist = time;
            best = i;
            isSaucer = true;
        }
    }
    for (int i = 0; i < ASTEROID_CAP; i++) {
        if (!sim.asteroids[i].alive) {
            continue;
        }
        int32_t dx = shortDX(ship.x, sim.asteroids[i].x);
        int32_t dy = shortDY(ship.y, sim.asteroids[i].y);
        int32_t dist = (int32_t)sqrtf((float)((int64_t)dx * dx + (int64_t)dy * dy));
        int32_t speed = SHIP_BSPEED_Q88 >> 4;
        int32_t frames = (speed > 0) ? dist / speed : 999;
        uint8_t angle = (uint8_t)simAtan2(dy, dx);
        int32_t delta = ((int32_t)angle - (int32_t)ship.angle + 256) & 0xff;
        if (delta > 128) {
            delta = 256 - delta;
        }
        int64_t time = (int64_t)delta + frames;
        if (time < bestDist) {
            bestDist = time;
            best = i;
            isSaucer = false;
        }
    }

    if (best < 0) {
        return 0;
    }

    int32_t tx, ty, tvx, tvy;
    if (isSaucer) {
        tx = sim.saucers[best].x;
        ty = sim.saucers[best].y;
        tvx = sim.saucers[best].vx;
        tvy = sim.saucers[best].vy;
    } else {
        tx = sim.asteroids[best].x;
        ty = sim.asteroids[best].y;
        tvx = sim.asteroids[best].vx;
        tvy = sim.asteroids[best].vy;
    }

    int32_t dx = shortDX(ship.x, tx);
    int32_t dy = shortDY(ship.y, ty);
    int32_t speed = SHIP_BSPEED_Q88 >> 4;
    int32_t lead = (speed > 0) ? min((int32_t)sqrtf((float)((int64_t)dx * dx + (int64_t)dy * dy)) / speed, 60) : 0;
    int32_t pdx = shortDX(ship.x, tx + (tvx >> 4) * lead);
    int32_t pdy = shortDY(ship.y, ty + (tvy >> 4) * lead);
    uint8_t angle = (uint8_t)simAtan2(pdy, pdx);
    int delta = ((int)angle - (int)ship.angle + 256) & 0xff;
    if (delta > 128) {
        delta = 256 - delta;
    }

    int8_t dir = 0;
    {
        int d = ((int)angle - (int)ship.angle + 256) & 0xff;
        if (d != 0) {
            dir = (d <= 128) ? 1 : -1;
        }
    }

    uint8_t inp = 0;
    if (dir == -1) {
        inp |= INPUT_LEFT;
    } else if (dir == 1) {
        inp |= INPUT_RIGHT;
    }

    if (delta <= 18 && ship.fireCooldown == 0 && sim.bulletCount < SHIP_BLIMIT) {
        inp |= INPUT_FIRE;
    }
    return inp & 0xf;
}

// Asteroid protection: check if bullet would hit the largest (protected) asteroid
static inline bool cpuWouldHitAsteroid(const Simulation& sim, uint8_t fireAngle) {
    const Ship& ship = sim.ship;
    int32_t targetIdx = -1;
    int32_t largestSize = 999;
    for (int i = 0; i < ASTEROID_CAP; i++) {
        if (!sim.asteroids[i].alive) continue;
        if (sim.asteroids[i].size < largestSize) {
            largestSize = sim.asteroids[i].size;
            targetIdx = i;
        }
    }
    if (targetIdx < 0) return false;

    int32_t absVx = ship.vx < 0 ? -ship.vx : ship.vx;
    int32_t absVy = ship.vy < 0 ? -ship.vy : ship.vy;
    int32_t shipSpeedApprox = ((absVx + absVy) * 3) >> 2;
    int32_t bulletSpeedQ88 = SHIP_BSPEED_Q88 + ((shipSpeedApprox * 89) >> 8);

    int32_t bvx_aim, bvy_aim;
    simVelocity(fireAngle, bulletSpeedQ88, bvx_aim, bvy_aim);
    int32_t bvx_step = (ship.vx + bvx_aim) >> 4;
    int32_t bvy_step = (ship.vy + bvy_aim) >> 4;

    int32_t spawn_dx, spawn_dy;
    simDisplace(fireAngle, SHIP_RADIUS + 6, spawn_dx, spawn_dy);
    int32_t bx = simWrapX(ship.x + spawn_dx);
    int32_t by = simWrapY(ship.y + spawn_dy);

    const Asteroid& a = sim.asteroids[targetIdx];
    int32_t avx_step = a.vx >> 4;
    int32_t avy_step = a.vy >> 4;

    for (int step = 0; step < 24; step++) {
        int32_t frame = (step + 1) * 3;
        int32_t px = simWrapX(bx + bvx_step * frame);
        int32_t py = simWrapY(by + bvy_step * frame);
        int32_t ax = simWrapX(a.x + avx_step * frame);
        int32_t ay = simWrapY(a.y + avy_step * frame);
        int32_t hitDist = (2 + a.radius) << 4;
        int32_t ddx = shortDX(px, ax);
        int32_t ddy = shortDY(py, ay);
        int32_t addx = ddx < 0 ? -ddx : ddx;
        int32_t addy = ddy < 0 ? -ddy : ddy;
        if (addx <= hitDist && addy <= hitDist) {
            if ((int64_t)ddx * ddx + (int64_t)ddy * ddy <= (int64_t)hitDist * hitDist) {
                return true;
            }
        }
    }
    return false;
}

// Shot verification: check if a bullet fired at fireAngle would hit any saucer (72-frame trajectory)
static inline bool cpuVerifyShotFarm(const Simulation& sim, uint8_t fireAngle) {
    const Ship& ship = sim.ship;
    int32_t absVx = ship.vx < 0 ? -ship.vx : ship.vx;
    int32_t absVy = ship.vy < 0 ? -ship.vy : ship.vy;
    int32_t shipSpeedApprox = ((absVx + absVy) * 3) >> 2;
    int32_t bulletSpeedQ88 = SHIP_BSPEED_Q88 + ((shipSpeedApprox * 89) >> 8);
    int32_t bvx_aim, bvy_aim;
    simVelocity(fireAngle, bulletSpeedQ88, bvx_aim, bvy_aim);
    int32_t bvx_step = (ship.vx + bvx_aim) >> 4;
    int32_t bvy_step = (ship.vy + bvy_aim) >> 4;
    int32_t spawn_dx, spawn_dy;
    simDisplace(fireAngle, SHIP_RADIUS + 6, spawn_dx, spawn_dy);
    int32_t bx = simWrapX(ship.x + spawn_dx);
    int32_t by = simWrapY(ship.y + spawn_dy);
    for (int step = 0; step < 24; step++) {
        int32_t frame = (step + 1) * 3;
        int32_t px = simWrapX(bx + bvx_step * frame);
        int32_t py = simWrapY(by + bvy_step * frame);
        for (int i = 0; i < 3; i++) {
            if (!sim.saucers[i].alive) continue;
            int32_t sx = sim.saucers[i].x + (sim.saucers[i].vx >> 4) * frame;
            if (sx < SAUCER_CULL_MIN_X_Q12_4 || sx > SAUCER_CULL_MAX_X_Q12_4) continue;
            int32_t sy = simWrapY(sim.saucers[i].y + (sim.saucers[i].vy >> 4) * frame);
            int32_t hitDist = (2 + sim.saucers[i].radius + 4) << 4;
            int32_t ddx = shortDX(px, sx);
            int32_t ddy = shortDY(py, sy);
            int32_t addx = ddx < 0 ? -ddx : ddx;
            int32_t addy = ddy < 0 ? -ddy : ddy;
            if (addx <= hitDist && addy <= hitDist) {
                if ((int64_t)ddx * ddx + (int64_t)ddy * ddy <= (int64_t)hitDist * hitDist) {
                    return true;
                }
            }
        }
    }
    return false;
}

// Check if a ship bullet is approaching a saucer (will hit within remaining lifetime)
static inline bool cpuBulletApproachingSaucer(const Simulation& sim, int bi, int si) {
    const Bullet& b = sim.bullets[bi];
    const Saucer& s = sim.saucers[si];
    if (!b.alive || !s.alive) return false;
    int32_t bvx_step = b.vx >> 4;
    int32_t bvy_step = b.vy >> 4;
    int32_t hitDist = (b.radius + s.radius + 3) << 4;
    int32_t maxFrames = b.life < 24 ? b.life : 24;
    for (int step = 0; step < 8; step++) {
        int32_t frame = (step + 1) * 3;
        if (frame > maxFrames) break;
        int32_t px = simWrapX(b.x + bvx_step * frame);
        int32_t py = simWrapY(b.y + bvy_step * frame);
        int32_t sx = s.x + (s.vx >> 4) * frame;
        if (sx < SAUCER_CULL_MIN_X_Q12_4 || sx > SAUCER_CULL_MAX_X_Q12_4) return false;
        int32_t sy = simWrapY(s.y + (s.vy >> 4) * frame);
        int32_t ddx = shortDX(px, sx);
        int32_t ddy = shortDY(py, sy);
        int32_t addx = ddx < 0 ? -ddx : ddx;
        int32_t addy = ddy < 0 ? -ddy : ddy;
        if (addx <= hitDist && addy <= hitDist) {
            if ((int64_t)ddx * ddx + (int64_t)ddy * ddy <= (int64_t)hitDist * hitDist) {
                return true;
            }
        }
    }
    return false;
}

static inline uint8_t cpuFarm(const Simulation& sim) {
    if (!sim.ship.canControl) {
        return 0;
    }
    const Ship& ship = sim.ship;

    // Track which saucers already have bullets heading toward them
    bool covered[3] = {false, false, false};
    for (int bi = 0; bi < SHIP_BLIMIT; bi++) {
        if (!sim.bullets[bi].alive) continue;
        for (int si = 0; si < 3; si++) {
            if (!sim.saucers[si].alive || covered[si]) continue;
            if (cpuBulletApproachingSaucer(sim, bi, si)) {
                covered[si] = true;
            }
        }
    }

    int id = -1;
    int64_t best = INT64_MAX;
    int32_t speed = SHIP_BSPEED_Q88 >> 4;
    for (int i = 0; i < 3; i++) {
        if (!sim.saucers[i].alive) {
            continue;
        }
        int32_t dx = shortDX(ship.x, sim.saucers[i].x);
        int32_t dy = shortDY(ship.y, sim.saucers[i].y);
        int32_t dist = (int32_t)sqrtf((float)((int64_t)dx * dx + (int64_t)dy * dy));
        int32_t frames = (speed > 0) ? dist / speed : 999;
        uint8_t angle = (uint8_t)simAtan2(dy, dx);
        int32_t delta = ((int32_t)angle - (int32_t)ship.angle + 256) & 0xff;
        if (delta > 128) {
            delta = 256 - delta;
        }
        int64_t time = (int64_t)delta + frames;
        int32_t cull = (sim.saucers[i].vx > 0) ? (SAUCER_CULL_MAX_X_Q12_4 - sim.saucers[i].x) : (sim.saucers[i].x - SAUCER_CULL_MIN_X_Q12_4);
        if (cull < 2048) {
            time -= 64;
        }
        // Penalize already-covered saucers (bullet already heading toward them)
        if (covered[i]) {
            time += 100;
        }
        // Chain bonus: prefer saucers with nearby companions (angularly)
        if (sim.saucerCount >= 2) {
            int32_t minGap = 128;
            for (int j = 0; j < 3; j++) {
                if (j == i || !sim.saucers[j].alive) continue;
                int32_t dx2 = shortDX(ship.x, sim.saucers[j].x);
                int32_t dy2 = shortDY(ship.y, sim.saucers[j].y);
                uint8_t aim2 = (uint8_t)simAtan2(dy2, dx2);
                int32_t gap = ((int32_t)angle - (int32_t)aim2 + 256) & 0xff;
                if (gap > 128) gap = 256 - gap;
                if (gap < minGap) minGap = gap;
            }
            if (minGap <= 20) {
                time -= (int64_t)(20 - minGap) * 2;
            }
        }
        if (time < best) {
            best = time;
            id = i;
        }
    }

    uint8_t inp = 0;
    if (id >= 0) {
        int32_t tx = sim.saucers[id].x, ty = sim.saucers[id].y;
        int32_t tvx = sim.saucers[id].vx, tvy = sim.saucers[id].vy;
        // 3-iteration lead prediction for accurate aim
        int32_t pdx = shortDX(ship.x, tx);
        int32_t pdy = shortDY(ship.y, ty);
        uint8_t angle = (uint8_t)simAtan2(pdy, pdx);
        for (int iter = 0; iter < 3; iter++) {
            int32_t dist = (int32_t)sqrtf((float)((int64_t)pdx * pdx + (int64_t)pdy * pdy));
            int32_t lead = (speed > 0) ? std::min(dist / speed, 48) : 0;
            pdx = shortDX(ship.x, tx + (tvx >> 4) * lead);
            pdy = shortDY(ship.y, ty + (tvy >> 4) * lead);
            angle = (uint8_t)simAtan2(pdy, pdx);
        }
        int delta = ((int)angle - (int)ship.angle + 256) & 0xff;
        if (delta > 128) {
            delta = 256 - delta;
        }
        int raw = ((int)angle - (int)ship.angle + 256) & 0xff;
        int8_t dir = (raw == 0) ? 0 : ((raw <= 128) ? 1 : -1);
        if (dir == -1) {
            inp |= INPUT_LEFT;
        } else if (dir == 1) {
            inp |= INPUT_RIGHT;
        }

        if (ship.fireCooldown == 0 && sim.bulletCount < SHIP_BLIMIT) {
            uint8_t fireAngle = (uint8_t)ship.angle;
            if (dir == -1) fireAngle = (ship.angle - SHIP_TURN_SPEED_BAM) & 0xff;
            else if (dir == 1) fireAngle = (ship.angle + SHIP_TURN_SPEED_BAM) & 0xff;
            // Baseline: fire at delta <= 7
            // Expanded: also fire at delta 8-15 if verify confirms hit
            bool canFire = (delta <= 7) ||
                           (delta <= 15 && cpuVerifyShotFarm(sim, fireAngle));
            // Extra: try current angle (before turn) for opportunistic hits
            if (!canFire && dir != 0 && cpuVerifyShotFarm(sim, (uint8_t)ship.angle)) {
                canFire = true;
                fireAngle = (uint8_t)ship.angle;
                inp &= ~(INPUT_LEFT | INPUT_RIGHT);
            }
            if (canFire && !cpuWouldHitAsteroid(sim, fireAngle)) {
                inp |= INPUT_FIRE;
            }
        }
    }
    return inp & 0xf;
}

static inline uint8_t cpuDecide(const Simulation& sim, int32_t wave) {
    if (wave > 0 && sim.wave >= wave && sim.astCount == 1) {
        return cpuFarm(sim);
    }
    return cpuClear(sim);
}

static inline float cpuFitness(const Simulation& sim, int32_t wave) {
    float f = (float)sim.score;
    if ((sim.gameOver && sim.lives <= 0) || (wave > 0 && sim.wave > wave)) {
        f *= 0.01f;
    } else if (wave > 0 && sim.wave == wave && sim.astCount == 1) {
        f += (float)sim.saucerCount * 1000.0f;
        if (!sim.ship.canControl) {
            f -= 2000.0f;
        }
        float r = (float)sim.score / (float)sim.frameCount;
        if (r < 39.04f) {
            f -= (39.04f - r) * 500.0f;
        }
    } else {
        f += (float)sim.wave * 500.0f;
        f += (float)(ASTEROID_CAP - sim.astCount) * 50.0f;
        f -= (float)sim.frameCount * 100.0f;
    }
    return f;
}

static void cpuPrune(const float* fit, int total, int K, std::vector<int>& top) {
    top.resize(total);
    for (int i = 0; i < total; i++) {
        top[i] = i;
    }
    std::nth_element(top.begin(), top.begin() + K, top.end(),
                     [fit](int a, int b) { return fit[a] > fit[b]; });
    top.resize(K);
}

struct CpuChildResult {
    Simulation sim;
    float fit;
    std::vector<uint8_t> nibbles;
};

static void cpuRunChild(
    const Simulation& parent, int branch, int horizon, int32_t wave,
    CpuChildResult& out) {

    Simulation sim = parent;
    int bytes = (horizon + 1) >> 1;
    out.nibbles.assign(bytes, 0);

    if (sim.gameOver) {
        out.sim = sim;
        out.fit = cpuFitness(sim, wave);
        return;
    }

    for (int f = 0; f < horizon && !sim.gameOver; f++) {
        uint8_t greedy = cpuDecide(sim, wave);
        uint8_t inp = cpuApplyBias(greedy, branch);
        int b = f >> 1;
        if (f & 1) {
            out.nibbles[b] |= (inp << 4);
        } else {
            out.nibbles[b] = inp;
        }
        simStep(sim, inp);
    }

    out.sim = sim;
    out.fit = cpuFitness(sim, wave);
}

extern "C" void
runSearchCPU(uint32_t seed, uint32_t salt, int32_t width,
             int32_t horizon, int32_t frames, int32_t wave, int32_t branches, int32_t numThreads,
             int32_t* outScore, uint8_t* outTape, int32_t* outFrames,
             const std::chrono::steady_clock::time_point& start, bool trace) {

    if (branches < 1 || branches > CPU_MAX_BRANCHES) {
        std::fprintf(stderr, "branch count must be 1..%d\n", CPU_MAX_BRANCHES);
        std::exit(EXIT_FAILURE);
    }

    const int size = width * branches;
    const int bytes = (horizon + 1) >> 1;
    const int maxBytes = (frames + 1) >> 1;

    std::vector<Simulation> beam(width);
    simInit(beam[0], seed);
    for (int i = 1; i < width; i++) {
        beam[i] = beam[0];
    }

    std::vector<std::vector<uint8_t>> tapes(width, std::vector<uint8_t>(maxBytes, 0));
    std::vector<CpuChildResult> expanded(size);

    int32_t roundFrames = 0;
    int32_t pos = 0;
    auto last = start;
    const unsigned int maxThreads = std::max(1u, std::thread::hardware_concurrency());
    const unsigned int threads = numThreads > 0 && numThreads < maxThreads ? numThreads : maxThreads;
    while (roundFrames < frames) {
        int curFrames = std::min(horizon, frames - roundFrames);
        int curBytes = (curFrames + 1) >> 1;
        {
            std::vector<std::thread> workers;
            workers.reserve(threads);
            int chunk = (size + (int)threads - 1) / (int)threads;
            for (unsigned int t = 0; t < threads; t++) {
                int lo = t * chunk;
                int hi = std::min(lo + chunk, size);
                if (lo >= hi) {
                    break;
                }
                workers.emplace_back([&, lo, hi, curFrames]() {
                    for (int id = lo; id < hi; id++) {
                        int parent = id / branches;
                        int branch = id % branches;
                        cpuRunChild(beam[parent], branch, curFrames, wave, expanded[id]);
                    }
                });
            }
            for (auto& w : workers) {
                w.join();
            }
        }
        std::vector<float> fit(size);
        uint32_t rng = salt ^ (uint32_t)(roundFrames * 0x9e3779b9u);
        for (int i = 0; i < size; i++) {
            fit[i] = expanded[i].fit;
            rng ^= rng << 13;
            rng ^= rng >> 17;
            rng ^= rng << 5;
            fit[i] += (float)(rng & 0xffff) * (1.0f / 65536.0f) * 500.0f;
        }

        std::vector<int> tops;
        cpuPrune(fit.data(), size, width, tops);
        std::vector<Simulation> newBeam(width);
        std::vector<std::vector<uint8_t>> newTapes(width);
        for (int k = 0; k < width; k++) {
            int child = tops[k];
            int slot = child / branches;
            newBeam[k] = expanded[child].sim;
            newTapes[k] = tapes[slot];
            const auto& win = expanded[child].nibbles;
            for (int f = 0; f < curFrames; f++) {
                int nibPos = pos + f;
                int byteIdx = nibPos >> 1;
                uint8_t nib = (f & 1) ? (win[f >> 1] >> 4) : (win[f >> 1] & 0xf);
                if (nibPos & 1) {
                    newTapes[k][byteIdx] |= (nib << 4);
                } else {
                    newTapes[k][byteIdx] = nib;
                }
            }
        }
        beam = std::move(newBeam);
        tapes = std::move(newTapes);
        pos += curFrames;
        roundFrames += curFrames;

        {
            auto now = std::chrono::steady_clock::now();
            double elapsed = std::chrono::duration<double>(now - last).count();
            if (trace || elapsed >= 10.0 || roundFrames >= frames) {
                int bestSlotNow = 0;
                for (int k = 1; k < width; k++) {
                    if (beam[k].score > beam[bestSlotNow].score) {
                        bestSlotNow = k;
                    }
                }
                const Simulation& b = beam[bestSlotNow];
                int64_t ts = std::chrono::duration_cast<std::chrono::microseconds>(
                                 now.time_since_epoch())
                                 .count();

                if (trace) {
                    auto hwrap = [](int32_t v, int32_t sz) -> int32_t {
                        v %= sz;
                        if (v < 0) {
                            v += sz;
                        }
                        if (v > sz / 2) {
                            v -= sz;
                        }
                        return v;
                    };
                    int32_t sx = b.ship.x >> 4;
                    int32_t sy = b.ship.y >> 4;
                    int32_t spd = (int32_t)(std::sqrt((float)((int64_t)b.ship.vx * b.ship.vx + (int64_t)b.ship.vy * b.ship.vy)) * 100.0f / 256.0f);
                    int32_t minBulletDist = 9999;
                    for (int i = 0; i < SAUCER_BLIMIT; i++) {
                        if (!b.saucerBullets[i].alive) {
                            continue;
                        }
                        int32_t ddx = hwrap(b.ship.x - b.saucerBullets[i].x, WORLD_WIDTH_Q12_4) >> 4;
                        int32_t ddy = hwrap(b.ship.y - b.saucerBullets[i].y, WORLD_HEIGHT_Q12_4) >> 4;
                        int32_t d = (int32_t)std::sqrt((float)((int64_t)ddx * ddx + (int64_t)ddy * ddy));
                        if (d < minBulletDist) {
                            minBulletDist = d;
                        }
                    }
                    int32_t minScDist = 9999, scSmall = 0;
                    for (int i = 0; i < 3; i++) {
                        if (!b.saucers[i].alive) {
                            continue;
                        }
                        int32_t ddx = hwrap(b.ship.x - b.saucers[i].x, WORLD_WIDTH_Q12_4) >> 4;
                        int32_t ddy = hwrap(b.ship.y - b.saucers[i].y, WORLD_HEIGHT_Q12_4) >> 4;
                        int32_t d = (int32_t)std::sqrt((float)((int64_t)ddx * ddx + (int64_t)ddy * ddy));
                        if (d < minScDist) {
                            minScDist = d;
                            scSmall = b.saucers[i].small ? 1 : 0;
                        }
                    }
                    std::printf("[BEAM] frame=%05d score=%07d lives=%2d "
                                "wave=%2d fit=%07.0f time=%lld seed=0x%08X"
                                "  sc=%d sb=%d st=%d tslk=%d"
                                " ship=(%d,%d) spd=%d hdg=%d ctrl=%d"
                                " bul=%d bdist=%d scdist=%d sc=%d ast=%d\n",
                                roundFrames, b.score, b.lives, b.wave,
                                fit[tops[0]], (long long)ts, seed, b.saucerCount, b.saucerBulletCount,
                                b.saucerSpawnTimer, b.timeSinceLastKill, sx, sy, spd, (int32_t)b.ship.angle,
                                b.ship.canControl ? 1 : 0, b.bulletCount, minBulletDist, minScDist, scSmall, b.astCount);
                } else {
                    std::printf("[BEAM] frame=%05d score=%07d lives=%2d "
                                "wave=%2d fit=%07.0f time=%lld seed=0x%08X\n",
                                roundFrames, b.score, b.lives, b.wave, fit[tops[0]], (long long)ts, seed);
                }
                std::fflush(stdout);
                last = now;
            }
        }

        bool allDead = true;
        for (int k = 0; k < width && allDead; k++) {
            if (!beam[k].gameOver) {
                allDead = false;
            }
        }
        if (allDead) {
            break;
        }
    }

    int bestSlot = 0;
    for (int k = 1; k < width; k++) {
        if (beam[k].score > beam[bestSlot].score) {
            bestSlot = k;
        }
    }
    *outScore = beam[bestSlot].score;
    *outFrames = pos;
    memcpy(outTape, tapes[bestSlot].data(), (pos + 1) >> 1);

    std::printf("[BEAM] frame=%05d score=%07d lives=%2d wave=%2d\n", pos, *outScore, beam[bestSlot].lives, beam[bestSlot].wave);
    std::printf("[ENGINE] threads=%u width=%d branches=%d horizon=%d\n", threads, width, branches, horizon);
}