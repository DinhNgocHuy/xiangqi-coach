"""Download the pinned official Pikafish release into <repo>/engine/pikafish/.

    cd backend && .venv/bin/pip install -e '.[engine-setup]' && .venv/bin/python scripts/fetch_pikafish.py

The archive must match PINNED_SHA256 (also with --archive). --allow-unpinned fetches the latest release instead and
then requires GitHub's sha256 digest for the asset; to move the pin, update PINNED_* after checking the new release.

Writes engine/pikafish/{pikafish[.exe], pikafish.nnue, Copying.txt, NNUE-License.md, SOURCE.txt}.
Pikafish is GPL-3.0: Copying.txt (the licence) and SOURCE.txt (tag + source link) must ship with the binary.
The release ships "universal" binaries (runtime CPU dispatch), so only OS/arch has to be chosen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "official-pikafish/Pikafish"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PINNED_TAG = "Pikafish-2026-09-06"
PINNED_ASSET = "Pikafish.2026-09-06.7z"
PINNED_SIZE = 53603424
PINNED_SHA256 = "41952bbfe2520faceb5902c69e6ab4845cc999841d2b49a95cc1be7867a25e5b"
DEST = Path(__file__).resolve().parents[2] / "engine" / "pikafish"
EXTRA_FILES = ("pikafish.nnue", "Copying.txt", "NNUE-License.md")
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


def pick_binary(names: list[str], system: str | None = None, machine: str | None = None) -> str:
    """Name of the binary inside the archive for this OS/CPU."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        wanted = "windows-x86-64"
    elif system == "darwin":
        wanted = "macos"
    elif system == "linux" and machine in ("x86_64", "amd64"):
        wanted = "linux-x86-64"
    elif system == "linux" and machine in ("aarch64", "arm64"):
        wanted = "android-arm64"  # ponytail: static arm64 build; untested on Linux arm64 desktops
    else:
        raise SystemExit(f"no Pikafish binary for {system}/{machine}")
    # top-level entries only; never a name that could escape the extraction dir
    safe = [n for n in names if "/" not in n and "\\" not in n and ".." not in n]
    candidates = sorted(n for n in safe if n.lower().startswith("pikafish-") and wanted in n.lower())
    # Prefer "universal" (CPU dispatch at runtime); fall back to any matching build.
    universal = [n for n in candidates if "universal" in n.lower()]
    if not (universal or candidates):
        raise SystemExit(f"archive has no binary for {wanted}: {names}")
    return (universal or candidates)[0]


def _get(url: str, accept: str = "application/octet-stream") -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "xiangqi-coach-fetch"})


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def expected_sha256(digest: str | None) -> str:
    """GitHub asset digest "sha256:<hex>" -> hex; anything else is an error (never install unverified)."""
    algo, _, value = (digest or "").partition(":")
    if algo != "sha256" or len(value) != 64:
        raise SystemExit(f"release asset has no sha256 digest ({digest!r}); refusing to install")
    return value.lower()


def download(url: str, size: int, sha256: str, out: Path) -> None:
    if size > MAX_ARCHIVE_BYTES:
        raise SystemExit(f"asset too large: {size} bytes")
    h = hashlib.sha256()
    got = 0
    with urllib.request.urlopen(_get(url), timeout=60) as r, out.open("wb") as f:
        while chunk := r.read(1 << 20):
            got += len(chunk)
            if got > size:
                raise SystemExit("download larger than announced size")
            h.update(chunk)
            f.write(chunk)
    if got != size:
        raise SystemExit(f"size mismatch: got {got}, expected {size}")
    if h.hexdigest() != sha256:
        raise SystemExit(f"sha256 mismatch: got {h.hexdigest()}, expected {sha256}")
    print(f"downloaded {got} bytes, sha256 {h.hexdigest()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=Path, default=DEST)
    ap.add_argument("--archive", type=Path, help=f"use an already downloaded {PINNED_ASSET} (sha256 still checked)")
    ap.add_argument(
        "--allow-unpinned", action="store_true", help="latest release, verified only by GitHub's digest (not the pin)"
    )
    args = ap.parse_args()

    import py7zr  # optional dependency: pip install -e '.[engine-setup]'

    if args.allow_unpinned:
        with urllib.request.urlopen(_get(API, "application/vnd.github+json"), timeout=30) as r:
            release = json.load(r)
        tag, html_url = release["tag_name"], release["html_url"]
        asset = next((a for a in release["assets"] if a["name"].endswith(".7z")), None)
        if asset is None:
            raise SystemExit(f"release {tag} has no .7z asset")
        url, size = asset["browser_download_url"], asset["size"]
        sha256 = None if args.archive else expected_sha256(asset.get("digest"))
    else:
        tag, html_url = PINNED_TAG, f"https://github.com/{REPO}/releases/tag/{PINNED_TAG}"
        url = f"https://github.com/{REPO}/releases/download/{tag}/{PINNED_ASSET}"
        size, sha256 = PINNED_SIZE, PINNED_SHA256

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = args.archive or tmpdir / url.rsplit("/", 1)[1]
        if not args.archive:
            print(f"downloading {archive.name} ({size} bytes) from {tag}")
            download(url, size, sha256, archive)  # type: ignore[arg-type]
        elif sha256 and (got := sha256_of(archive)) != sha256:
            raise SystemExit(f"{archive}: sha256 {got} does not match the pinned {sha256}")
        with py7zr.SevenZipFile(archive) as z:
            names = z.getnames()
        binary = pick_binary(names)
        missing = [n for n in EXTRA_FILES if n not in names]
        if missing:
            raise SystemExit(f"archive is missing {missing}")
        out = tmpdir / "x"
        with py7zr.SevenZipFile(archive) as z:
            z.extract(path=out, targets=[binary, *EXTRA_FILES])

        args.dest.mkdir(parents=True, exist_ok=True)
        exe = args.dest / ("pikafish.exe" if binary.lower().endswith(".exe") else "pikafish")
        shutil.copyfile(out / binary, exe)
        exe.chmod(0o755)
        for name in EXTRA_FILES:
            shutil.copyfile(out / name, args.dest / name)

    (args.dest / "SOURCE.txt").write_text(
        f"Pikafish {tag} (GPL-3.0, see Copying.txt; NNUE network: NNUE-License.md)\n"
        f"Binary: {binary} from {url}\n"
        f"Release: {html_url}\n"
        f"Source code: https://github.com/{REPO}/tree/{tag}\n"
        f"Source archive: https://github.com/{REPO}/archive/refs/tags/{tag}.tar.gz\n",
        encoding="utf-8",
    )
    print(f"installed {binary} -> {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
