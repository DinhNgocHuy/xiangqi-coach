import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "x", "levelname": "INFO", "msg": "hello %s", "args": ("bạn",), "version": 1, "color_message": "c"}
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello bạn" and out["level"] == "INFO" and out["version"] == 1
    assert "color_message" not in out and "args" not in out
