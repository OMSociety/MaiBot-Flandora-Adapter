"""MaiBot 侧的 Flandora 微信适配器插件入口。

本插件是 Flandora（OneBot v11 微信桥接器）与麦麦之间的双向消息网关：
出站把麦麦的消息翻成 OneBot 动作调用，入站把 Flandora 的事件翻成宿主 message_dict。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from maibot_sdk import MaiBotPlugin, MessageGateway, PluginConfigBase

from .codecs import build_outbound_request
from .config import FlandoraPluginSettings
from .constants import (
    FLANDORA_GATEWAY_NAME,
    FLANDORA_PLATFORM,
    FLANDORA_PROTOCOL,
    PLUGIN_ID,
)
from .runtime import FlandoraRuntime, build_runtime
from .services import (
    action_response_error,
    action_response_retcode,
    is_action_response_ok,
)
from .transport import FlandoraActionError

_DEFAULT_SELF_ID_CACHE = Path("data") / "plugins" / PLUGIN_ID / "flandora_self_id.json"


class FlandoraAdapterPlugin(MaiBotPlugin):
    """Flandora 微信适配器。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = FlandoraPluginSettings

    def __init__(self) -> None:
        """初始化插件。"""

        super().__init__()
        self._runtime: Optional[FlandoraRuntime] = None
        self._connection_signature: Optional[Tuple[str, int, str, str]] = None
        self._lifecycle_lock = asyncio.Lock()

    def get_components(self) -> List[Dict[str, Any]]:
        """返回本插件注册的组件。"""

        return super().get_components()

    async def on_load(self) -> None:
        """插件加载：按配置决定是否连上 Flandora。"""

        settings = self._settings()
        if not settings.plugin.enabled:
            self.ctx.logger.info("适配器已在配置中禁用，不建立连接")
            return
        if not settings.should_connect():
            self.ctx.logger.warning("适配器缺少可用的服务端地址或端口，未建立连接")
            return
        await self._start_runtime(settings)

    async def on_unload(self) -> None:
        """插件卸载：断开连接并上报离线。"""

        await self._stop_runtime()

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置热更新：必要时重建连接，否则就地替换配置快照。"""

        del version
        if scope != "self":
            return

        self.set_plugin_config(config_data)
        settings = self._settings()

        if not settings.plugin.enabled or not settings.should_connect():
            self.ctx.logger.info("适配器已关闭或配置不完整，断开现有连接")
            await self._stop_runtime()
            return

        signature = settings.client.connection_signature()
        if self._runtime is None or signature != self._connection_signature:
            self.ctx.logger.info("连接参数已变化，重建与 Flandora 的连接")
            await self._restart_runtime(settings)
            return

        self._apply_settings(self._runtime, settings)
        self.ctx.logger.info("适配器配置已热更新")

    @MessageGateway(
        name=FLANDORA_GATEWAY_NAME,
        route_type="duplex",
        platform=FLANDORA_PLATFORM,
        protocol=FLANDORA_PROTOCOL,
        description="Flandora 微信桥接器双向消息网关",
    )
    async def handle_flandora_gateway(
        self,
        message: Dict[str, Any],
        route: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """把宿主下发的消息翻成 Flandora 动作调用。"""

        del metadata, kwargs

        internal_message_id = str(message.get("message_id") or "").strip()
        runtime = self._runtime

        try:
            request = build_outbound_request(
                message,
                logger=self.ctx.logger,
                route=route,
                self_id=self._current_account_id(),
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc), "metadata": {"action": "", "retcode": -1}}

        if runtime is None or not runtime.connected:
            return {
                "success": False,
                "error": "尚未连接 Flandora，消息未发送",
                "metadata": {"action": request.action, "retcode": -1},
            }

        try:
            response = await runtime.action_service.call(request.action, request.params)
        except FlandoraActionError as exc:
            return {
                "success": False,
                "error": str(exc),
                "metadata": {"action": request.action, "retcode": exc.retcode},
            }
        except Exception as exc:  # 连接层意外异常：如实回报，不吞掉
            self.ctx.logger.warning(f"发送消息时发生未预期的错误：{exc}")
            return {"success": False, "error": str(exc), "metadata": {"action": request.action}}

        if not is_action_response_ok(response):
            error = action_response_error(response)
            retcode = action_response_retcode(response)
            self.ctx.logger.warning(f"Flandora 拒绝发送：{error}（retcode={retcode}）")
            return {
                "success": False,
                "error": error,
                "metadata": {"action": request.action, "retcode": retcode},
            }

        data = response.get("data")
        data = data if isinstance(data, dict) else {}
        external_message_id = str(data.get("message_id") or "").strip()

        failed_segments = data.get("failed_segments") or 0
        failed_details = data.get("failed_details") or []
        if failed_segments:
            self.ctx.logger.warning(
                f"部分消息段未发出：{failed_segments} 段，原因：{failed_details}"
            )

        adapter_callbacks: List[Dict[str, Any]] = []
        if (
            internal_message_id
            and external_message_id
            and internal_message_id != external_message_id
        ):
            adapter_callbacks.append(
                {
                    "name": "message_id_echo",
                    "payload": {
                        "content": {
                            "type": "echo",
                            "echo": internal_message_id,
                            "actual_id": external_message_id,
                        }
                    },
                }
            )

        return {
            "success": True,
            "external_message_id": external_message_id or None,
            "metadata": {
                "action": request.action,
                "actions": [request.action],
                "dropped_segments": request.dropped,
                "failed_segments": failed_segments,
                "failed_details": failed_details,
                "adapter_callbacks": adapter_callbacks,
            },
        }

    def _settings(self) -> FlandoraPluginSettings:
        """取当前配置；未注入时返回一份默认配置。"""

        try:
            config = self.config
        except RuntimeError:
            return FlandoraPluginSettings()
        return config if isinstance(config, FlandoraPluginSettings) else FlandoraPluginSettings()

    def _self_id_cache_path(self) -> Path:
        """机器人账号缓存的落点。"""

        try:
            data_dir = self.ctx.paths.data_dir
        except RuntimeError:
            return _DEFAULT_SELF_ID_CACHE
        return Path(data_dir) / "flandora_self_id.json"

    def _current_account_id(self) -> str:
        """当前已知的机器人账号。"""

        runtime = self._runtime
        if runtime is None:
            return ""
        return str(runtime.runtime_state.account_id or "").strip()

    def _apply_settings(self, runtime: FlandoraRuntime, settings: FlandoraPluginSettings) -> None:
        """把新配置就地灌进运行中的运行时。"""

        runtime.settings = settings
        runtime.debug_logger.set_enabled(settings.debug.log_raw_events)
        runtime.router.update_settings(settings)

    async def _start_runtime(self, settings: FlandoraPluginSettings) -> None:
        """建立连接并启动运行时。"""

        async with self._lifecycle_lock:
            if self._runtime is not None:
                return

            if not settings.validate_runtime_config(self.ctx.logger):
                self.ctx.logger.warning("适配器配置未通过启动校验，未建立连接")
                return

            runtime = build_runtime(
                settings=settings,
                gateway=self.ctx.gateway,
                logger=self.ctx.logger,
                self_id_cache_path=self._self_id_cache_path(),
            )
            runtime.start()
            self._runtime = runtime
            self._connection_signature = settings.client.connection_signature()
            self.ctx.logger.info(
                f"已启动 Flandora 适配器：server={settings.client.server} "
                f"port={settings.client.port} scope={settings.client.connection_id}"
            )

    async def _stop_runtime(self) -> None:
        """停掉运行时并清空状态。"""

        async with self._lifecycle_lock:
            runtime = self._runtime
            self._runtime = None
            self._connection_signature = None
            if runtime is None:
                return
            await runtime.stop()
            self.ctx.logger.info("Flandora 适配器已停止")

    async def _restart_runtime(self, settings: FlandoraPluginSettings) -> None:
        """按新配置重建运行时。"""

        await self._stop_runtime()
        await self._start_runtime(settings)


def create_plugin() -> MaiBotPlugin:
    """插件工厂函数：宿主据此创建插件实例。"""

    return FlandoraAdapterPlugin()
