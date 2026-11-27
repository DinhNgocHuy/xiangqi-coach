"""Write the licence folder shipped with the installer (Tauri resource "licenses/").

    python backend/packaging/collect_licenses.py --out backend/dist/licenses

Contents: LICENSE-GPL-3.0.txt (repo LICENSE), NOTICE.txt (this app + GPL sources), THIRD_PARTY_LICENSES.txt
(every runtime dependency of the backend, found by walking its requirements, with the licence files from each
installed dist-info). Run in the environment PyInstaller builds from so versions match the bundle.
"""

from __future__ import annotations

import argparse
import re
import shutil
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "xiangqi-coach-backend"
LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)

NOTICE = """Live Xiangqi Screen Coach
Copyright (C) the Live Xiangqi Screen Coach authors.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
Public License version 3 (LICENSE-GPL-3.0.txt). It comes WITHOUT ANY WARRANTY.
Source code: https://github.com/DinhNgocHuy/xingqi-coach

GPL-3.0 components shipped in this installer:
- Backend (backend/xqc-backend.exe) links pyffish {pyffish} (Fairy-Stockfish move generator, GPL-3.0).
  Source: https://github.com/fairy-stockfish/Fairy-Stockfish and https://pypi.org/project/pyffish/{pyffish}/
- Pikafish engine (pikafish/): GPL-3.0, see pikafish/Copying.txt, pikafish/NNUE-License.md and
  pikafish/SOURCE.txt (exact release + source link). Runs as a separate process over UCI.

Other bundled components and their licences: THIRD_PARTY_LICENSES.txt.
The backend is packaged with PyInstaller (GPL-2.0 with bootloader exception) and runs on CPython (PSF-2.0).
"""


def runtime_dists(root: str) -> dict[str, metadata.Distribution]:
    """`root` and everything it needs at runtime (no extras), keyed by canonical name."""
    found: dict[str, metadata.Distribution] = {}
    todo = [root]
    while todo:
        name = canonicalize_name(todo.pop())
        if name in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # optional/platform-specific dependency not installed here
        found[name] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                todo.append(req.name)
    return found


def license_of(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    lic = (meta.get("License") or "").strip()
    return ", ".join(classifiers) or (lic.splitlines()[0] if lic else "UNKNOWN")


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    out = []
    for f in dist.files or []:
        if ".dist-info" in str(f) and LICENSE_FILE.match(f.name):
            out.append((str(f), Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    dists = runtime_dists(PROJECT)
    if canonicalize_name(PROJECT) not in dists:
        raise SystemExit(f"{PROJECT} is not installed (pip install -e backend)")
    del dists[canonicalize_name(PROJECT)]

    shutil.copyfile(ROOT / "LICENSE", args.out / "LICENSE-GPL-3.0.txt")
    pyffish = dists.get("pyffish")
    (args.out / "NOTICE.txt").write_text(NOTICE.format(pyffish=pyffish.version if pyffish else "?"), encoding="utf-8")

    parts = []
    for _, dist in sorted(dists.items()):
        name, version = dist.metadata["Name"], dist.version
        head = f"{'=' * 78}\n{name} {version} — {license_of(dist)}\n"
        home = dist.metadata.get("Home-page") or next(iter(dist.metadata.get_all("Project-URL") or []), "")
        texts = license_texts(dist)
        if not texts:
            head += f"(no licence file in the distribution; see {home or 'https://pypi.org/project/' + name})\n"
        parts.append(head + "".join(f"\n--- {path} ---\n{text}\n" for path, text in texts))
    (args.out / "THIRD_PARTY_LICENSES.txt").write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {len(dists)} packages to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
