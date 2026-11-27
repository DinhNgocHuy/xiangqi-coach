"""Plain-language move facts: notation and immediate reasons (rules only, no engine)."""

from app.services.engine.explain import explain, notation, null_move_fen, reasons
from app.services.rules import xiangqi as rules

START = rules.START_FEN


def test_notation_red_and_black() -> None:
    assert notation(START, "h2e2") == "Pháo 2 bình 5"
    assert notation(START, "h0g2") == "Mã 2 tiến 3"
    assert notation(START, "a0a1") == "Xe 9 tiến 1"
    black = rules.apply_move(START, "h2e2")
    assert notation(black, "h9g7") == "Mã 8 tiến 7"
    assert notation(black, "b7e7") == "Pháo 2 bình 5"
    assert notation(black, "a9a8") == "Xe 1 tiến 1"


def test_notation_front_back_on_one_file() -> None:
    fen = "4k4/9/9/9/9/9/9/R8/9/R3K4 w - - 0 1"  # two red chariots on file a (red's 9)
    assert notation(fen, "a2a5") == "Xe trước tiến 3"
    assert notation(fen, "a0b0") == "Xe sau bình 8"


def test_reasons_capture_check_and_new_threat() -> None:
    fen = rules.apply_move(rules.apply_move(START, "h2e2"), "h9g7")
    assert reasons(fen, "e2e6") == ["ăn Tốt"]  # no screen in front of the king: no check
    assert reasons("3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1", "a0d0") == ["chiếu Tướng"]
    assert reasons("3k5/9/9/9/9/9/n8/9/9/4K3R w - - 0 1", "i0i3") == ["đe dọa ăn Mã (không được bảo vệ)"]
    assert reasons(START, "i0i1") == []


def test_explain_reports_intent_and_whether_it_was_handled() -> None:
    # Black to move; the red chariot on a4 wants to take the unprotected black horse on a5.
    fen = "3k5/9/9/9/n8/R8/9/9/9/4K4 b - - 0 1"
    assert null_move_fen(fen) is not None
    e = explain(fen, "a5b7", ["a5b7"], None, "a4a5")
    assert e.opponent_intent == "Xe 9 tiến 1"
    assert e.opponent_intent_reasons[0] == "ăn Mã"
    assert e.intent_handled is True  # the horse moved away
    stay = explain(fen, "d9d8", ["a5b7"], None, "a4a5")
    assert stay.intent_handled is False
    assert stay.best_move == "Mã 1 thoái 2" and stay.best_line == ["Mã 1 thoái 2"]
