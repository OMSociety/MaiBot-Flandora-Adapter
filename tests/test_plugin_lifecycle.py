"""插件生命周期的行为测试。

覆盖宿主真正会调的那几个入口：on_load、on_config_update、on_unload 与网关 handler。
构造出实例、能注册组件，并不代表这些入口可用——`on_load` 里访问过一个不存在的
`self.logger`，宿主侧表现是「插件初始化失败 / 启动失败」，而构造与 get_components()
一路正常，所以必须有这一层。

本模块不使用 pytest fixture，方便在麦麦的 venv 里直接跑（那里没有 pytest）。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import types
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - 麦麦的 venv 里没有 pytest
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from maibot_sdk import PluginContext, PluginPaths
except ModuleNotFoundError as exc:  # pragma: no cover - 系统 Python 没有宿主 SDK
    if pytest is not None:
        pytest.skip(f"生命周期测试需要宿主的插件 SDK：{exc}", allow_module_level=True)
    raise

_ROOT = Path(__file__).resolve().parent.parent


def _load(module: str):
    """按合成包导入插件模块（仓库目录名带连字符，不能直接当包名）。"""

    package_name = "flandora_adapter"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(_ROOT)]
        sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.{module}")


plugin_mod = _load("plugin")


class _StubDebugLogger:
    def __init__(self) -> None:
        self.enabled_values: list[bool] = []

    def set_enabled(self, enabled: bool) -> None:
        self.enabled_values.append(enabled)


class _StubRouter:
    def __init__(self) -> None:
        self.settings_updates: list[object] = []

    def update_settings(self, settings: object) -> None:
        self.settings_updates.append(settings)


class _StubRuntimeState:
    def __init__(self) -> None:
        self.account_id = "10086"
        self.ready = False
        self.disconnect_reasons: list[str] = []


class _StubActionService:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {"status": "ok", "retcode": 0, "data": {}}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, action: str, params: dict | None = None, *, timeout=None):
        self.calls.append((action, params or {}))
        return self.response


class _StubTransport:
    def __init__(self) -> None:
        self.settings_updates: list[object] = []

    def update_settings(self, settings: object) -> None:
        self.settings_updates.append(settings)


class _StubTransport:
    """顶替连接层，记录热更新时下发的配置。"""

    def __init__(self) -> None:
        self.applied = []

    def update_settings(self, client_settings) -> None:
        self.applied.append(client_settings)


class StubRuntime:
    """顶替 build_runtime 的产物，记录生命周期调用。"""

    def __init__(self, *, settings, gateway, logger, response=None) -> None:
        self.settings = settings
        self.gateway = gateway
        self.logger = logger
        self.started = False
        self.stopped = False
        self.connected = True
        self.debug_logger = _StubDebugLogger()
        self.router = _StubRouter()
        self.runtime_state = _StubRuntimeState()
        self.action_service = _StubActionService(response)
        self.transport = _StubTransport()

    def start(self) -> None:
        self.started = True

    async def stop(self, *, silent: bool = False) -> None:
        self.stopped = True
        self.stop_silent = silent


def _make_plugin(tmp_dir: Path):
    """装出一个注入了上下文、且 build_runtime 被顶替的插件实例。"""

    plugin = plugin_mod.create_plugin()
    context = PluginContext(
        plugin_id="omsociety.flandora-adapter",
        rpc_call=None,
        paths=PluginPaths(
            data_dir=tmp_dir / "data",
            runtime_dir=tmp_dir / "runtime",
        ),
    )
    plugin._set_context(context)
    return plugin, context


def _patch_build_runtime(response: dict | None = None):
    original = plugin_mod.build_runtime

    def _fake(**kwargs):
        return StubRuntime(**kwargs, response=response)

    plugin_mod.build_runtime = _fake
    return original


def test_on_load_starts_runtime_with_host_context():
    """on_load 必须能读到日志器与宿主上下文，并按默认配置启起运行时。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        tmp_dir = Path(raw_dir)
        plugin, context = _make_plugin(tmp_dir)
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
        finally:
            plugin_mod.build_runtime = original

        runtime = plugin._runtime
        assert runtime is not None, "on_load 之后应当已有运行时"
        assert runtime.started is True
        assert runtime.logger is context.logger, "运行时应拿到宿主的插件日志器"
        assert runtime.gateway is context.gateway
        assert runtime.settings.client.attachment_max_bytes == 20 * 1024 * 1024

        asyncio.run(plugin.on_unload())
        assert runtime.stopped is True
        assert plugin._runtime is None


def test_on_load_is_idempotent():
    """重复 on_load 不应建出第二个运行时。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            first = plugin._runtime
            asyncio.run(plugin.on_load())
        finally:
            plugin_mod.build_runtime = original

        assert plugin._runtime is first


def test_config_update_hot_swaps_without_reconnect():
    """连接参数不变时只换配置快照，不重建运行时。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            runtime = plugin._runtime
            assert runtime is not None

            defaults = plugin.build_default_config()
            asyncio.run(plugin.on_config_update("self", defaults, "1.0.0"))
        finally:
            plugin_mod.build_runtime = original

        assert plugin._runtime is runtime, "连接参数没变就不应重建运行时"
        assert runtime.router.settings_updates, "新配置应灌进路由器"
        assert runtime.debug_logger.enabled_values == [False]

        asyncio.run(plugin.on_unload())


