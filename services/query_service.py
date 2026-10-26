"""名册与信息查询服务。

把所有只读动作收在这里：连接建立时取机器人账号，后续需要平台资料时也走这里，
调用方不直接接触 WebSocket。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..transport import FlandoraActionError
from .action_service import (
    FlandoraActionService,
    action_response_error,
    action_response_retcode,
    is_action_response_ok,
)


def _as_dict(value: Any) -> Dict[str, Any]:
    """把任意值安全规整为字典。"""

    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    """把任意值安全规整为字典列表。"""

    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


class FlandoraQueryService:
    """Flandora 只读查询。"""

    def __init__(self, action_service: FlandoraActionService, logger: Any) -> None:
        """初始化查询服务。

        Args:
            action_service: 动作服务实例。
            logger: 插件日志对象。
        """

        self._action_service = action_service
        self._logger = logger

    async def _fetch(self, action: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """执行一次只读动作并原样返回 ``data`` 字段。

        Flandora 的 ``data`` 可能是对象也可能是数组（``get_group_list`` 就是数组），
        所以这里不做字典化，交由各调用方按自己的形状规整。

        Raises:
            FlandoraActionError: 动作响应表示失败时。
        """

        response = await self._action_service.call(action, params)
        if not is_action_response_ok(response):
            raise FlandoraActionError(
                action,
                action_response_error(response),
                retcode=action_response_retcode(response),
            )
        return response.get("data")

    async def get_login_info(self) -> Dict[str, Any]:
        """取机器人自身的账号与昵称。"""

        return _as_dict(await self._fetch("get_login_info"))

    async def get_status(self) -> Dict[str, Any]:
        """取 Flandora 的运行状态（微信是否在线、收发通道是否就绪）。"""

        return _as_dict(await self._fetch("get_status"))

    async def list_groups(self) -> List[Dict[str, Any]]:
        """取群列表。"""

        return _as_dict_list(await self._fetch("get_group_list"))

    async def list_friends(self) -> List[Dict[str, Any]]:
        """取好友列表。"""

        return _as_dict_list(await self._fetch("get_friend_list"))

    async def list_group_members(self, group_id: Any) -> List[Dict[str, Any]]:
        """取群成员列表。"""

        return _as_dict_list(await self._fetch("get_group_member_list", {"group_id": group_id}))

    async def get_group_info(self, group_id: Any) -> Dict[str, Any]:
        """取单个群资料。"""

        return _as_dict(await self._fetch("get_group_info", {"group_id": group_id}))

    async def get_group_member_info(self, group_id: Any, user_id: Any) -> Dict[str, Any]:
        """取单个群成员资料。"""

        return _as_dict(
            await self._fetch("get_group_member_info", {"group_id": group_id, "user_id": user_id})
        )

    async def get_friend_info(self, user_id: Any) -> Dict[str, Any]:
        """取好友资料。"""

        return _as_dict(await self._fetch("get_friend_info", {"user_id": user_id}))

    async def get_stranger_info(self, user_id: Any) -> Dict[str, Any]:
        """取陌生人资料。"""

        return _as_dict(await self._fetch("get_stranger_info", {"user_id": user_id}))

    async def get_message(self, message_id: Any) -> Dict[str, Any]:
        """按消息号取原文。"""

        return _as_dict(await self._fetch("get_msg", {"message_id": message_id}))
