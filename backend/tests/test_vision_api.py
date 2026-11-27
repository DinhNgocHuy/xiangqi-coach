"""/vision endpoints with SYNTHETIC screenshots (tests/vision_synth.py). Raw PNG body contract."""

import struct
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from vision_synth import random_board, render, start_board

from app.core.config import Settings
from app.main import create_app

HEADERS = {"Content-Type": "image/png", "X-XQC-Client": "1"}  # what the frontend sends
TEN_MB = 10 * 1024 * 1024


def _png(image: np.ndarray) -> bytes:
    return cv2.imencode(".png", image)[1].tobytes()


def _post(client: TestClient, path: str, data, headers: dict | None = None):
    return client.post(path, content=data, headers=headers or HEADERS)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "coach.db")))


def test_board_before_calibration_is_409(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    with _client(tmp_path) as client:
        r = _post(client, "/vision/board", _png(render(start_board(), rng).image))
    assert r.status_code == 409
    assert r.json()["detail"] == 'Chưa hiệu chỉnh quân cờ. Hãy chụp bàn cờ ở thế ban đầu và bấm "Hiệu chỉnh" trước.'


def test_calibrate_then_read_board(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    board = random_board(rng, 25)
    with _client(tmp_path) as client:
        cal = _post(client, "/vision/calibrate", _png(render(start_board(), rng, board_width=600).image))
        assert cal.status_code == 200, cal.text
        assert cal.json()["orientation"] == "red_bottom"
        assert (tmp_path / "vision_theme.npz").exists()
        r = _post(client, "/vision/board", _png(render(board, rng, red_bottom=False).image))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["board"] == [list(row) for row in board]
    assert body["orientation"] == "red_top"
    assert body["fen_placement"] and body["side_to_move"] is None
    assert len(body["confidence"]) == 10 and len(body["confidence"][0]) == 9
    assert body["timing_ms"] > 0
    # theme survives a restart (loaded from the user data dir)
    with _client(tmp_path) as client:
        again = _post(client, "/vision/board", _png(render(board, rng).image))
    assert again.status_code == 200 and again.json()["fen_placement"] == body["fen_placement"]


def test_png_over_2mb_passes_the_app_guard(tmp_path: Path) -> None:
    """A real 1080p screenshot can be several MB: only the 10 MB vision limit applies to image/png."""
    rng = np.random.default_rng(4)
    s = render(start_board(), rng, board_width=600)
    noise = rng.integers(0, 256, (700, s.image.shape[1], 3), dtype=np.uint8)  # incompressible "video ad"
    data = _png(np.vstack([s.image, noise]))
    assert 2 * 1024 * 1024 < len(data) < TEN_MB
    with _client(tmp_path) as client:
        assert _post(client, "/vision/calibrate", data).status_code == 200
        r = _post(client, "/vision/board", data)
    assert r.status_code == 200, r.text
    assert r.json()["fen_placement"] == "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR"


def test_body_over_10mb_is_413_with_and_without_content_length(tmp_path: Path) -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * TEN_MB

    def chunked():  # generator body -> no Content-Length, Transfer-Encoding: chunked
        for i in range(0, len(big), 1 << 20):
            yield big[i : i + (1 << 20)]

    with _client(tmp_path) as client:
        declared = _post(client, "/vision/calibrate", big)
        streamed = _post(client, "/vision/calibrate", chunked())
    assert declared.status_code == 413 and declared.json()["detail"] == "Ảnh quá lớn (tối đa 10 MB)."
    assert streamed.status_code == 413 and streamed.json()["detail"] == "Ảnh quá lớn (tối đa 10 MB)."


def test_bad_inputs(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    with _client(tmp_path) as client:
        assert _post(client, "/vision/calibrate", _png(render(start_board(), rng).image)).status_code == 200
        no_board = _post(client, "/vision/board", _png(np.full((400, 600, 3), 200, np.uint8)))
        not_png = _post(client, "/vision/board", b"GIF89a not a png")
        broken = _post(client, "/vision/board", _png(np.zeros((50, 50, 3), np.uint8))[:40])
        header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
        huge_side = _post(client, "/vision/board", header + struct.pack(">II", 100_000, 100) + b"\x00" * 64)
        too_many_px = _post(client, "/vision/board", header + struct.pack(">II", 8000, 8000) + b"\x00" * 64)
        multipart = client.post("/vision/board", files={"image": ("f.png", b"x", "image/png")})
        not_start = _post(client, "/vision/calibrate", _png(render(random_board(rng, 30), rng).image))
    assert no_board.status_code == 422 and no_board.json()["detail"].startswith("Không tìm thấy bàn cờ")
    assert not_png.status_code == 422 and broken.status_code == 422
    assert huge_side.status_code == 422 and too_many_px.status_code == 422
    assert multipart.status_code == 415
    assert not_start.status_code == 422 and not_start.json()["detail"].startswith("Không hiệu chỉnh được")


def test_corrupt_theme_file_is_409_not_500(tmp_path: Path) -> None:
    rng = np.random.default_rng(6)
    (tmp_path / "vision_theme.npz").write_bytes(b"PK\x03\x04 definitely not a zip")
    with _client(tmp_path) as client:
        r = _post(client, "/vision/board", _png(render(start_board(), rng).image))
    assert r.status_code == 409
    assert r.json()["detail"] == "File hiệu chỉnh quân cờ bị hỏng. Hãy hiệu chỉnh lại."
