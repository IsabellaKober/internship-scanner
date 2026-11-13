from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["profile"] = load_profile()
    return cfg


def load_profile() -> dict:
    """The personal profile is NOT in the public repo.
    GitHub Actions: secret PROFILE_YAML.  Local runs: profile.local.yaml
    (git-ignored)."""
    raw = os.environ.get("PROFILE_YAML")
    if not raw:
        p = ROOT / "profile.local.yaml"
        if p.exists():
            raw = p.read_text(encoding="utf-8")
    if not raw:
        return {"summary": "", "highlights": []}
    return yaml.safe_load(raw) or {}
