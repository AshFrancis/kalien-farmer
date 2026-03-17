#!/usr/bin/env python3
"""Kalien Web Farmer — unified server.

Serves the dashboard + WASM assets, proxies kalien.xyz API,
and persists run results in a multi-user SQLite database.

Usage:
  python -m web.server                    # localhost:8080
  python -m web.server --port 9000        # custom port
  python -m web.server --host 0.0.0.0     # expose to network
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from web.db import WebDatabase

# ── Paths ────────────────────────────────────────────────────────────
WEB_ROOT = Path(__file__).resolve().parent
SITE_DIR = WEB_ROOT / "site"
DATA_DIR = WEB_ROOT.parent / "web_data"

API_BASE = "https://kalien.xyz"
USER_AGENT = "kalien-web-farmer/1.0"

# ── Shared state ─────────────────────────────────────────────────────
_db: Optional[WebDatabase] = None
_seed_cache: dict[str, Any] = {"ts": 0, "data": None}
_seed_cache_lock = threading.Lock()


def _proxy_request(path: str, method: str = "GET", body: bytes = b"",
                   content_type: str = "") -> tuple[int, bytes, str]:
    """Forward a request to kalien.xyz and return (status, body, content_type)."""
    url = API_BASE + path
    req = Request(url, data=body if body else None, method=method)
    req.add_header("User-Agent", USER_AGENT)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urlopen(req, timeout=120) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "application/json")
            return resp.status, data, ct
    except HTTPError as e:
        return e.code, e.read(), "application/json"
    except Exception as e:
        return 502, json.dumps({"error": str(e)}).encode(), "application/json"


def _get_current_seed() -> Optional[dict[str, Any]]:
    """Fetch current seed from API with 30s cache."""
    now = time.time()
    with _seed_cache_lock:
        if now - _seed_cache["ts"] < 30 and _seed_cache["data"]:
            return _seed_cache["data"]
    try:
        req = Request(f"{API_BASE}/api/seed/current",
                      headers={"User-Agent": USER_AGENT})
        data = json.loads(urlopen(req, timeout=10).read())
        with _seed_cache_lock:
            _seed_cache["ts"] = now
            _seed_cache["data"] = data
        return data
    except Exception:
        return _seed_cache.get("data")


def _build_seeds(db: WebDatabase, claimant: str) -> list[dict[str, Any]]:
    """Build /api/seeds response matching native dashboard format."""
    seeds = db.read_seeds(claimant)
    current = _get_current_seed()
    csid = current["seed_id"] if current else 0

    result = []
    for s in seeds:
        sid = s["seed_id"]
        age_min = (csid - sid) * 10 if csid else 0
        rem_min = 24 * 60 - age_min
        best = max(s.get("qualify_score", 0) or 0, s.get("push_score", 0) or 0)
        result.append({
            "seed": s["seed_hex"],
            "seed_id": sid,
            "age_min": age_min,
            "remaining_min": rem_min,
            "qualify_score": s.get("qualify_score", 0),
            "push_status": s.get("push_status", "none"),
            "push_beam": s.get("push_beam", 0),
            "push_score": s.get("push_score", 0),
            "push_salts_done": s.get("push_salts_done", 0),
            "push_salts_total": s.get("push_salts_total", 0),
            "queue_pos": None,
            "is_running": False,
            "submitted_score": s.get("submitted_score", 0),
            "submitted_job_id": s.get("submitted_job_id", ""),
        })
    return result


def _build_stats(db: WebDatabase, claimant: str) -> dict[str, Any]:
    """Build /api/stats response matching native dashboard format."""
    seeds = db.read_seeds(claimant)
    scores = []
    for s in reversed(seeds):
        best = max(s.get("qualify_score", 0) or 0, s.get("push_score", 0) or 0)
        if best > 0:
            scores.append({
                "seed_id": s["seed_id"],
                "seed": s["seed_hex"],
                "qualify": s.get("qualify_score", 0) or 0,
                "push": s.get("push_score", 0) or 0,
                "best": best,
            })
    return {"scores": scores[-100:]}


# ── Proof status cache ───────────────────────────────────────────────
_proof_cache: dict[str, dict] = {}
_proof_cache_ttl = 60.0


def _fetch_proof_status(job_id: str) -> dict[str, Any]:
    now = time.time()
    cached = _proof_cache.get(job_id)
    if cached and now - cached.get("_ts", 0) < _proof_cache_ttl:
        return cached
    try:
        req = Request(f"{API_BASE}/api/proofs/jobs/{job_id}",
                      headers={"User-Agent": USER_AGENT})
        data = json.loads(urlopen(req, timeout=10).read())
        job = data.get("job", {})
        result = {
            "status": job.get("status", "unknown"),
            "score": job.get("tape", {}).get("metadata", {}).get("finalScore", 0),
            "prover": job.get("prover", {}).get("status", ""),
            "claim": job.get("claim", {}).get("status", ""),
            "replay_url": f"https://kalien.xyz/replay/{job_id}",
            "_ts": now,
        }
        _proof_cache[job_id] = result
        return result
    except Exception:
        return {"status": "unknown", "replay_url": f"https://kalien.xyz/replay/{job_id}", "_ts": now}


def _build_proofs(db: WebDatabase, claimant: str) -> dict[str, Any]:
    seeds = db.read_seeds(claimant)
    proofs = {}
    for s in seeds:
        jid = s.get("submitted_job_id", "")
        if jid:
            proofs[s["seed_hex"]] = _fetch_proof_status(jid)
    return proofs


# ── HTTP Handler ─────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence

    def _headers(self):
        """Add COOP/COEP and CORS headers."""
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Claimant")

    def _json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._headers()
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _claimant(self) -> str:
        """Extract claimant from X-Claimant header."""
        return self.headers.get("X-Claimant", "").strip()

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self._headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── API proxy ──
        if path.startswith("/proxy/"):
            api_path = "/api/" + path[7:]
            qs = parsed.query
            if qs:
                api_path += "?" + qs
            status, body, ct = _proxy_request(api_path)
            self.send_response(status)
            self.send_header("Content-Type", ct)
            self._headers()
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ── Local API ──
        claimant = self._claimant()

        if path == "/api/seeds":
            self._json(_build_seeds(_db, claimant) if claimant else [])
        elif path == "/api/stats":
            self._json(_build_stats(_db, claimant) if claimant else {"scores": []})
        elif path == "/api/proofs":
            self._json(_build_proofs(_db, claimant) if claimant else {})
        elif path == "/api/status":
            # Web farmer status is client-driven; return minimal
            current = _get_current_seed()
            self._json({
                "state": {},
                "progress": {},
                "connected": current is not None,
                "current_seed_id": current["seed_id"] if current else 0,
                "queue_length": 0,
            })
        elif path == "/api/queue":
            self._json([])
        elif path == "/api/tapes":
            self._json(self._build_tapes(claimant))
        elif path == "/api/runner":
            self._json({"ok": True, "running": False, "paused": False, "pid": None})
        elif path == "/api/settings":
            self._json(self._load_user_settings(claimant))
        elif path == "/api/setup":
            settings = self._load_user_settings(claimant)
            claimant_ok = bool(claimant and len(claimant) == 56 and claimant[0] in "GC")
            self._json({
                "engine_found": True,  # WASM is always available
                "engine_path": "WebAssembly",
                "settings_configured": claimant_ok,
                "claimant": claimant,
                "benchmark_done": bool(settings.get("benchmark")),
                "benchmark": settings.get("benchmark", {}),
                "os": "Browser",
                "python_version": "",
            })
        elif path == "/api/log":
            self._json({"lines": [], "total": 0})
        elif path == "/api/global":
            self._json(self._build_global())
        elif path == "/api/check_seed":
            seed_hex = params.get("seed", [""])[0].upper()
            qualified = _db.already_qualified(claimant, seed_hex) if claimant else False
            self._json({"qualified": qualified})
        else:
            # ── Static files ──
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))

        # ── API proxy ──
        if path.startswith("/proxy/"):
            api_path = "/api/" + path[7:]
            qs = parsed.query
            if qs:
                api_path += "?" + qs
            body = self.rfile.read(length) if length else b""
            ct = self.headers.get("Content-Type", "")
            status, resp_body, resp_ct = _proxy_request(api_path, "POST", body, ct)
            self.send_response(status)
            self.send_header("Content-Type", resp_ct)
            self._headers()
            self._cors()
            self.end_headers()
            self.wfile.write(resp_body)
            return

        body = json.loads(self.rfile.read(length)) if length else {}
        claimant = self._claimant()

        if path == "/api/record_run":
            self._handle_record_run(claimant, body)
        elif path == "/api/settings":
            self._save_user_settings(claimant, body)
            self._json({"ok": True})
        else:
            self.send_error(404)

    def _handle_record_run(self, claimant: str, body: dict):
        """Record a completed run: save to DB, save tape to disk."""
        if not claimant:
            self._json({"ok": False, "error": "No claimant"}, 400)
            return

        seed_hex = body.get("seed_hex", "").upper()
        seed_id = body.get("seed_id", 0)
        score = body.get("score", 0)
        salt = body.get("salt", "0x00000000")
        elapsed = body.get("elapsed", 0)
        tape_b64 = body.get("tape_b64", "")
        job_id = body.get("job_id", "")

        _db.record_seed(claimant, seed_hex, seed_id)
        _db.update_qualify(claimant, seed_hex, score, salt, elapsed)

        if job_id:
            _db.update_submitted(claimant, seed_hex, score, job_id)

        # Save tape to disk
        if tape_b64:
            tape_dir = DATA_DIR / "tapes" / claimant[:8] / seed_hex.lower()
            tape_dir.mkdir(parents=True, exist_ok=True)
            tape_bytes = base64.b64decode(tape_b64)
            tape_path = tape_dir / f"run_0_{score}.tape"
            tape_path.write_bytes(tape_bytes)

        self._json({"ok": True, "seed": seed_hex, "score": score})

    def _build_global(self) -> dict[str, Any]:
        """Build global leaderboard across all users."""
        runs = _db.read_all_runs()
        current = _get_current_seed()
        csid = current["seed_id"] if current else 0
        entries = []
        for r in runs:
            sid = r["seed_id"]
            age_min = (csid - sid) * 10 if csid else 0
            c = r["claimant"]
            entries.append({
                "claimant_short": c[:4] + "..." + c[-4:] if len(c) > 12 else c,
                "claimant": c,
                "seed": r["seed_hex"],
                "seed_id": sid,
                "age": age_min,
                "score": r["qualify_score"] or 0,
                "elapsed": r["qualify_elapsed"] or 0,
                "submitted": r["submitted_score"] or 0,
                "job_id": r["submitted_job_id"] or "",
                "time": r["updated_at"] or "",
            })
        # Unique users
        users = set(r["claimant"] for r in runs)
        total_runs = len(runs)
        best = max((r["qualify_score"] or 0 for r in runs), default=0)
        return {
            "runs": entries[:500],
            "total_users": len(users),
            "total_runs": total_runs,
            "best_score": best,
        }

    def _build_tapes(self, claimant: str) -> list[dict[str, Any]]:
        if not claimant:
            return []
        import re
        from datetime import datetime
        tapes_dir = DATA_DIR / "tapes" / claimant[:8]
        if not tapes_dir.exists():
            return []
        tapes = []
        for d in sorted(tapes_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            seed = d.name.upper()
            for t in sorted(d.glob("*.tape"), key=lambda f: f.stat().st_mtime, reverse=True):
                m = re.search(r"_(\d+)_(\d+)\.tape$", t.name)
                if m:
                    tapes.append({
                        "seed": seed,
                        "salt": int(m.group(1)),
                        "score": int(m.group(2)),
                        "file": t.name,
                        "path": str(t),
                        "size": t.stat().st_size,
                        "time": datetime.fromtimestamp(t.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
        return tapes[:200]

    def _load_user_settings(self, claimant: str) -> dict[str, Any]:
        defaults = {"claimant": claimant, "push_threshold": 1190000}
        if not claimant:
            return defaults
        path = DATA_DIR / "settings" / f"{claimant[:16]}.json"
        try:
            if path.exists():
                data = json.loads(path.read_text())
                defaults.update(data)
        except Exception:
            pass
        defaults["claimant"] = claimant
        return defaults

    def _save_user_settings(self, claimant: str, data: dict):
        if not claimant:
            return
        settings_dir = DATA_DIR / "settings"
        settings_dir.mkdir(parents=True, exist_ok=True)
        path = settings_dir / f"{claimant[:16]}.json"
        existing = {}
        try:
            if path.exists():
                existing = json.loads(path.read_text())
        except Exception:
            pass
        existing.update(data)
        path.write_text(json.dumps(existing, indent=2))

    def _serve_static(self, path: str):
        if path == "/" or path == "":
            path = "/dashboard.html"
        file_path = SITE_DIR / path.lstrip("/")
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        ext = file_path.suffix.lower()
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".wasm": "application/wasm",
            ".json": "application/json",
            ".css": "text/css",
            ".png": "image/png",
        }
        ct = content_types.get(ext, "application/octet-stream")
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self._headers()
        if ext in (".wasm", ".js"):
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)


# ── Main ─────────────────────────────────────────────────────────────
def main():
    global _db, DATA_DIR

    parser = argparse.ArgumentParser(description="Kalien Web Farmer Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--dir", type=str, help="Data directory")
    args = parser.parse_args()

    if args.dir:
        DATA_DIR = Path(args.dir)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _db = WebDatabase(DATA_DIR / "kalien_web.db")
    _db.init_schema()

    # Background seed refresh
    def _refresh_loop():
        while True:
            _get_current_seed()
            time.sleep(30)

    threading.Thread(target=_refresh_loop, daemon=True).start()
    _get_current_seed()

    url = f"http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}"
    print(f"\n  \u2554{'=' * 42}\u2557")
    print(f"  \u2551  KALIEN WEB FARMER                      \u2551")
    print(f"  \u2551  {url:<39s} \u2551")
    print(f"  \u255a{'=' * 42}\u255d\n")

    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
