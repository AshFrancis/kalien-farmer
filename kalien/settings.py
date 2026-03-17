"""Settings load/save/validation for the runner and dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kalien.config import DEFAULT_PUSH_THRESHOLD

# ── Defaults ──────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict[str, Any] = {
    "claimant": "",
    "push_threshold": DEFAULT_PUSH_THRESHOLD,
    "qualify_beam": 32768,
    "push_beam": 65536,
}

CLAIMANT_PLACEHOLDERS: set[str] = {"", "YOUR_STELLAR_ADDRESS_HERE", "YOUR_ADDRESS_HERE"}


# ── Validation ────────────────────────────────────────────────────────
def is_valid_claimant(claimant: str) -> bool:
    """Return *True* if *claimant* looks like a real Stellar address.

    Rejects empty strings, well-known placeholder values, and strings
    that do not match the expected format (56 characters starting with
    ``G`` or ``C``).
    """
    if not claimant or claimant.upper() in CLAIMANT_PLACEHOLDERS:
        return False
    # Stellar addresses start with G (public) or C (contract), 56 chars
    if len(claimant) == 56 and claimant[0] in "GC":
        return True
    return False


# ── Persistence ───────────────────────────────────────────────────────
def load_settings(path: Path) -> dict[str, Any]:
    """Load settings from *path*, filling in defaults for missing keys.

    Note: ``claimant`` defaults to the empty string.  The runner will
    skip submissions if no claimant is configured — it never falls back
    to a hardcoded address.
    """
    settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
    try:
        if path.exists():
            data = json.loads(path.read_text())
            settings.update(data)
    except Exception:
        pass
    return settings


def save_settings(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Merge *data* into the settings file at *path* and return the result."""
    settings = load_settings(path)
    settings.update(data)
    path.write_text(json.dumps(settings, indent=2))
    return {"ok": True, "settings": settings}