def test_config_update_ignores_foreign_scope():
    """scope 不是 self 时不动连接。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            runtime = plugin._runtime
            asyncio.run(plugin.on_config_update("bot", plugin.build_default_config(), "1.0.0"))
        finally:
            plugin_mod.build_runtime = original

        assert plugin._runtime is runtime
        assert runtime.router.settings_updates == []

        asyncio.run(plugin.on_unload())


def test_disabled_config_does_not_connect():
    """配置里关掉插件时不建连接。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            defaults = plugin.build_default_config()
            defaults["plugin"]["enabled"] = False
            plugin.set_plugin_config(defaults)
            asyncio.run(plugin.on_load())
        finally:
            plugin_mod.build_runtime = original

        assert plugin._runtime is None


def test_gateway_handler_without_connection_reports_failure():
    """连接没起来时 handler 要如实回报失败，而不是抛异常。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        message = {
            "message_id": "1",
            "platform": "wechat",
            "message_info": {
                "user_info": {"user_id": "10086", "user_nickname": "bot"},
                "group_info": {"group_id": "88", "group_name": "群"},
            },
            "raw_message": [{"type": "text", "data": "你好"}],
        }
        result = asyncio.run(plugin.handle_flandora_gateway(message, route={}, metadata=None))

        assert result["success"] is False
        assert "尚未连接 Flandora" in result["error"]


def test_gateway_handler_sends_and_echoes_message_id():
    """连通后 handler 应当发出动作并回填消息号。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime(
            {"status": "ok", "retcode": 0, "data": {"message_id": 998877}}
        )
        try:
            asyncio.run(plugin.on_load())
            runtime = plugin._runtime
            assert runtime is not None

            message = {
                "message_id": "1",
                "platform": "wechat",
                "message_info": {
                    "user_info": {"user_id": "10086", "user_nickname": "bot"},
                    "group_info": {"group_id": "88", "group_name": "群"},
                },
                "raw_message": [{"type": "text", "data": "你好"}],
            }
            result = asyncio.run(plugin.handle_flandora_gateway(message, route={}, metadata=None))
        finally:
            plugin_mod.build_runtime = original

        assert result["success"] is True
        assert result["external_message_id"] == "998877"
        assert runtime.action_service.calls == [
            (
                "send_group_msg",
                {"group_id": 88, "message": [{"type": "text", "data": {"text": "你好"}}]},
            )
        ]
        callbacks = result["metadata"]["adapter_callbacks"]
        assert callbacks[0]["name"] == "message_id_echo"
        assert callbacks[0]["payload"]["content"] == {
            "type": "echo",
            "echo": "1",
            "actual_id": "998877",
        }

        asyncio.run(plugin.on_unload())


def test_gateway_handler_reports_flandora_rejection():
    """Flandora 明确拒绝时按失败回报，并带上 retcode。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime(
            {"status": "failed", "retcode": 1406, "data": {}, "message": "未知的 group_id：88"}
        )
        try:
            asyncio.run(plugin.on_load())
            message = {
                "message_id": "1",
                "platform": "wechat",
                "message_info": {
                    "user_info": {"user_id": "10086", "user_nickname": "bot"},
                    "group_info": {"group_id": "88", "group_name": "群"},
                },
                "raw_message": [{"type": "text", "data": "你好"}],
            }
            result = asyncio.run(plugin.handle_flandora_gateway(message, route={}, metadata=None))
        finally:
            plugin_mod.build_runtime = original

        assert result["success"] is False
        assert result["error"] == "未知的 group_id：88"
        assert result["metadata"]["retcode"] == 1406

        asyncio.run(plugin.on_unload())


def test_plugin_has_no_undeclared_logger_attribute():
    """基类只提供 ctx.logger；插件不得依赖 self.logger。"""

    plugin_mod_plugin = plugin_mod.FlandoraAdapterPlugin
    assert not hasattr(plugin_mod_plugin, "logger"), (
        "MaiBotPlugin 没有 logger 属性，日志一律走 self.ctx.logger"
    )


def test_config_widgets_are_declared():
    """配置页只声明连接状态与重连两个控件。"""

    plugin = plugin_mod.create_plugin()
    widgets = {widget.id: widget for widget in plugin.config_widgets}

    assert set(widgets) == {"connection", "reconnect"}
    assert widgets["connection"].kind == "status"
    assert widgets["reconnect"].kind == "action"


def test_widget_state_reports_connected_account():
    """连上后状态控件显示微信账号，重连按钮可用。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            states = asyncio.run(plugin.get_config_widget_state())
        finally:
            plugin_mod.build_runtime = original
            asyncio.run(plugin.on_unload())

        assert states["connection"].text == "已连接：微信 10086"
        assert states["connection"].tone == "success"
        assert states["reconnect"].disabled is False


