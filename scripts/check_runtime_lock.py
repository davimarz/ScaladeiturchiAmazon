from __future__ import annotations

import re
import sys
from pathlib import Path


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        result[normalize(name)] = version.strip()
    return result


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_runtime_lock.py LOCK RESOLVED")
    expected = parse(sys.argv[1])
    resolved = parse(sys.argv[2])
    ignored = {"pip", "setuptools", "wheel"}
    resolved = {k: v for k, v in resolved.items() if k not in ignored}
    missing = sorted(set(resolved) - set(expected))
    extra = sorted(set(expected) - set(resolved))
    changed = sorted(
        name for name in set(expected) & set(resolved)
        if expected[name] != resolved[name]
    )
    if not (missing or extra or changed):
        print(f"runtime lock ok: {len(expected)} packages")
        return 0
    if missing:
        print("missing from lock:", ", ".join(f"{n}=={resolved[n]}" for n in missing))
    if extra:
        print("not resolved anymore:", ", ".join(f"{n}=={expected[n]}" for n in extra))
    if changed:
        print("version changes:")
        for name in changed:
            print(f"  {name}: lock={expected[name]} resolved={resolved[name]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
