import pytest
from asost.config import ASOSTConfig


def test_defaults_and_environment_parsing():
    config = ASOSTConfig.from_env({"ASOST_CREDENTIALS": "alpha, beta", "ASOST_MAX_ATTEMPTS": "2"})
    assert config.provider == "gemini"
    assert config.credentials == ("alpha", "beta")
    assert config.max_attempts == 2


def test_credentials_are_redacted_from_repr():
    config = ASOSTConfig(credentials=("super-secret-value",))
    assert "super-secret-value" not in repr(config)
    assert "redacted:1" in repr(config)


def test_invalid_attempt_count():
    with pytest.raises(ValueError):
        ASOSTConfig.from_env({"ASOST_MAX_ATTEMPTS": "0"})
