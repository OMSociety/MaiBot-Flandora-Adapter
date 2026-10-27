"""配置模型测试。"""

from __future__ import annotations

import pytest
from conftest import load

pytest.importorskip("maibot_sdk")

config_mod = load("config")
constants = load("constants")


class _Recorder:
    """记录配置校验输出的日志替身。"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def test_client_defaults():
    client = config_mod.FlandoraClientConfig()

    assert client.server == "127.0.0.1"
    assert client.port == 7999
    assert client.token == ""
    assert client.heartbeat_interval_sec == 30.0
    assert client.action_timeout_sec == 15.0
    assert client.attachment_max_mb == 20
    assert client.attachment_max_bytes == 20 * constants.BYTES_PER_MB
    assert client.build_ws_uri() == "ws://127.0.0.1:7999/"


def test_server_strips_scheme_and_path():
    client = config_mod.FlandoraClientConfig(server="ws://10.0.0.5/onebot")

    assert client.server == "10.0.0.5"
    assert client.build_ws_uri() == "ws://10.0.0.5:7999/"


def test_server_with_matching_port_is_stripped():
    client = config_mod.FlandoraClientConfig(server="ws://127.0.0.1:7999")

    assert client.server == "127.0.0.1"


def test_server_with_conflicting_port_is_rejected():
    with pytest.raises(ValueError, match="不一致"):
        config_mod.FlandoraClientConfig(server="127.0.0.1:7999", port=8000)


def test_token_goes_into_query_string():
    client = config_mod.FlandoraClientConfig(token="a/b c")

    assert client.build_ws_uri() == "ws://127.0.0.1:7999/?access_token=a%2Fb%20c"


def test_delay_fields_fall_back_to_their_own_defaults():
    client = config_mod.FlandoraClientConfig(
        reconnect_delay_sec="bad",
        max_reconnect_delay_sec="abc",
        heartbeat_interval_sec=0,
        action_timeout_sec=-1,
    )

    assert client.reconnect_delay_sec == 5.0
    assert client.max_reconnect_delay_sec == 60.0
    assert client.heartbeat_interval_sec == 30.0
    assert client.action_timeout_sec == 15.0


def test_attachment_limit_falls_back_and_converts():
    fallback = config_mod.FlandoraClientConfig(attachment_max_mb=0)
    assert fallback.attachment_max_mb == 20

    explicit = config_mod.FlandoraClientConfig(attachment_max_mb=5)
    assert explicit.attachment_max_bytes == 5 * constants.BYTES_PER_MB


def test_connection_signature_tracks_connection_fields():
    client = config_mod.FlandoraClientConfig(server="10.0.0.5", port=8000, token="t")

    assert client.connection_signature() == ("10.0.0.5", 8000, "t")


def test_config_version_defaults_to_supported():
    options = config_mod.FlandoraPluginOptions()

    assert options.config_version == constants.SUPPORTED_CONFIG_VERSION
    assert options.should_connect() is True


def test_empty_config_version_is_rejected():
    with pytest.raises(ValueError, match="config_version"):
        config_mod.FlandoraPluginOptions(config_version="   ")


def test_settings_should_connect_follows_enabled():
    assert config_mod.FlandoraPluginSettings().should_connect() is True

    disabled = config_mod.FlandoraPluginSettings(plugin={"enabled": False})
    assert disabled.should_connect() is False


def test_validate_runtime_config_rejects_version_mismatch():
    settings = config_mod.FlandoraPluginSettings()
    settings.plugin.config_version = "0.9.0"
    recorder = _Recorder()

    assert settings.validate_runtime_config(recorder) is False
    assert "配置版本不兼容" in recorder.errors[0]


def test_validate_runtime_config_accepts_defaults():
    assert config_mod.FlandoraPluginSettings().validate_runtime_config(_Recorder()) is True
