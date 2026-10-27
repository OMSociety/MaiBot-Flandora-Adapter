"""动作服务：把对 Flandora 的动作调用收敛到一处。

本模块只负责“发出去、拿到响应、判断成败”，不含任何消息段翻译逻辑。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..transport import FlandoraTransport

_STATUS_OK = "ok"


def is_action_response_ok(response: Dict[str, Any]) -> bool:
    """判断动作响应是否表示成功。

    Flandora 在至少执行了部分段时返回 ``status=ok`` 且 ``retcode=0``；
    一段都没发出去时返回 ``status=failed``。
    """

    if not isinstance(response, dict):
        return False
    status = str(response.get("status") or "").strip().lower()
    try:
        retcode = int(response.get("retcode", 0))
    except (TypeError, ValueError):
        retcode = -1
    return status == _STATUS_OK and retcode == 0


def action_response_retcode(response: Any) -> int:
    """取出响应里的 retcode；取不到时返回 -1。"""

    if not isinstance(response, dict):
        return -1
    try:
        return int(response.get("retcode", -1))
    except (TypeError, ValueError):
        return -1


def action_response_error(response: Any) -> str:
    """从失败的响应里拼出可读的失败原因。"""

    if not isinstance(response, dict):
        return "Flandora 返回的响应缺少可识别的状态"

    for key in ("wording", "message", "msg", "error"):
        text = str(response.get(key) or "").strip()
        if text:
            return text

    retcode = action_response_retcode(response)
    if retcode >= 0:
        return f"Flandora 返回 retcode={retcode}"
    return "Flandora 未说明失败原因"


class FlandoraActionService:
    """对 Flandora 动作接口的轻封装。"""

    def __init__(self, transport: FlandoraTransport, logger: Any) -> None:
        """初始化动作服务。

        Args:
            transport: 连接层实例。
            logger: 插件日志对象。
        """

        self._transport = transport
        self._logger = logger

    @property
    def transport(self) -> FlandoraTransport:
        """返回底层连接层实例。"""

        return self._transport

    @property
    def connected(self) -> bool:
        """当前连接是否可用。"""

        return self._transport.connected

    async def call(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """调用一次动作并返回原始响应。"""

        return await self._transport.call_action(action, params, timeout=timeout)
