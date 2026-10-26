"""运行时装配：把配置、连接层、服务与路由器拼成一个可启停的运行单元。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from ..config import FlandoraPluginSettings
from ..constants import FLANDORA_GATEWAY_NAME, FLANDORA_PLATFORM
from ..debug import FlandoraDebugLogger
from ..runtime_state import (
    FlandoraRuntimeState,
    load_cached_account_id,
    save_cached_account_id,
)
from ..services import FlandoraActionService, FlandoraQueryService
from ..transport import FlandoraActionError, FlandoraTransport
from .router import FlandoraEventRouter


@dataclass
class FlandoraRuntime:
    """一次配置快照下的完整运行时。"""

    settings: FlandoraPluginSettings
    gateway: Any
    logger: Any
    self_id_cache_path: Path
    debug_logger: FlandoraDebugLogger
    router: FlandoraEventRouter
    transport: FlandoraTransport
    action_service: FlandoraActionService
    query_service: FlandoraQueryService
    runtime_state: FlandoraRuntimeState

    def start(self) -> None:
        """启动后台连接。"""

        self.transport.start()

    async def stop(self) -> None:
        """停止后台连接并上报离线。"""

        await self.transport.stop()

    @property
    def connected(self) -> bool:
        """当前是否已连接 Flandora。"""

        return self.transport.connected

    async def handle_connected(self) -> None:
        """连接建立后取机器人账号并上报就绪。"""

        account_id = load_cached_account_id(self.self_id_cache_path)
        try:
            info = await self.query_service.get_login_info()
        except FlandoraActionError as exc:
            self.logger.warning(f"连接已建立但取机器人账号失败：{exc}")
            info = {}

        fetched = str(info.get("user_id") or "").strip()
        if fetched:
            account_id = fetched
            nickname = str(info.get("nickname") or "").strip()
            save_cached_account_id(self.self_id_cache_path, account_id, nickname)
        elif account_id:
            self.logger.info(f"沿用上次缓存的机器人账号：{account_id}")

        await self.runtime_state.report_connected(
            self.gateway,
            account_id=account_id,
            scope=self.settings.client.connection_id,
            metadata={
                "connection_id": self.settings.client.connection_id,
                "server": self.settings.client.server,
                "port": self.settings.client.port,
            },
        )

        await self._warn_if_flandora_degraded()

    async def _warn_if_flandora_degraded(self) -> None:
        """连接可用但 Flandora 侧没准备好时，给出能直接定位的提示。

        收件侧要不要口令文件由 Flandora 自己决定（缺钥时它会每 10 秒重试），桥接侧能做的
        只是如实提示并保持连接：发件方向通常是好的，收件方向要等它自己恢复。
        """

        try:
            status = await self.query_service.get_status()
        except FlandoraActionError as exc:
            self.logger.warning(f"连接已建立但读取 Flandora 状态失败：{exc}")
            return

        if not status.get("online"):
            self.logger.warning(
                "Flandora 报告桥接未就绪（online=false）：消息可能收发不畅，"
                "插件保持连接并等待其恢复"
            )
        if not status.get("receiver_ready"):
            self.logger.warning(
                "Flandora 的本地库收件源尚未就绪（receiver_ready=false）："
                "当前收不到微信消息，需要在 Flandora 控制台完成取钥后才会自动恢复"
            )

    async def handle_disconnected(self, reason: str = "") -> None:
        """连接断开后上报离线。"""

        await self.runtime_state.report_disconnected(self.gateway, reason=reason)


def build_runtime(
    *,
    settings: FlandoraPluginSettings,
    gateway: Any,
    logger: Any,
    self_id_cache_path: Path,
) -> FlandoraRuntime:
    """按一份配置快照装配运行时。

    Args:
        settings: 已通过校验的配置。
        gateway: SDK 网关能力对象（``ctx.gateway``）。
        logger: 插件日志对象。
        self_id_cache_path: 机器人账号缓存文件路径。

    Returns:
        FlandoraRuntime: 可直接 ``start()`` 的运行时。
    """

    debug_logger = FlandoraDebugLogger(logger, enabled=settings.debug.log_raw_events)
    runtime_state = FlandoraRuntimeState(
        gateway_name=FLANDORA_GATEWAY_NAME,
        platform=FLANDORA_PLATFORM,
        logger=logger,
    )
    router = FlandoraEventRouter(
        gateway=gateway,
        gateway_name=FLANDORA_GATEWAY_NAME,
        platform=FLANDORA_PLATFORM,
        logger=logger,
        debug_logger=debug_logger,
        settings=settings,
    )

    # transport 需要回调，而回调又要用到尚未构造出来的 runtime，用一个可变槽位晚绑定。
    slot: List[Optional[FlandoraRuntime]] = [None]

    async def _on_connected() -> None:
        current = slot[0]
        if current is not None:
            await current.handle_connected()

    async def _on_disconnected(reason: str = "") -> None:
        current = slot[0]
        if current is not None:
            await current.handle_disconnected(reason)

    transport = FlandoraTransport(
        settings=settings.client,
        logger=logger,
        on_event=router.handle_event,
        on_connected=_on_connected,
        on_disconnected=_on_disconnected,
    )
    action_service = FlandoraActionService(transport, logger)
    query_service = FlandoraQueryService(action_service, logger)

    runtime = FlandoraRuntime(
        settings=settings,
        gateway=gateway,
        logger=logger,
        self_id_cache_path=self_id_cache_path,
        debug_logger=debug_logger,
        router=router,
        transport=transport,
        action_service=action_service,
        query_service=query_service,
        runtime_state=runtime_state,
    )
    slot[0] = runtime
    return runtime
