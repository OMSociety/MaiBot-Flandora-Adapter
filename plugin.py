"""MaiBot 侧的 Flandora 微信适配器插件入口。

本插件是 Flandora（OneBot v11 微信桥接器）与麦麦之间的双向消息网关：
出站把麦麦的消息翻成 OneBot 动作调用，入站把 Flandora 的事件翻成宿主 message_dict。
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from maibot_sdk import (
    ConfigWidget,
    ConfigWidgetState,
    MaiBotPlugin,
    MessageGateway,
    PluginConfigBase,
)

from .codecs import build_outbound_request
from .config import FlandoraPluginSettings
from .constants import (
    FLANDORA_GATEWAY_NAME,
    FLANDORA_PLATFORM,
    FLANDORA_PROTOCOL,
    FLANDORA_SCOPE,
    OUTBOUND_FILE_CLEANUP_DELAY_SEC,
)
from .runtime import FlandoraRuntime, build_runtime
from .services import (
    StagedFile,
    action_response_error,
    action_response_retcode,
    is_action_response_ok,
    remove_staged,
    stage_outbound_files,
)
from .transport import FlandoraActionError


class FlandoraAdapterPlugin(MaiBotPlugin):
    """Flandora 微信适配器。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = FlandoraPluginSettings

    # 配置页只放两个控件：一个看连接状态，一个手动重连；与 SnowLuma 适配器保持一致。
    config_widgets: ClassVar[List[ConfigWidget]] = [
        ConfigWidget(id="connection", kind="status", label="微信连接器状态"),
        ConfigWidget(id="reconnect", kind="action", label="重新连接"),
    ]

    def __init__(self) -> None:
        """初始化插件。"""

        super().__init__()
        self._runtime: Optional[FlandoraRuntime] = None
        self._connection_signature: Optional[Tuple[str, int, str]] = None
        self._lifecycle_lock = asyncio.Lock()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._deferred_files: set[StagedFile] = set()

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

    async def on_unload(self, for_reload: bool = False) -> None:
        """插件卸载：断开连接；热重载时静默断开，不把重载当掉线。

        Args:
            for_reload: 宿主 1.3.19 起在热重载时传 ``True``；普通卸载为 ``False``。
        """

        self._cancel_cleanup_tasks()
        await self._stop_runtime(silent=for_reload)

    async def get_config_widget_state(self) -> Dict[str, ConfigWidgetState]:
        """返回配置页控件的实时状态。"""

        runtime = self._runtime
        account_id = runtime.runtime_state.account_id if runtime is not None else ""
        connected = bool(runtime is not None and runtime.connected and account_id)
        text = (
            f"已连接：微信 {account_id}"
            if connected
            else "未连接，请检查连接配置，并确认 Flandora 客户端已启动"
        )
        return {
            "connection": ConfigWidgetState(
                text=text,
                tone="success" if connected else "neutral",
            ),
            "reconnect": ConfigWidgetState(disabled=not self._settings().should_connect()),
        }

    async def on_config_widget_action(self, action_id: str) -> None:
        """处理配置页按钮：目前只有「重新连接」。"""

        if action_id != "reconnect":
            raise ValueError(f"未知配置页操作: {action_id}")
        settings = self._settings()
        if not settings.should_connect():
            return
        await self._restart_runtime(settings, silent_stop=True)

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
        staged = await stage_outbound_files(message, logger=self.ctx.logger)

        try:
            request = build_outbound_request(
                message,
                logger=self.ctx.logger,
                route=route,
            )
        except ValueError as exc:
            remove_staged(staged.files)
            error = str(exc)
            if staged.failures:
                error = f"{error}；{'、'.join(staged.failures)}"
            return {"success": False, "error": error, "metadata": {"action": "", "retcode": -1}}

        request.dropped.extend(staged.failures)

        runtime = self._runtime
        if runtime is None or not runtime.connected:
            remove_staged(staged.files)
            return {
                "success": False,
                "error": "尚未连接 Flandora，消息未发送",
                "metadata": {"action": request.action, "retcode": -1},
            }

        try:
            response = await runtime.action_service.call(request.action, request.params)
        except FlandoraActionError as exc:
            # 超时或连接中断时 Flandora 可能仍在读文件，延后清理，避免删掉正在发送的附件。
            self._defer_staged_cleanup(staged.files)
            return {
                "success": False,
                "error": str(exc),
                "metadata": {"action": request.action, "retcode": exc.retcode},
            }
        except asyncio.CancelledError:
            remove_staged(staged.files)
            raise
        except Exception as exc:  # 连接层意外异常：如实回报，不吞掉
            self.ctx.logger.warning(f"发送消息时发生未预期的错误：{exc}")
            self._defer_staged_cleanup(staged.files)
            return {"success": False, "error": str(exc), "metadata": {"action": request.action}}

        remove_staged(staged.files)

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

    def _defer_staged_cleanup(self, files: List[StagedFile]) -> None:
        """发送结果不明时延后清理临时文件，给 Flandora 留出读文件的时间。"""

        if not files:
            return
        self._deferred_files.update(files)
        task = asyncio.create_task(self._cleanup_after_delay(files), name="flandora-file-cleanup")
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _cleanup_after_delay(self, files: List[StagedFile]) -> None:
        """等待清理延迟；任务被取消时同样会删除文件。"""

        try:
            await asyncio.sleep(OUTBOUND_FILE_CLEANUP_DELAY_SEC)
        finally:
            remove_staged(files)
            self._deferred_files.difference_update(files)

    def _cancel_cleanup_tasks(self) -> None:
        """取消所有待清理任务，并当场删掉尚未到点的文件。"""

        for task in list(self._cleanup_tasks):
            task.cancel()
        self._cleanup_tasks.clear()
        if self._deferred_files:
            remove_staged(list(self._deferred_files))
            self._deferred_files.clear()

    def _settings(self) -> FlandoraPluginSettings:
        """取当前配置；未注入时返回一份默认配置。"""

        try:
            config = self.config
        except RuntimeError:
            return FlandoraPluginSettings()
        return config if isinstance(config, FlandoraPluginSettings) else FlandoraPluginSettings()

    def _apply_settings(self, runtime: FlandoraRuntime, settings: FlandoraPluginSettings) -> None:
        """把新配置就地灌进运行中的运行时。"""

        runtime.settings = settings
        runtime.transport.update_settings(settings.client)
        runtime.debug_logger.set_enabled(settings.debug.log_raw_events)
        runtime.router.update_settings(settings)

    async def _start_runtime(self, settings: FlandoraPluginSettings) -> None:
        """建立连接并启动运行时。"""

        async with self._lifecycle_lock:
            await self._start_runtime_locked(settings)

    async def _start_runtime_locked(self, settings: FlandoraPluginSettings) -> None:
        """建立连接并启动运行时；调用方须已持有生命周期锁。"""

        if self._runtime is not None:
            return

        if not settings.validate_runtime_config(self.ctx.logger):
            self.ctx.logger.warning("适配器配置未通过启动校验，未建立连接")
            return

        runtime = build_runtime(
            settings=settings,
            gateway=self.ctx.gateway,
            logger=self.ctx.logger,
        )
        runtime.start()
        self._runtime = runtime
        self._connection_signature = settings.client.connection_signature()
        self.ctx.logger.info(
            f"已启动 Flandora 适配器：server={settings.client.server} "
            f"port={settings.client.port} scope={FLANDORA_SCOPE}"
        )

    async def _stop_runtime(self, *, silent: bool = False) -> None:
        """停掉运行时并清空状态。"""

        async with self._lifecycle_lock:
            await self._stop_runtime_locked(silent=silent)

    async def _stop_runtime_locked(self, *, silent: bool = False) -> None:
        """停掉运行时并清空状态；调用方须已持有生命周期锁。"""

        runtime = self._runtime
        self._runtime = None
        self._connection_signature = None
        if runtime is None:
            return
        await runtime.stop(silent=silent)
        if silent:
            self.ctx.logger.debug("Flandora 适配器已停止（热重载，不上报离线）")
        else:
            self.ctx.logger.info("Flandora 适配器已停止")

    async def _restart_runtime(
        self, settings: FlandoraPluginSettings, *, silent_stop: bool = False
    ) -> None:
        """按新配置重建运行时，停与起在同一把锁内完成。"""

        async with self._lifecycle_lock:
            await self._stop_runtime_locked(silent=silent_stop)
            await self._start_runtime_locked(settings)


def create_plugin() -> MaiBotPlugin:
    """插件工厂函数：宿主据此创建插件实例。"""

    return FlandoraAdapterPlugin()
