from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Tiny .env loader (no dependency). Real env vars win over the file."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)


def load_config(path: str | Path | None = None) -> dict:
    load_env()
    p = Path(path) if path else ROOT / "config.toml"
    with open(p, "rb") as f:
        cfg = tomllib.load(f)
    fonts = cfg["captions"]["font_path"]
    if isinstance(fonts, list):
        found = [ROOT / f if not f.startswith("/") else Path(f) for f in fonts]
        found = [f for f in found if f.exists()]
        if not found:
            raise SystemExit(f"No caption font found, tried: {fonts}")
        cfg["captions"]["font_path"] = str(found[0])
    return cfg
