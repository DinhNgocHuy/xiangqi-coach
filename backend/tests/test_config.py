from pathlib import Path

import pytest

from app.core.config import DEFAULT_PORT, Settings, default_db_path


def test_defaults() -> None:
    s = Settings.from_env({"HOME": "/x"})
    assert s.host == "127.0.0.1"
    assert s.port == DEFAULT_PORT
    assert s.log_level == "INFO"
    assert s.pikafish_path is None and s.llm_api_key is None
    assert s.llm_provider is None and s.hf_token is None and s.hf_model is None


def test_reads_prefixed_env() -> None:
    s = Settings.from_env(
        {
            "XQC_PORT": "9000",
            "XQC_DB_PATH": "/tmp/a.db",
            "XQC_PIKAFISH_PATH": "/opt/pikafish",
            "XQC_LLM_API_KEY": "sk-secret",
            "XQC_LLM_MODEL": "m",
            "XQC_LLM_PROVIDER": "HuggingFace",
            "XQC_HF_TOKEN": "hf_secret",
            "XQC_HF_MODEL": "Qwen/Qwen3-32B:cheapest",
            "XQC_LOG_LEVEL": "debug",
        }
    )
    assert (s.port, s.db_path, s.pikafish_path, s.llm_model, s.log_level) == (
        9000,
        Path("/tmp/a.db"),
        Path("/opt/pikafish"),
        "m",
        "DEBUG",
    )
    assert s.llm_api_key == "sk-secret"
    assert (s.llm_provider, s.hf_token, s.hf_model) == ("huggingface", "hf_secret", "Qwen/Qwen3-32B:cheapest")
    assert "sk-secret" not in repr(s) and "hf_secret" not in repr(s)


@pytest.mark.parametrize("env", [{"XQC_PORT": "abc"}, {"XQC_PORT": "70000"}, {"XQC_LOG_LEVEL": "loud"}, {"XQC_LLM_PROVIDER": "openai"}])
def test_rejects_bad_values(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Settings.from_env(env)


def test_default_db_path_per_platform() -> None:
    assert default_db_path({"APPDATA": r"C:\Users\u\AppData\Roaming"}, "win32").parts[-2:] == ("XiangqiCoach", "coach.db")
    assert default_db_path({"XDG_DATA_HOME": "/d"}, "linux") == Path("/d/xiangqi-coach/coach.db")
