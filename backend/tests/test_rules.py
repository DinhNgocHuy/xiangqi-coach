import time

import pytest

from app.services.rules.xiangqi import (
    START_FEN,
    FenError,
    IllegalMoveError,
    Position,
    apply_move,
    board_to_fen,
    find_move_between,
    from_engine_move,
    game_status,
    is_in_check,
    is_legal,
    legal_moves,
    parse_fen,
    perft,
    to_engine_move,
    to_fen,
    validate_line,
    validate_position,
)

START_BLACK = START_FEN.replace(" w ", " b ")


def moves_from(fen: str, square: str) -> set[str]:
    return {m for m in legal_moves(fen) if m.startswith(square)}


def mutable_board(fen: str = START_FEN) -> list[list[str | None]]:
    return [list(row) for row in parse_fen(fen).board]


# ---------------------------------------------------------------- perft / coordinates


@pytest.mark.parametrize("depth, nodes", [(1, 44), (2, 1920)])
def test_perft_shallow(depth: int, nodes: int) -> None:
    assert perft(START_FEN, depth) == nodes


@pytest.mark.slow
def test_perft_3() -> None:
    t = time.perf_counter()
    assert perft(START_FEN, 3) == 79666
    assert time.perf_counter() - t < 30


def test_coordinate_conversion_round_trip() -> None:
    assert to_engine_move("a0a1") == "a1a2"
    assert to_engine_move("a9a8") == "a10a9"
    assert from_engine_move("a10a9") == "a9a8"
    assert from_engine_move("i1i10") == "i0i9"
    for f in "abcdefghi":
        for r in range(10):
            m = f"{f}{r}e{9 - r}"
            assert from_engine_move(to_engine_move(m)) == m
    with pytest.raises(IllegalMoveError):
        to_engine_move("a10a9")  # two-digit ranks only exist on the pyffish side


def test_rank_9_moves_for_black() -> None:
    assert moves_from(START_BLACK, "a9") == {"a9a8", "a9a7"}
    assert apply_move(START_BLACK, "a9a8").startswith("1nbakabnr/r8/")


# ---------------------------------------------------------------- FEN


def test_fen_round_trip_and_aliases() -> None:
    assert to_fen(parse_fen(START_FEN)) == START_FEN
    alias = "rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR w - - 0 1"
    assert to_fen(parse_fen(alias)) == START_FEN
    pos = parse_fen(START_FEN)
    assert pos.board[0][4] == "K" and pos.board[9][4] == "k" and pos.board[2][1] == "C"
    assert board_to_fen(pos.board, "b") == START_BLACK


@pytest.mark.parametrize(
    "fen",
    ["", "rnbakabnr/9 w", START_FEN.replace("RNBAKABNR", "RNBAKABN"), START_FEN.replace(" w ", " x "), "x" + START_FEN[1:]],
)
def test_malformed_fen(fen: str) -> None:
    with pytest.raises(FenError):
        parse_fen(fen)


def test_unplayable_fen_rejected() -> None:
    with pytest.raises(FenError):
        legal_moves("9/9/9/9/9/9/9/9/9/4K4 w - - 0 1")  # no black king
    with pytest.raises(FenError, match="kings face"):
        legal_moves("4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")
    with pytest.raises(FenError, match="not to move is in check"):
        legal_moves("4k4/9/9/9/9/9/9/9/4R4/3K5 w - - 0 1")


# ---------------------------------------------------------------- piece rules


def test_start_position_piece_moves() -> None:
    assert moves_from(START_FEN, "a0") == {"a0a1", "a0a2"}  # rook stops before own pawn
    assert moves_from(START_FEN, "b0") == {"b0a2", "b0c2"}  # b0-d1 leg (c0) blocked
    assert moves_from(START_FEN, "c0") == {"c0a2", "c0e2"}
    assert moves_from(START_FEN, "d0") == {"d0e1"}
    assert moves_from(START_FEN, "e0") == {"e0e1"}
    assert moves_from(START_FEN, "a3") == {"a3a4"}
    assert "b2b9" in moves_from(START_FEN, "b2")  # cannon captures horse over the b7 cannon
    assert "b2b7" not in moves_from(START_FEN, "b2")


def test_king_stays_in_palace() -> None:
    assert moves_from("5k3/9/9/9/9/9/9/9/9/3K5 w - - 0 1", "d0") == {"d0d1", "d0e0"}
    # e0 would face the black king on e9
    assert moves_from("4k4/9/9/9/9/9/9/9/9/3K5 w - - 0 1", "d0") == {"d0d1"}


def test_elephant_eye_and_river() -> None:
    assert moves_from("3k5/9/9/9/9/9/9/9/3N5/2B1K4 w - - 0 1", "c0") == {"c0a2"}  # eye d1 blocked
    assert moves_from("3k5/9/9/9/9/2B6/9/9/9/4K4 w - - 0 1", "c4") == {"c4a2", "c4e2"}  # cannot cross


def test_horse_leg() -> None:
    free = moves_from("4k4/9/9/9/9/4N4/9/9/9/3K5 w - - 0 1", "e4")
    assert free == {"e4d6", "e4f6", "e4c5", "e4g5", "e4c3", "e4g3", "e4d2", "e4f2"}
    blocked = moves_from("4k4/9/9/9/9/4N4/4P4/9/9/3K5 w - - 0 1", "e4")  # leg e3
    assert blocked == free - {"e4d2", "e4f2"}


def test_cannon_needs_screen_to_capture() -> None:
    fen = "3k5/9/4r4/9/4p4/9/9/9/4C4/5K3 w - - 0 1"
    file_moves = {m for m in moves_from(fen, "e1") if m[2] == "e"}
    assert file_moves == {"e1e0", "e1e2", "e1e3", "e1e4", "e1e7"}


