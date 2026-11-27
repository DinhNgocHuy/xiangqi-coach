"""Board recognition endpoints.

Contract: POST with the raw PNG bytes as the body, `Content-Type: image/png` (no multipart), max 10 MB.
The body is read into memory with a hard cap (never spooled to disk) and the image is never stored.
"""

import logging
import struct
import time

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.schemas.board import BoardResult, CalibrateResult, GridOut
from app.services.vision.calibrate import CalibrationError, calibrate, load_theme, save_theme
from app.services.vision.classify import Theme
from app.services.vision.grid import CELL, Grid
from app.services.vision.locate import BoardNotFoundError
from app.services.vision.pipeline import recognize

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 8192  # px; a small PNG can decode to gigabytes, so dimensions are checked before decoding
MAX_PIXELS = 3840 * 2160 * 2  # two 4K screens side by side
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
THEME_FILE = "vision_theme.npz"  # next to the database, in the user data dir

NOT_FOUND = "Không tìm thấy bàn cờ trong ảnh. Hãy chụp cả bàn cờ, không bị che hay cắt mất."


TOO_BIG = "Ảnh quá lớn (tối đa 10 MB)."


async def _read_png(request: Request) -> bytes:
    """Request body with a hard cap, checked before and while reading."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "image/png":
        raise HTTPException(415, "Hãy gửi ảnh PNG với Content-Type: image/png.")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(400, "Content-Length không hợp lệ.") from None
    if declared > MAX_BYTES:
        raise HTTPException(413, TOO_BIG)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            raise HTTPException(413, TOO_BIG)
    return bytes(body)


def _decode(data: bytes) -> np.ndarray:
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise HTTPException(422, "Ảnh phải là file PNG hợp lệ.")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise HTTPException(422, f"Kích thước ảnh không hợp lệ (tối đa {MAX_SIDE}×{MAX_SIDE} px).")
    if width * height > MAX_PIXELS:
        raise HTTPException(422, "Ảnh có quá nhiều điểm ảnh (tối đa khoảng 2 màn hình 4K).")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(422, "Không đọc được ảnh PNG (file hỏng?).")
    return image


def _grid_out(grid: Grid) -> GridOut:
    x, y, w, h = grid.bbox()
    return GridOut(x=x, y=y, width=w, height=h, cell=round(grid.cell, 2))


def _theme_path(request: Request):
    return request.app.state.settings.db_path.parent / THEME_FILE


def _theme(request: Request) -> Theme:
    theme = getattr(request.app.state, "vision_theme", None)
    if theme is None:
        try:
            theme = load_theme(_theme_path(request))
        except ValueError as e:  # load_theme wraps every read/format problem in ValueError
            log.warning("vision theme unreadable", extra={"error": str(e)})
            raise HTTPException(409, "File hiệu chỉnh quân cờ bị hỏng. Hãy hiệu chỉnh lại.") from e
        if theme is None:
            raise HTTPException(
                409, "Chưa hiệu chỉnh quân cờ. Hãy chụp bàn cờ ở thế ban đầu và bấm \"Hiệu chỉnh\" trước."
            )
        request.app.state.vision_theme = theme
    return theme


def _calibrate(data: bytes, request: Request) -> CalibrateResult:
    img = _decode(data)
    try:
        theme, grid, orientation = calibrate(img)
    except BoardNotFoundError as e:
        raise HTTPException(422, NOT_FOUND) from e
    except CalibrationError as e:
        raise HTTPException(
            422, f"Không hiệu chỉnh được: ảnh phải là thế cờ ban đầu, đủ 32 quân, không có hiệu ứng che quân ({e})."
        ) from e
    try:
        save_theme(theme, _theme_path(request))
    except OSError as e:
        log.error("vision theme not saved", extra={"error": str(e)})
        raise HTTPException(500, "Không lưu được file hiệu chỉnh vào thư mục dữ liệu (hết dung lượng hoặc không có quyền ghi?).") from e
    request.app.state.vision_theme = theme
    return CalibrateResult(
        orientation=orientation,
        disc_radius_px=round(theme.radius * grid.cell / CELL, 2),
        grid=_grid_out(grid),
    )


@router.post("/calibrate")
async def calibrate_theme(request: Request) -> CalibrateResult:
    """Learn piece templates from a screenshot of the standard start position (raw PNG body)."""
    data = await _read_png(request)
    return await run_in_threadpool(_calibrate, data, request)


def _read_board(data: bytes, theme: Theme, t0: float) -> BoardResult:
    img = _decode(data)
    try:
        r = recognize(img, theme, t0)
    except BoardNotFoundError as e:
        raise HTTPException(422, NOT_FOUND) from e
    return BoardResult(
        board=r.board,
        confidence=r.confidence,
        orientation=r.orientation,
        fen_placement=r.fen_placement,
        low_confidence=r.low_confidence,
        problems=r.problems,
        grid=_grid_out(r.grid),
        timing_ms=r.timing_ms,
    )


@router.post("/board")
async def read_board(request: Request) -> BoardResult:
    """Recognise the position in a screenshot (raw PNG body). Uncertain squares are reported, never guessed.

    timing_ms covers decoding + recognition (not the upload itself).
    """
    theme = _theme(request)
    data = await _read_png(request)
    return await run_in_threadpool(_read_board, data, theme, time.perf_counter())
