"""Vision pipeline on SYNTHETIC screenshots (tests/vision_synth.py). Not evidence of accuracy on real Ziga images."""

import time
from pathlib import Path

import numpy as np
import pytest
import vision_synth as synth
from vision_synth import _clutter, ghost_piece, random_board, render, start_board

from app.services.rules.xiangqi import START_FEN, apply_move, parse_fen
from app.services.vision.calibrate import CalibrationError, calibrate, load_theme, save_theme
from app.services.vision.locate import BoardNotFoundError, locate_board
from app.services.vision.pipeline import CONFIDENCE_THRESHOLD, recognize

START_PLACEMENT = START_FEN.split()[0]


@pytest.fixture(scope="module")
def theme():
    rng = np.random.default_rng(100)
    t, _, orientation = calibrate(render(start_board(), rng, board_width=650).image)
    assert orientation == "red_bottom"
    return t


def test_grid_within_quarter_cell() -> None:
    rng = np.random.default_rng(1)
    worst = 0.0
    for n in range(12):
        board = start_board() if n % 4 == 0 else random_board(rng, int(rng.integers(5, 60)))
        s = render(board, rng, red_bottom=bool(n % 2))
        err = np.abs(locate_board(s.image).points() - s.points).max() / s.cell
        worst = max(worst, err)
    print(f"grid: worst intersection error {worst:.3f} cell")
    assert worst <= 0.25


