"""通知里的人名解析：查得到就用昵称，查不到回退数字 ID。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from conftest import load

config_mod = load("config")
router_mod = load("runtime.router")
transport_mod = load("transport")


class _Gateway:
    """记录上抛到宿主的 message_dict。"""

    def __init__(self) -> None:
        self.pushed: List[Dict[str, Any]] = []

    async def route_message(
        self,
        *,
        gateway_name: str,
        message: Dict[str, Any],
        external_message_id: str = "",
        dedupe_key: str = "",
    ) -> bool:
        self.pushed.append(message)
        return True


class _Debug:
    def raw_event(self, payload: Any) -> None:
        return


class _Query:
    """顶替查询服务：要么给昵称，要么抛给定的异常。"""

    def __init__(self, *, nickname: str = "", error: Optional[Exception] = None) -> None:
        self.nickname = nickname
        self.error = error
        self.calls: List[Tuple[Any, ...]] = []

    async def get_group_member_info(self, group_id: Any, user_id: Any) -> Dict[str, Any]:
        self.calls.append(("group", group_id, user_id))
        if self.error is not None:
            raise self.error
        return {"user_id": user_id, "nickname": self.nickname}

    async def get_stranger_info(self, user_id: Any) -> Dict[str, Any]:
        self.calls.append(("friend", user_id))
        if self.error is not None:
            raise self.error
        return {"user_id": user_id, "nickname": self.nickname}


def _router(query: Any, logger: Any) -> Any:
    return router_mod.FlandoraEventRouter(
        gateway=_Gateway(),
        gateway_name="flandora_gateway",
        platform="wechat",
        logger=logger,
        debug_logger=_Debug(),
        settings=config_mod.FlandoraPluginSettings(),
        query_service=query,
    )


def _recall_payload() -> Dict[str, Any]:
    return {
        "time": 1730000010,
        "self_id": "1001",
        "post_type": "notice",
        "notice_type": "group_recall",
        "group_id": 88,
        "user_id": 7,
        "operator_id": 7,
        "message_id": 0,
        "message_id_known": False,
    }


def test_recall_uses_nickname_when_lookup_succeeds(logger):
    query = _Query(nickname="张三")
    router = _router(query, logger)

    asyncio.run(router.handle_notice(_recall_payload()))

    assert router._gateway.pushed[0]["processed_plain_text"] == "[事件-群撤回] 张三 撤回了一条消息"
    assert query.calls == [("group", "88", "7")]


def test_recall_falls_back_to_id_when_lookup_fails(logger):
    query = _Query(
        error=transport_mod.FlandoraActionError("get_group_member_info", "找不到该成员", 1406)
    )
    router = _router(query, logger)

    asyncio.run(router.handle_notice(_recall_payload()))

    assert router._gateway.pushed[0]["processed_plain_text"] == "[事件-群撤回] 7 撤回了一条消息"


def test_poke_resolves_both_sides(logger):
    query = _Query(nickname="张三")
    router = _router(query, logger)

    asyncio.run(
        router.handle_notice(
            {
                "time": 1730000011,
                "self_id": "1001",
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "user_id": 7,
                "target_id": 8,
                "suffix": "的小肚子",
            }
        )
    )

    assert router._gateway.pushed[0]["processed_plain_text"] == "张三 拍了拍张三的小肚子"
    assert query.calls == [("friend", "7"), ("friend", "8")]


def test_router_without_query_service_keeps_numeric_ids(logger):
    router = router_mod.FlandoraEventRouter(
        gateway=_Gateway(),
        gateway_name="flandora_gateway",
        platform="wechat",
        logger=logger,
        debug_logger=_Debug(),
        settings=config_mod.FlandoraPluginSettings(),
    )

    asyncio.run(router.handle_notice(_recall_payload()))

    assert router._gateway.pushed[0]["processed_plain_text"] == "[事件-群撤回] 7 撤回了一条消息"
