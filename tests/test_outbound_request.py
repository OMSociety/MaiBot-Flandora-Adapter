"""出站动作选择测试。"""

from __future__ import annotations

import pytest
from conftest import load

outbound = load("codecs.outbound")


def _message(raw_message, *, group_id="", user_id="", additional=None):
    message_info = {"user_info": {"user_id": user_id or "7"}, "additional_config": additional or {}}
    if group_id:
        message_info["group_info"] = {"group_id": group_id, "group_name": "测试群"}
    return {"message_id": "m1", "message_info": message_info, "raw_message": raw_message}


def test_group_message_uses_send_group_msg_with_numeric_id(logger):
    request = outbound.build_outbound_request(
        _message([{"type": "text", "data": "回复"}], group_id="88"),
        logger=logger,
    )

    assert request.action == "send_group_msg"
    assert request.params["group_id"] == 88
    assert request.params["message"] == [{"type": "text", "data": {"text": "回复"}}]


def test_private_message_prefers_platform_io_target(logger):
    request = outbound.build_outbound_request(
        _message(
            [{"type": "text", "data": "私聊回复"}],
            user_id="7",
            additional={"platform_io_target_user_id": "7"},
        ),
        logger=logger,
    )

    assert request.action == "send_private_msg"
    assert request.params["user_id"] == 7


def test_private_message_falls_back_to_user_info(logger):
    request = outbound.build_outbound_request(
        _message([{"type": "text", "data": "回复"}], user_id="9"),
        logger=logger,
    )

    assert request.action == "send_private_msg"
    assert request.params["user_id"] == 9


def test_group_takes_precedence_over_user(logger):
    request = outbound.build_outbound_request(
        _message([{"type": "text", "data": "回复"}], group_id="88", user_id="7"),
        logger=logger,
    )

    assert request.action == "send_group_msg"


def test_non_numeric_target_is_rejected_with_reason(logger):
    with pytest.raises(ValueError) as excinfo:
        outbound.build_outbound_request(
            _message([{"type": "text", "data": "回复"}], user_id="wxid_abc"),
            logger=logger,
        )

    assert "不是 Flandora 分配的数字 ID" in str(excinfo.value)


def test_missing_target_is_rejected(logger):
    message = {
        "message_id": "m1",
        "message_info": {},
        "raw_message": [{"type": "text", "data": "x"}],
    }

    with pytest.raises(ValueError):
        outbound.build_outbound_request(message, logger=logger)


def test_message_without_sendable_segments_is_rejected(logger):
    with pytest.raises(ValueError) as excinfo:
        outbound.build_outbound_request(
            _message([{"type": "reply", "data": {"target_message_id": "1"}}], group_id="88"),
            logger=logger,
        )

    assert "没有可发送的段" in str(excinfo.value)


def test_dropped_segments_are_reported(logger):
    request = outbound.build_outbound_request(
        _message(
            [
                {"type": "text", "data": "正文"},
                {"type": "image", "data": "https://example.com/a.png"},
            ],
            group_id="88",
        ),
        logger=logger,
    )

    assert request.segments == [{"type": "text", "data": {"text": "正文"}}]
    assert request.dropped


def test_route_is_used_when_message_info_has_no_target(logger):
    message = {
        "message_id": "m1",
        "message_info": {},
        "raw_message": [{"type": "text", "data": "x"}],
    }

    request = outbound.build_outbound_request(
        message,
        logger=logger,
        route={"platform": "wechat", "account_id": "1001", "group_id": "88"},
    )

    assert request.action == "send_group_msg"
    assert request.params["group_id"] == 88


def test_resolve_target_reads_group_from_additional_config(logger):
    message = {
        "message_info": {"additional_config": {"platform_io_target_group_id": "42"}},
    }

    assert outbound.resolve_target(message) == {"kind": "group", "id": "42"}