@pytest.mark.parametrize("red_bottom", [True, False])
def test_calibration_from_start_position(red_bottom: bool, tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    s = render(start_board(), rng, red_bottom=red_bottom, board_width=500)
    t, _, orientation = calibrate(s.image)
    assert orientation == ("red_bottom" if red_bottom else "red_top")
    save_theme(t, tmp_path / "theme.npz")
    loaded = load_theme(tmp_path / "theme.npz")
    assert loaded is not None and np.array_equal(loaded.templates, t.templates)
    # recognising at another scale with the stored theme
    r = recognize(render(start_board(), rng, red_bottom=red_bottom, board_width=850).image, loaded)
    assert r.fen_placement == START_PLACEMENT and r.low_confidence == []


def test_calibration_rejects_other_positions() -> None:
    rng = np.random.default_rng(3)
    with pytest.raises(CalibrationError):
        calibrate(render(random_board(rng, 30), rng).image)


@pytest.mark.parametrize(
    "fen",
    [
        START_FEN.replace("RNBAKABNR", "1NBAKABNR"),  # start minus the a0 rook
        apply_move(START_FEN, "h2e2"),  # one move from the start (central cannon)
    ],
)
def test_calibration_rejects_near_start_positions(fen: str) -> None:
    rng = np.random.default_rng(8)
    with pytest.raises(CalibrationError):
        calibrate(render(parse_fen(fen).board, rng, board_width=600).image)


def test_load_theme_rejects_corrupt_files(tmp_path: Path) -> None:
    path = tmp_path / "theme.npz"
    for content in (b"", b"PK\x03\x04garbage", b"not a zip at all"):
        path.write_bytes(content)
        with pytest.raises(ValueError):
            load_theme(path)
    np.savez(path, version=2, templates=np.zeros((3, 5, 5)), scalars=np.zeros(6))
    with pytest.raises(ValueError):
        load_theme(path)


def test_load_theme_missing_file(tmp_path: Path) -> None:
    assert load_theme(tmp_path / "none.npz") is None


def test_recognition_accuracy_on_random_positions(theme) -> None:
    rng = np.random.default_rng(2024)
    n_positions, squares, wrong, unflagged, full, times = 32, 0, 0, [], 0, []
    for n in range(n_positions):
        board = random_board(rng, int(rng.integers(4, 80)))
        s = render(board, rng, red_bottom=bool(rng.random() < 0.5))
        r = recognize(s.image, theme)
        times.append(r.timing_ms)
        assert r.orientation == ("red_bottom" if s.red_bottom else "red_top")
        ok = True
        for rank in range(10):
            for file in range(9):
                squares += 1
                if r.board[rank][file] != board[rank][file]:
                    wrong += 1
                    ok = False
                    if r.confidence[rank][file] >= CONFIDENCE_THRESHOLD:
                        unflagged.append((n, rank, file))
        full += ok and r.fen_placement is not None
    accuracy = 1 - wrong / squares
    print(
        f"recognition: {squares} squares, {wrong} wrong ({accuracy:.4%}), {full}/{n_positions} positions "
        f"fully read; timing median {np.median(times):.0f} ms, max {max(times):.0f} ms"
    )
    assert accuracy >= 0.995
    assert unflagged == []  # every wrong square must be reported as uncertain
    assert full / n_positions >= 0.95


def test_piece_mid_animation_is_flagged_not_guessed(theme) -> None:
    rng = np.random.default_rng(77)
    wrong = 0
    for _ in range(12):
        board = random_board(rng, int(rng.integers(4, 60)))
        s = render(board, rng, red_bottom=bool(rng.random() < 0.5))
        r = recognize(ghost_piece(s, rng)[0], theme)
        bad = [(rk, f) for rk in range(10) for f in range(9) if r.board[rk][f] != board[rk][f]]
        wrong += len(bad)
        assert all(r.confidence[rk][f] < CONFIDENCE_THRESHOLD for rk, f in bad)
        if bad:
            assert r.fen_placement is None
    print(f"mid-animation: {wrong} wrong squares over 12 frames, all flagged")


# Hand-written, asymmetric: red rook a0 + red king e0, black king d9. Independent of orient.to_board.
ASYMMETRIC = "3k5/9/9/9/9/9/9/9/9/R3K4"


def _is_red(image: np.ndarray, xy: np.ndarray, cell: float) -> bool:
    x, y, r = int(xy[0]), int(xy[1]), int(0.25 * cell)
    b, g, red = image[y - r : y + r, x - r : x + r].reshape(-1, 3).astype(int).T
    return int(((red > 150) & (red - g > 80) & (red - b > 80)).sum()) > 10


@pytest.mark.parametrize("red_bottom", [True, False])
def test_absolute_file_mapping(theme, red_bottom: bool) -> None:
    rng = np.random.default_rng(21)
    s = render(parse_fen(ASYMMETRIC + " w - - 0 1").board, rng, red_bottom=red_bottom, noise=False)
    # the renderer itself: Red at the bottom means a0 is the bottom-LEFT point; flipped, it is the top-RIGHT one
    rook_point = s.points[9, 0] if red_bottom else s.points[0, 8]
    assert _is_red(s.image, rook_point, s.cell)
    r = recognize(s.image, theme)
    assert r.orientation == ("red_bottom" if red_bottom else "red_top")
    assert r.fen_placement == ASYMMETRIC
    assert r.board[0][0] == "R" and r.board[0][4] == "K" and r.board[9][3] == "k"


def _assert_never_silently_wrong(r, board) -> int:
    bad = [(rk, f) for rk in range(10) for f in range(9) if r.board[rk][f] != board[rk][f]]
    assert all(r.confidence[rk][f] < CONFIDENCE_THRESHOLD for rk, f in bad), bad
    if bad:
        assert r.fen_placement is None
    return len(bad)


def test_occluded_points_are_uncertain_not_empty(theme) -> None:
    rng = np.random.default_rng(31)
    for _ in range(6):
        board = random_board(rng, int(rng.integers(4, 60)))
        s = render(board, rng, red_bottom=bool(rng.random() < 0.5))
        image, covered = synth.occlude(s, rng)
        r = recognize(image, theme)
        _assert_never_silently_wrong(r, board)
        assert r.fen_placement is None
        conf = np.array(r.confidence)  # [rank][file] -> back to image [row][col]
        conf_image = conf[::-1] if s.red_bottom else conf[:, ::-1]
        assert (conf_image[covered] < CONFIDENCE_THRESHOLD).all()


@pytest.mark.parametrize("cut", ["top", "bottom", "left", "right"])
def test_board_cut_by_image_edge_never_gives_fen(theme, cut: str) -> None:
    rng = np.random.default_rng(41)
    board = random_board(rng, 30)
    s = render(board, rng, red_bottom=True)
    p, c = s.points, s.cell
    image = {
        "top": s.image[int(p[0, 0, 1] + 0.2 * c) :],
        "bottom": s.image[: int(p[9, 0, 1] - 0.2 * c)],
        "left": s.image[:, int(p[0, 0, 0] + 0.2 * c) :],
        "right": s.image[:, : int(p[0, 8, 0] + 0.3 * c)],
    }[cut]
    try:
        r = recognize(image, theme)
    except BoardNotFoundError:
        return  # rejected is fine
    _assert_never_silently_wrong(r, board)
    assert r.fen_placement is None
    assert "board is cut off by the image edge" in r.problems


def test_tint_over_piece_and_disc_markers_are_never_misread(theme) -> None:
    rng = np.random.default_rng(51)
    for make in (
        lambda s: synth.tint_over_piece(s, rng)[0],
        lambda s: synth.disc_marker(s, rng, filled=False)[0],
        lambda s: synth.disc_marker(s, rng, filled=True)[0],
    ):
        for _ in range(5):
            board = random_board(rng, int(rng.integers(4, 60)))
            s = render(board, rng, red_bottom=bool(rng.random() < 0.5))
            _assert_never_silently_wrong(recognize(make(s), theme), board)


def test_orientation_flip(theme) -> None:
    rng = np.random.default_rng(11)
    board = random_board(rng, 20)
    a = recognize(render(board, rng, red_bottom=True).image, theme)
    b = recognize(render(board, rng, red_bottom=False).image, theme)
    assert (a.orientation, b.orientation) == ("red_bottom", "red_top")
    assert a.board == b.board == [list(row) for row in board]


def test_impossible_position_has_no_fen(theme) -> None:
    rng = np.random.default_rng(5)
    board = [list(row) for row in start_board()]
    board[4][4] = "R"  # third red rook
    r = recognize(render(tuple(map(tuple, board)), rng, red_bottom=True).image, theme)
    assert r.fen_placement is None
    assert "Red has 3 R (max 2)" in r.problems


def test_no_board_found() -> None:
    rng = np.random.default_rng(9)
    canvas = np.full((900, 1400, 3), 236, np.uint8)
    _clutter(canvas, rng, (0, 0, 0, 0))
    with pytest.raises(BoardNotFoundError):
        locate_board(canvas)
    with pytest.raises(BoardNotFoundError):
        locate_board(np.zeros((300, 300, 3), np.uint8))


def test_timing_per_frame(theme) -> None:
    rng = np.random.default_rng(13)
    times = []
    for _ in range(5):
        image = render(random_board(rng, 30), rng, board_width=900).image
        t0 = time.perf_counter()
        recognize(image, theme)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"timing (900 px boards, {image.shape[1]}x{image.shape[0]} frames): max {max(times):.0f} ms")
    assert max(times) < 300
