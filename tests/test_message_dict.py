"""入站 message_dict 与通知事件测试。"""

from __future__ import annotations

import pytest
from conftest import load

inbound = load("codecs.inbound")
notice = load("codecs.notice")


def _group_event(**overrides):
    event = {
        "time": 1730000000,
        "self_id": 1001,
        "post_type": "message",
        "message_id": 555,
        "message_type": "group",
        "group_id": 88,
        "group_wxid": "123456@chatroom",
        "group_name": "测试群",
        "user_id": 7,
        "is_mentioned": True,
        "sender": {"user_id": 7, "nickname": "小明", "wxid": "wxid_sender"},
        "message": [
            {"type": "text", "data": {"text": "你好"}},
            {"type": "at", "data": {"qq": 1001}},
        ],
        "raw_message": "你好[CQ:at,qq=1001]",
    }
    event.update(overrides)
    return event


def test_group_message_dict_matches_host_contract(logger):
    built = inbound.build_message_dict(
        _group_event(), self_id="1001", attachment_max_bytes=1024, logger=logger
    )

    assert built["message_id"] == "555"
    assert built["platform"] == "wechat"
    assert built["account_id"] == "1001"
    assert built["is_notify"] is False
    assert built["message_info"]["group_info"] == {"group_id": "88", "group_name": "测试群"}
    assert built["message_info"]["user_info"]["user_id"] == "7"
    assert built["message_info"]["user_info"]["user_nickname"] == "小明"


def test_additional_config_carries_wxids_and_mention_flags(logger):
    built = inbound.build_message_dict(
        _group_event(), self_id="1001", attachment_max_bytes=1024, logger=logger
    )

    assert built["message_info"]["additional_config"] == {
        "at_bot": True,
        "flandora_wxid": "wxid_sender",
        "flandora_group_wxid": "123456@chatroom",
    }


def test_private_message_has_no_group_info(logger):
    event = _group_event(
        message_type="private",
        group_id=0,
        group_wxid="",
        group_name="",
        is_mentioned=False,
        message=[{"type": "text", "data": {"text": "在吗"}}],
    )

    built = inbound.build_message_dict(
        event, self_id="1001", attachment_max_bytes=1024, logger=logger
    )

    assert "group_info" not in built["message_info"]
    assert built["is_at"] is False
    assert built["message_info"]["additional_config"]["at_bot"] is False


def test_missing_message_id_is_rejected(logger):
    with pytest.raises(ValueError):
        inbound.build_message_dict(
            _group_event(message_id=0), self_id="1001", attachment_max_bytes=1024, logger=logger
        )


def test_missing_sender_is_rejected(logger):
    with pytest.raises(ValueError):
        inbound.build_message_dict(
            _group_event(user_id=0, sender={}),
            self_id="1001",
            attachment_max_bytes=1024,
            logger=logger,
        )


def test_raw_message_is_used_when_segment_list_is_empty(logger):
    built = inbound.build_message_dict(
        _group_event(message=[], raw_message="裸文本"),
        self_id="1001",
        attachment_max_bytes=1024,
        logger=logger,
    )

    assert built["processed_plain_text"] == "裸文本"


def test_quote_of_bot_message_wakes_via_prepended_at(logger):
    """Flandora 在被引消息属于机器人时，会在段数组最前面补一个 at 自己的段。"""

    built = inbound.build_message_dict(
        _group_event(
            message=[
                {"type": "at", "data": {"qq": 1001}},
                {"type": "reply", "data": {"id": 500}},
                {"type": "text", "data": {"text": "这句什么意思"}},
            ],
            is_mentioned=False,
        ),
        self_id="1001",
        attachment_max_bytes=1024,
        logger=logger,
    )

    assert built["is_at"] is True
    assert built["is_mentioned"] is True
    assert built["message_info"]["additional_config"]["at_bot"] is True
    assert built["raw_message"][1]["type"] == "reply"


