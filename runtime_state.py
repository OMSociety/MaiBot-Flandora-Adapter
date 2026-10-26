"""运行状态与机器人账号上报。

宿主只有收到适配器上报的账号，才能判断“某条消息是不是机器人自己发的”，
@ 判定与回复概率也依赖这一条；因此连接建立后必须上报一次。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class FlandoraRuntimeState:
    """向宿主上报消息网关的就绪状态与机器人账号。"""

    def __init__(self, *, gateway_name: str, platform: str, logger: Any) -> None:
        """初始化运行状态上报器。

        Args:
            gateway_name: 消息网关名称。
            platform: 平台标识。
            logger: 插件日志对象。
        """

        self._gateway_name = gateway_name
        self._platform = platform
        self._logger = logger
        self._ready = False
        self._account_id = ""
        self._scope = ""

    @property
    def account_id(self) -> str:
        """最近一次上报的机器人账号。"""

        return self._account_id

    async def report_connected(
        self,
        gateway: Any,
        *,
        account_id: str,
        scope: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """上报连接已就绪。

        Args:
            gateway: SDK 的网关能力对象（``ctx.gateway``）。
            account_id: 机器人自身账号。
            scope: 连接作用域，用于区分多连接。
            metadata: 附加元数据。

        Returns:
            bool: 宿主是否接受本次上报。
        """

        normalized_account = str(account_id or "").strip()
        if not normalized_account:
            self._logger.warning("尚未取到 Flandora 的机器人账号，暂不上报运行状态")
            return False

        self._account_id = normalized_account
        self._scope = str(scope or "").strip()

        try:
            accepted = await gateway.update_state(
                gateway_name=self._gateway_name,
                ready=True,
                platform=self._platform,
                account_id=self._account_id,
                scope=self._scope,
                metadata=dict(metadata or {}),
            )
        except Exception as exc:
            self._logger.warning(f"上报消息网关状态失败：{exc}")
            return False

        if accepted:
            self._ready = True
            self._logger.info(
                f"消息网关已激活路由：platform={self._platform} "
                f"account_id={self._account_id} scope={self._scope}"
            )
        else:
            self._logger.warning("消息网关连接已建立，但宿主未接受运行时状态更新")
        return bool(accepted)

    async def report_disconnected(self, gateway: Any, *, reason: str = "") -> bool:
        """上报连接已断开。

        Args:
            gateway: SDK 的网关能力对象（``ctx.gateway``）。
            reason: 断开原因，仅用于日志。

        Returns:
            bool: 宿主是否接受本次上报。
        """

        had_state = self._ready or bool(self._account_id)
        self._ready = False
        if not had_state:
            return False

        try:
            accepted = await gateway.update_state(
                gateway_name=self._gateway_name,
                ready=False,
                platform=self._platform,
                account_id=self._account_id,
                scope=self._scope,
            )
        except Exception as exc:
            self._logger.warning(f"上报消息网关断开状态失败：{exc}")
            return False

        if reason:
            self._logger.info(f"消息网关已断开（{reason}）")
        return bool(accepted)
