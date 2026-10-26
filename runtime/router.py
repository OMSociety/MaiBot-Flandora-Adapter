"""入站事件路由：Flandora 事件 -> 宿主消息网关。

只管“把事件如实送进宿主”：不过滤 @、不拼上下文、不生成回复——那些是宿主与客户端的职责。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..codecs import build_message_dict, build_notice_dedupe_key, build_notice_message_dict
from ..config import FlandoraPluginSettings
from ..constants import (
    FLANDORA_SCOPE,
    POST_TYPE_MESSAGE,
    POST_TYPE_MESSAGE_SENT,
    POST_TYPE_META_EVENT,
    POST_TYPE_NOTICE,
)


class FlandoraEventRouter:
    """把 Flandora 推送的事件转成宿主可接受的 message_dict。"""

    def __init__(
        self,
        *,
        gateway: Any,
        gateway_name: str,
        platform: str,
        logger: Any,
        debug_logger: Any,
        settings: FlandoraPluginSettings,
    ) -> None:
        """初始化路由器。

        Args:
            gateway: SDK 网关能力对象（``ctx.gateway``）。
            gateway_name: 消息网关名称。
            platform: 平台标识。
            logger: 插件日志对象。
            debug_logger: 原始事件调试日志。
            settings: 当前配置快照。
        """

        self._gateway = gateway
        self._gateway_name = gateway_name
        self._platform = platform
        self._logger = logger
        self._debug = debug_logger
        self._settings = settings

    @property
    def scope(self) -> str:
        """上报给宿主的会话作用域。"""

        return FLANDORA_SCOPE

    def update_settings(self, settings: FlandoraPluginSettings) -> None:
        """替换配置快照（连接参数未变时就地热更新）。"""

        self._settings = settings

    async def handle_event(self, payload: Mapping[str, Any]) -> None:
        """按 ``post_type`` 分发一条事件。"""

        self._debug.raw_event(payload)

        post_type = str(payload.get("post_type") or "").strip().lower()
        if post_type == POST_TYPE_MESSAGE:
            await self.handle_message(payload)
            return
        if post_type == POST_TYPE_NOTICE:
            await self.handle_notice(payload)
            return
        if post_type == POST_TYPE_META_EVENT:
            self.handle_meta_event(payload)
            return
        if post_type == POST_TYPE_MESSAGE_SENT:
            # 自己发出的消息：Flandora 上报它是为了让客户端能把被引用的 message_id 回查原文，
            # 麦麦没有这个需求，重复上抛只会让机器人把自己的话当成新消息。
            self._logger.debug("忽略 message_sent 事件（机器人自己发出的消息不上抛）")
            return
        self._logger.debug(f"忽略未知的 post_type：{post_type or '<空>'}")

    async def handle_message(self, payload: Mapping[str, Any]) -> None:
        """处理普通消息事件。"""

        self_id = str(payload.get("self_id") or "").strip()
        sender = payload.get("sender")
        sender_user_id = str(
            payload.get("user_id") or (sender.get("user_id") if isinstance(sender, Mapping) else "")
        ).strip()
        if not sender_user_id:
            self._logger.debug("入站消息缺少 user_id，已丢弃")
            return

        filters = self._settings.filters
        if filters.is_user_banned(sender_user_id):
            self._logger.debug(f"发送者 {sender_user_id} 在过滤名单中，消息已丢弃")
            return

        group_id = str(payload.get("group_id") or "").strip()
        if group_id and filters.is_group_banned(group_id):
            self._logger.debug(f"群 {group_id} 在过滤名单中，消息已丢弃")
            return

        if self_id and sender_user_id == self_id and filters.ignore_self_message:
            self._logger.debug("自己发送的消息已按配置丢弃")
            return

        try:
            message_dict = build_message_dict(
                payload,
                self_id=self_id,
                attachment_max_bytes=self._settings.client.attachment_max_bytes,
                logger=self._logger,
            )
        except ValueError as exc:
            self._logger.warning(f"入站消息格式不受支持，已丢弃：{exc}")
            return

        external_message_id = str(payload.get("message_id") or "").strip()
        await self._push(
            message_dict,
            external_message_id=external_message_id,
            dedupe_key=f"msg:{external_message_id}" if external_message_id else "",
        )

    async def handle_notice(self, payload: Mapping[str, Any]) -> None:
        """处理通知事件。"""

        self_id = str(payload.get("self_id") or "").strip()
        notice_config = self._settings.notice

        message_dict = build_notice_message_dict(
            payload,
            self_id=self_id,
            enable_group_recall=notice_config.enable_group_recall,
            enable_friend_recall=notice_config.enable_friend_recall,
            enable_poke=notice_config.enable_poke,
        )
        if message_dict is None:
            self._logger.debug(
                "通知事件未启用或类型未识别，已丢弃："
                f"{payload.get('notice_type')}.{payload.get('sub_type') or '<空>'}"
            )
            return

        await self._push(
            message_dict,
            external_message_id=str(payload.get("message_id") or "").strip(),
            dedupe_key=build_notice_dedupe_key(payload),
        )

    def handle_meta_event(self, payload: Mapping[str, Any]) -> None:
        """处理元事件（心跳、生命周期）。

        连接状态由 ``update_state`` 上报，这里只留一条调试日志。
        """

        meta_event_type = str(payload.get("meta_event_type") or "").strip()
        if payload.get("sub_type"):
            meta_event_type = f"{meta_event_type}.{payload.get('sub_type')}"
        self._logger.debug(f"收到元事件：{meta_event_type or '<空>'}")

    async def _push(
        self,
        message_dict: Mapping[str, Any],
        *,
        external_message_id: str,
        dedupe_key: str,
    ) -> bool:
        """把 message_dict 交给宿主。"""

        payload = dict(message_dict)
        payload["account_id"] = str(payload.get("account_id") or "").strip()
        payload["scope"] = self.scope

        try:
            accepted = await self._gateway.route_message(
                gateway_name=self._gateway_name,
                message=payload,
                external_message_id=external_message_id,
                dedupe_key=dedupe_key,
            )
        except Exception as exc:
            self._logger.warning(f"上抛消息失败：{exc}")
            return False

        if not accepted:
            self._logger.debug(
                f"宿主未接受该事件：{external_message_id or dedupe_key or '无消息 ID'}"
            )
        return bool(accepted)
