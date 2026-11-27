import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture(autouse=True)
def _test_client_like_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    """TestClient talks to host "testserver" (allowed in tests only) and sends the client header like the frontend."""
    monkeypatch.setattr(main, "ALLOWED_HOSTS", [*main.ALLOWED_HOSTS, "testserver"])
    init = TestClient.__init__

    def with_header(self, *args, headers=None, **kwargs):  # type: ignore[no-untyped-def]
        init(self, *args, headers={main.CLIENT_HEADER: "1", **(headers or {})}, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", with_header)
