"""Verze aplikace (soubor VERSION přibalený do obrazu)."""

from __future__ import annotations

import re
from pathlib import Path

_CANDIDATES = (Path(__file__).resolve().parent.parent / "VERSION", Path(__file__).resolve().parents[2] / "VERSION")
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _read_version() -> str:
    for path in _CANDIDATES:
        try:
            value = path.read_text().strip()
        except OSError:
            continue
        if _SEMVER.match(value):
            return value.lstrip("v")
    return "0.0.0-dev"


VERSION = _read_version()


def parse(version: str) -> tuple | None:
    """Klíč pro porovnání verzí; předběžná verze je nižší než finální."""
    match = _SEMVER.match(version.strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    pre_key: tuple = (1,) if pre is None else (0, *[(0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")])
    return (int(major), int(minor), int(patch), pre_key)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    a, b = parse(candidate), parse(current)
    return a is not None and b is not None and a > b
