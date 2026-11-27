import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("fetch_pikafish", Path(__file__).parents[1] / "scripts" / "fetch_pikafish.py")
assert _spec and _spec.loader
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)

# File names of the Pikafish-2026-09-06 release archive.
NAMES = [
    "Copying.txt", "pikafish.nnue", "Pikafish-Android-arm64-universal", "Pikafish-Linux-x86-64-universal",
    "Pikafish-MacOS-universal", "Pikafish-Windows-x86-64-universal.exe", "Wiki/Home.md",
]


def test_pick_binary() -> None:
    assert fetch.pick_binary(NAMES, "Windows", "AMD64") == "Pikafish-Windows-x86-64-universal.exe"
    assert fetch.pick_binary(NAMES, "Linux", "x86_64") == "Pikafish-Linux-x86-64-universal"
    assert fetch.pick_binary(NAMES, "Darwin", "arm64") == "Pikafish-MacOS-universal"
    with pytest.raises(SystemExit):
        fetch.pick_binary(NAMES, "Linux", "riscv64")
    with pytest.raises(SystemExit):
        fetch.pick_binary(["Copying.txt"], "Linux", "x86_64")


def test_pick_binary_rejects_unsafe_names() -> None:
    unsafe = ["..\\Pikafish-Windows-x86-64-universal.exe", "Pikafish-Windows-x86-64-universal..exe"]
    with pytest.raises(SystemExit):
        fetch.pick_binary(unsafe, "Windows", "AMD64")


def test_digest_required_and_archive_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert fetch.expected_sha256("sha256:" + "A" * 64) == "a" * 64
    for bad in (None, "", "md5:abc", "sha256:short"):
        with pytest.raises(SystemExit):
            fetch.expected_sha256(bad)
    assert len(fetch.PINNED_SHA256) == 64
    fake = tmp_path / "Pikafish.7z"
    fake.write_bytes(b"not the release")
    monkeypatch.setattr("sys.argv", ["fetch", "--archive", str(fake), "--dest", str(tmp_path / "out")])
    with pytest.raises(SystemExit, match="does not match the pinned"):
        fetch.main()
    assert not (tmp_path / "out").exists()
