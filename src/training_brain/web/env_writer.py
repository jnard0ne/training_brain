"""In-place editor for the project's .env file.

Preserves ordering, comments, and unrelated keys. Writes atomically via a
temp file + rename so a crash mid-write can't corrupt secrets.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def env_path() -> Path:
    """Resolve the .env file at the repo root."""
    return Path(__file__).resolve().parents[3] / ".env"


def read_keys(keys: list[str]) -> dict[str, str | None]:
    """Return the current value of each requested key (None if absent)."""
    path = env_path()
    out: dict[str, str | None] = {k: None for k in keys}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        k = k.strip()
        if k in out:
            out[k] = _strip_quotes(v.strip())
    return out


def write_keys(updates: dict[str, str]) -> None:
    """Update or insert each key=value pair, preserving the rest of the file."""
    path = env_path()
    existing_lines = path.read_text().splitlines(keepends=True) if path.exists() else []

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k, _, _ = stripped.partition("=")
        k = k.strip()
        if k in remaining:
            new_lines.append(f"{k}={_quote(remaining.pop(k))}\n")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        for k, v in remaining.items():
            new_lines.append(f"{k}={_quote(v)}\n")

    fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def _quote(v: str) -> str:
    if any(c in v for c in (" ", "#", '"', "'", "\t")):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return v
