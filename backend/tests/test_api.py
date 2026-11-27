from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.core.config import Settings
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "coach.db")))


def test_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__, "db": "ok"}
    assert (tmp_path / "coach.db").exists()


def test_cors_allows_only_tauri_origins(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        ok = client.get("/health", headers={"Origin": "http://tauri.localhost"})
        bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://tauri.localhost"
    assert "access-control-allow-origin" not in bad.headers


def test_untrusted_host_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "coach.db")), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_writes_require_client_header(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/sessions", json={}, headers={"X-XQC-Client": "0"}).status_code == 403
        del client.headers["X-XQC-Client"]
        assert client.post("/sessions", json={}).status_code == 403
        assert client.delete("/sessions/x/moves/last").status_code == 403
        assert client.get("/sessions").status_code == 200  # reads need no header
        pre = client.options(
            "/sessions",
            headers={"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type,x-xqc-client"},
        )  # fmt: skip
        assert pre.status_code == 200 and "x-xqc-client" in pre.headers["access-control-allow-headers"].lower()


def test_json_body_size_limit(tmp_path: Path) -> None:
    big = b'{"note": "' + b"x" * (2 * 1024 * 1024) + b'"}'
    with _client(tmp_path) as client:
        r = client.post("/sessions", content=big, headers={"Content-Type": "application/json"})
        assert r.status_code == 413

        def chunks():  # no Content-Length: counted while reading
            yield big[:1024]
            yield big[1024:]

        r = client.post("/sessions", content=chunks(), headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        assert client.post("/sessions", json={"note": "ok"}).status_code == 201