def test_group_recall_notice_reports_message_id(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000001,
            "notice_type": "group_recall",
            "group_id": 88,
            "user_id": 7,
            "operator_id": 8,
            "message_id": 444,
            "message_id_known": True,
        },
        self_id="1001",
    )

    assert built is not None
    assert built["is_notify"] is True
    assert built["processed_plain_text"] == "[事件-群撤回] 8 撤回了 7 的消息（message_id=444）"
    assert built["message_info"]["group_info"]["group_id"] == "88"
    assert built["message_info"]["additional_config"]["flandora_notice_type"] == "group_recall"


def test_group_recall_notice_omits_unknown_message_id(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000001,
            "notice_type": "group_recall",
            "group_id": 88,
            "user_id": 7,
            "operator_id": 8,
            "message_id": 0,
            "message_id_known": False,
        },
        self_id="1001",
    )

    assert built is not None
    assert "message_id" not in built["processed_plain_text"]


def test_friend_recall_notice_text(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000002,
            "notice_type": "friend_recall",
            "user_id": 7,
            "message_id": 12,
            "message_id_known": True,
        },
        self_id="1001",
    )

    assert built is not None
    assert built["processed_plain_text"] == "[事件-私聊撤回] 7 撤回了一条消息（message_id=12）"
    assert "group_info" not in built["message_info"]


def test_poke_notice_text(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000003,
            "notice_type": "notify",
            "sub_type": "poke",
            "user_id": 7,
            "target_id": 1001,
        },
        self_id="1001",
    )

    assert built is not None
    assert built["processed_plain_text"] == "[事件-戳一戳] 7 拍了拍你"


def test_notice_uses_resolved_names(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000005,
            "notice_type": "group_recall",
            "group_id": 88,
            "user_id": 7,
            "operator_id": 8,
            "message_id": 444,
            "message_id_known": True,
        },
        self_id="1001",
        names={"operator": "张三", "user": "李四"},
    )

    assert built is not None
    assert (
        built["processed_plain_text"] == "[事件-群撤回] 张三 撤回了 李四 的消息（message_id=444）"
    )
    assert built["message_info"]["user_info"]["user_nickname"] == "张三"
    assert built["message_info"]["user_info"]["user_id"] == "8"


def test_self_recall_reads_as_one_message(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000006,
            "notice_type": "group_recall",
            "group_id": 88,
            "user_id": 7,
            "operator_id": 7,
            "message_id": 0,
            "message_id_known": False,
        },
        self_id="1001",
        names={"operator": "张三"},
    )

    assert built is not None
    assert built["processed_plain_text"] == "[事件-群撤回] 张三 撤回了一条消息"


def test_poke_notice_includes_suffix_and_target(logger):
    built = notice.build_notice_message_dict(
        {
            "time": 1730000007,
            "notice_type": "notify",
            "sub_type": "poke",
            "user_id": 7,
            "target_id": 1001,
            "suffix": "拍了拍我的小肚子",
        },
        self_id="1001",
        names={"operator": "张三"},
    )

    assert built is not None
    assert built["processed_plain_text"] == "[事件-戳一戳] 张三 拍了拍你（拍了拍我的小肚子）"


def test_notice_respects_disable_switch(logger):
    payload = {
        "time": 1730000004,
        "notice_type": "group_recall",
        "group_id": 88,
        "user_id": 7,
        "operator_id": 8,
        "message_id": 444,
        "message_id_known": True,
    }

    assert (
        notice.build_notice_message_dict(payload, self_id="1001", enable_group_recall=False) is None
    )


def test_unknown_notice_is_ignored(logger):
    assert (
        notice.build_notice_message_dict(
            {"notice_type": "group_admin", "user_id": 7},
            self_id="1001",
        )
        is None
    )


def test_notice_dedupe_key_is_stable_and_distinct(logger):
    first = {"notice_type": "group_recall", "group_id": 88, "user_id": 7, "message_id": 444}
    second = dict(first)
    other = dict(first, message_id=445)

    assert notice.build_notice_dedupe_key(first) == notice.build_notice_dedupe_key(second)
    assert notice.build_notice_dedupe_key(first) != notice.build_notice_dedupe_key(other)
    assert notice.build_notice_dedupe_key(first).startswith("notice:")
