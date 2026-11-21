"""Config + state helpers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
OUTPUT_DIR = ROOT / "output"


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (does not override variables already set)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.example.yaml"
    with open(p) as f:
        return yaml.safe_load(f)


def env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "")
    if required and not val:
        raise RuntimeError(f"Missing environment variable {name} (see .env.example)")
    return val


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- JSON state
def _state_path(name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{name}.json"


def read_state(name: str, default: Any) -> Any:
    p = _state_path(name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return default


def write_state(name: str, data: Any) -> None:
    p = _state_path(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(p)
