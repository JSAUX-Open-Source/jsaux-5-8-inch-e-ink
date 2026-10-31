#!/usr/bin/env python3
"""Extract ABI-matched wheels without requiring pip on immutable SteamOS."""
from __future__ import annotations

import posixpath
import sys
import zipfile
from pathlib import Path


def safe_target(root: Path, member: str) -> Path:
    normalized = posixpath.normpath(member.replace("\\", "/"))
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"unsafe wheel member: {member}")
    target = (root / normalized).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"wheel member escapes target: {member}")
    return target


def extract(root: Path, wheel: Path) -> int:
    count = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = safe_target(root, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    return count


if len(sys.argv) < 3:
    raise SystemExit("usage: runtime_wheel_extract.py <target> <wheel> [wheel ...]")
target = Path(sys.argv[1]).resolve()
target.mkdir(parents=True, exist_ok=True)
total = 0
for raw in sys.argv[2:]:
    wheel = Path(raw)
    total += extract(target, wheel)
    print(f"Extracted {wheel.name}")
print(f"Extracted {total} wheel files into {target}")