def test_pawn_moves() -> None:
    assert moves_from("4k4/9/9/9/4P4/9/9/9/9/3K5 w - - 0 1", "e5") == {"e5e6", "e5d5", "e5f5"}
    assert moves_from("3k5/9/9/9/9/4p4/9/9/9/4K4 b - - 0 1", "e4") == {"e4e3", "e4d4", "e4f4"}
    assert moves_from("3k5/9/9/4p4/9/9/9/9/9/4K4 b - - 0 1", "e6") == {"e6e5"}


# ---------------------------------------------------------------- check / mate / flying general


def test_flying_general_forbids_facing_kings() -> None:
    assert moves_from("3k5/9/9/9/9/9/9/9/9/4K4 w - - 0 1", "e0") == {"e0e1", "e0f0"}
    assert not is_legal("3k5/9/9/9/9/9/9/9/9/4K4 w - - 0 1", "e0d0")


def test_check_evasion() -> None:
    fen = "4k4/9/9/9/9/9/9/9/4R4/3K5 b - - 0 1"
    assert is_in_check(fen)
    assert legal_moves(fen) == ["e9f9"]  # e8 still on the file, d9 faces the red king
    assert game_status(fen) is None


def test_checkmate_and_stalemate() -> None:
    assert game_status("3k5/9/9/9/9/9/9/9/9/2RRK4 b - - 0 1") == "checkmate"
    assert game_status("3k5/R8/R8/9/9/9/9/9/9/4K4 b - - 0 1") == "stalemate"
    assert not is_in_check("3k5/R8/R8/9/9/9/9/9/9/4K4 b - - 0 1")
    assert game_status(START_FEN) is None


def test_apply_move() -> None:
    after = apply_move(START_FEN, "h2e2")
    assert after == "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR b - - 1 1"
    with pytest.raises(IllegalMoveError):
        apply_move(START_FEN, "h2h7")  # cannon cannot capture without a screen
    with pytest.raises(IllegalMoveError):
        apply_move(START_FEN, "h7e7")  # black piece, red to move
    assert not is_legal(START_FEN, "nonsense")


# ---------------------------------------------------------------- validation


def test_start_position_is_valid() -> None:
    assert validate_position(parse_fen(START_FEN).board, "w") == []


def _problems_after(edits: dict[tuple[int, int], str | None], side: str | None = None) -> list[str]:
    board = mutable_board()
    for (file, rank), piece in edits.items():
        board[rank][file] = piece
    return validate_position(board, side)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "edits, expected",
    [
        ({(4, 4): "R"}, "Red has 3 R"),
        ({(4, 0): None}, "Red must have exactly one king"),
        ({(4, 0): None, (4, 4): "K"}, "king outside palace"),
        ({(3, 0): None, (3, 1): "A"}, "advisor not on a palace point"),
        ({(2, 0): None, (2, 6): "B"}, "elephant not on a legal elephant point"),
        ({(0, 3): None, (1, 3): "P"}, "pawn on an illegal square"),
        ({(0, 3): None, (0, 1): "P"}, "pawn behind its starting rank"),
        ({(0, 6): None, (1, 6): "p"}, "pawn on an illegal square"),
        ({(4, 3): None, (4, 6): None}, "kings face each other"),
    ],
)
def test_validation_problems(edits: dict[tuple[int, int], str | None], expected: str) -> None:
    problems = _problems_after(edits)
    assert any(expected in p for p in problems), problems


def test_side_not_to_move_in_check() -> None:
    fen = "4k4/9/9/9/9/9/9/9/4R4/3K5 b - - 0 1"  # black in check
    board = parse_fen(fen).board
    assert validate_position(board, "b") == []
    assert validate_position(board, "w") == ["side not to move is in check"]


def test_bad_board_shape() -> None:
    assert validate_position([[None] * 9] * 9) == ["board must be 10 ranks x 9 files"]
    assert validate_position([["X"] * 9] * 10) == ["invalid piece 'X'"]


# ---------------------------------------------------------------- move tracker helpers


def test_find_move_between() -> None:
    red_after = parse_fen(apply_move(START_FEN, "h2e2")).board
    assert find_move_between(START_FEN, red_after) == ["h2e2"]
    black_after = parse_fen(apply_move(START_BLACK, "h7e7")).board
    assert find_move_between(START_FEN, black_after) == ["h7e7"]  # side unknown: tries both
    assert find_move_between(START_FEN, black_after, side="w") == []
    assert find_move_between(START_FEN, parse_fen(START_FEN).board) == []
    two_moves = parse_fen(apply_move(apply_move(START_FEN, "h2e2"), "h7e7")).board
    assert find_move_between(START_FEN, two_moves) == []


def test_find_move_between_accepts_vision_matrix() -> None:
    after = [["." if sq is None else sq for sq in row] for row in parse_fen(apply_move(START_FEN, "b0c2")).board]
    after[0][2] = "E"  # alias from vision
    assert find_move_between(START_FEN, after) == ["b0c2"]


def test_validate_line() -> None:
    assert validate_line(START_FEN, ["h2e2", "h9g7", "h0g2"]) is None
    assert validate_line(START_FEN, ["h2e2", "h2e2"]) == 1
    assert validate_line(START_FEN, ["zz"]) == 0
    assert validate_line(START_FEN, []) is None


def test_position_is_frozen() -> None:
    pos = parse_fen(START_FEN)
    assert isinstance(pos, Position) and pos.side == "w"
    with pytest.raises(AttributeError):
        pos.side = "b"  # type: ignore[misc]