def test_widget_state_reports_disconnected_plugin():
    """未连接时给出排查提示，按钮仍可按（配置启用）。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        states = asyncio.run(plugin.get_config_widget_state())

        assert "未连接" in states["connection"].text
        assert states["connection"].tone == "neutral"
        assert states["reconnect"].disabled is False


def test_widget_reconnect_disabled_when_plugin_off():
    """配置里关闭插件时重连按钮置灰。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        defaults = plugin.build_default_config()
        defaults["plugin"]["enabled"] = False
        plugin.set_plugin_config(defaults)

        states = asyncio.run(plugin.get_config_widget_state())

        assert states["reconnect"].disabled is True


def test_widget_action_reconnects_silently():
    """点击重连应当静默停掉旧连接并建出新运行时。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            first = plugin._runtime
            assert first is not None

            asyncio.run(plugin.on_config_widget_action("reconnect"))
        finally:
            plugin_mod.build_runtime = original

        assert first.stopped is True
        assert first.stop_silent is True
        assert plugin._runtime is not None
        assert plugin._runtime is not first

        asyncio.run(plugin.on_unload())


def test_unknown_widget_action_is_rejected():
    """未知 action 要抛出可读的 ValueError。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        try:
            asyncio.run(plugin.on_config_widget_action("remove"))
        except ValueError as exc:
            assert "未知配置页操作: remove" in str(exc)
        else:
            raise AssertionError("未知配置页操作应抛 ValueError")


def test_reload_unload_is_silent():
    """热重载卸载不把适配器上报成离线。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            runtime = plugin._runtime
            asyncio.run(plugin.on_unload(for_reload=True))
        finally:
            plugin_mod.build_runtime = original

        assert runtime is not None
        assert runtime.stopped is True
        assert runtime.stop_silent is True
        assert plugin._runtime is None


def test_normal_unload_reports_offline():
    """普通卸载仍走非静默停止。"""

    with tempfile.TemporaryDirectory() as raw_dir:
        plugin, _ = _make_plugin(Path(raw_dir))
        original = _patch_build_runtime()
        try:
            asyncio.run(plugin.on_load())
            runtime = plugin._runtime
            asyncio.run(plugin.on_unload())
        finally:
            plugin_mod.build_runtime = original

        assert runtime is not None
        assert runtime.stop_silent is False


def test_deferred_cleanup_removes_files_on_unload():
    """结果不明时挂起的清理任务在卸载时立即删掉文件。"""

    services = _load("services")
    with tempfile.TemporaryDirectory() as raw_dir:
        tmp_dir = Path(raw_dir)
        plugin, _ = _make_plugin(tmp_dir)
        staged_path = tmp_dir / "pending.bin"
        staged_path.write_bytes(b"pending")
        staged = services.StagedFile(path=staged_path, directory=tmp_dir)

        async def scenario() -> None:
            plugin._defer_staged_cleanup([staged])
            assert staged_path.exists()
            plugin._cancel_cleanup_tasks()
            await asyncio.sleep(0)

        asyncio.run(scenario())

        assert not staged_path.exists()


def test_gateway_handler_reports_file_failures_and_cleans_temp():
    """下载失败的文件段从消息里移除，原因进回执，临时文件随后删除。"""

    services = _load("services")
    with tempfile.TemporaryDirectory() as raw_dir:
        tmp_dir = Path(raw_dir)
        plugin, _ = _make_plugin(tmp_dir)
        original_runtime = _patch_build_runtime(
            {"status": "ok", "retcode": 0, "data": {"message_id": 1}}
        )
        original_stage = plugin_mod.stage_outbound_files
        staged_path = tmp_dir / "payload.bin"
        staged_path.write_bytes(b"payload")

        async def fake_stage(message, *, logger):
            del logger
            message["raw_message"] = [{"type": "text", "data": "你好"}]
            return services.StagedFiles(
                files=[services.StagedFile(path=staged_path, directory=tmp_dir)],
                failures=["file:报告.pdf 下载失败（HTTP 404）"],
            )

        plugin_mod.stage_outbound_files = fake_stage
        try:
            asyncio.run(plugin.on_load())
            message = {
                "message_id": "1",
                "platform": "wechat",
                "message_info": {
                    "user_info": {"user_id": "10086", "user_nickname": "bot"},
                    "group_info": {"group_id": "88", "group_name": "群"},
                },
                "raw_message": [{"type": "file", "data": {"url": "http://example/x"}}],
            }
            result = asyncio.run(plugin.handle_flandora_gateway(message, route={}, metadata=None))
        finally:
            plugin_mod.stage_outbound_files = original_stage
            plugin_mod.build_runtime = original_runtime

        assert result["success"] is True
        assert result["metadata"]["dropped_segments"] == ["file:报告.pdf 下载失败（HTTP 404）"]
        assert not staged_path.exists()

        asyncio.run(plugin.on_unload())
