"""入站段翻译测试。"""

from __future__ import annotations

import base64

from conftest import load

segments_in = load("codecs.segments_in")


def _build(segments, *, self_id="1001", limit=1024 * 1024, logger=None):
    return segments_in.build_components(
        segments,
        self_id=self_id,
        attachment_max_bytes=limit,
        logger=logger,
    )


def test_text_segment_becomes_bare_string_component(logger):
    built = _build([{"type": "text", "data": {"text": "你好"}}], logger=logger)

    assert built.components == [{"type": "text", "data": "你好"}]
    assert segments_in.build_plain_text(built.components) == "你好"


def test_at_segment_marks_bot_and_uses_host_field_names(logger):
    built = _build([{"type": "at", "data": {"qq": 1001}}], self_id="1001", logger=logger)

    assert built.at_bot is True
    assert built.components[0] == {
        "type": "at",
        "data": {
            "target_user_id": "1001",
            "target_user_nickname": None,
            "target_user_cardname": None,
        },
    }


def test_at_other_user_does_not_mark_bot(logger):
    built = _build([{"type": "at", "data": {"qq": 2002}}], self_id="1001", logger=logger)

    assert built.at_bot is False
    assert built.components[0]["data"]["target_user_id"] == "2002"


def test_at_all_degrades_to_text(logger):
    built = _build([{"type": "at", "data": {"qq": "all"}}], logger=logger)

    assert built.components == [{"type": "text", "data": "@全体成员"}]


def test_at_with_only_nickname_degrades_to_text(logger):
    built = _build([{"type": "at", "data": {"qq": "", "name": "小明"}}], logger=logger)

    assert built.components == [{"type": "text", "data": "@小明"}]


def test_image_base64_segment_carries_hash_and_payload(logger):
    payload = b"\x89PNG-demo"
    encoded = base64.b64encode(payload).decode("ascii")

    built = _build([{"type": "image", "data": {"file": f"base64://{encoded}"}}], logger=logger)

    component = built.components[0]
    assert built.has_picture is True
    assert component["type"] == "image"
    assert component["data"] == ""
    assert base64.b64decode(component["binary_data_base64"]) == payload
    assert len(component["hash"]) == 64


def test_image_over_limit_degrades_to_placeholder(logger):
    encoded = base64.b64encode(b"x" * 32).decode("ascii")

    built = _build(
        [{"type": "image", "data": {"file": f"base64://{encoded}"}}],
        limit=8,
        logger=logger,
    )

    assert built.components[0]["type"] == "text"
    assert "超过内联上限" in built.components[0]["data"]


def test_image_with_missing_file_degrades_to_placeholder(logger):
    built = _build(
        [{"type": "image", "data": {"file": "file:///definitely/not/here.png"}}], logger=logger
    )

    assert built.components == [{"type": "text", "data": "[图片]"}]
    assert built.has_picture is True


def test_record_degrades_to_placeholder_when_unreadable(logger):
    built = _build([{"type": "record", "data": {"file": "file:///not/here.mp3"}}], logger=logger)

    assert built.components == [{"type": "text", "data": "[语音]"}]


def test_video_degrades_to_placeholder(logger):
    built = _build([{"type": "video", "data": {"file": "file:///not/here.mp4"}}], logger=logger)

    assert built.components == [{"type": "text", "data": "[视频]"}]


def test_face_degrades_to_text_placeholder(logger):
    built = _build([{"type": "face", "data": {"id": 178}}], logger=logger)

    assert built.components == [{"type": "text", "data": "[表情 178]"}]
    assert built.has_emoji is True


def test_file_segment_carries_name_size_and_payload(logger):
    encoded = base64.b64encode(b"report").decode("ascii")

    built = _build(
        [{"type": "file", "data": {"file": f"base64://{encoded}", "name": "报表.xlsx"}}],
        logger=logger,
    )

    component = built.components[0]
    assert component["type"] == "file"
    assert component["data"]["name"] == "报表.xlsx"
    assert component["data"]["size"] == "6"
    assert component["data"]["base64"] == encoded


def test_reply_segment_keeps_target_message_id(logger):
    built = _build([{"type": "reply", "data": {"id": 4321}}], logger=logger)

    assert built.components == [{"type": "reply", "data": {"target_message_id": "4321"}}]


def test_forward_segment_degrades_to_placeholder(logger):
    built = _build([{"type": "node", "data": {}}], logger=logger)

    assert built.components == [{"type": "text", "data": "[合并转发]"}]


def test_unknown_segment_is_kept_as_placeholder(logger):
    built = _build([{"type": "music", "data": {}}], logger=logger)

    assert built.components == [{"type": "text", "data": "[未识别的段 music]"}]


def test_http_reference_is_never_downloaded(logger):
    built = _build(
        [{"type": "image", "data": {"file": "https://example.com/a.png"}}], logger=logger
    )

    assert built.components == [{"type": "text", "data": "[图片]"}]
