"""出站段翻译测试。"""

from __future__ import annotations

import base64

from conftest import load

segments_out = load("codecs.segments_out")


def _build(components, *, logger):
    return segments_out.build_outbound_segments(components, logger=logger)


def test_text_component_becomes_nested_text_segment(logger):
    built = _build([{"type": "text", "data": "你好"}], logger=logger)

    assert built.segments == [{"type": "text", "data": {"text": "你好"}}]
    assert built.dropped == []


def test_at_component_requires_numeric_target(logger):
    built = _build([{"type": "at", "data": {"target_user_id": "1001"}}], logger=logger)

    assert built.segments == [{"type": "at", "data": {"qq": 1001}}]


def test_at_component_with_non_numeric_target_is_dropped(logger):
    built = _build([{"type": "at", "data": {"target_user_id": "wxid_abc"}}], logger=logger)

    assert built.segments == []
    assert len(built.dropped) == 1


def test_image_with_inline_bytes_becomes_base64_reference(logger):
    encoded = base64.b64encode(b"png").decode("ascii")

    built = _build(
        [{"type": "image", "data": "x", "binary_data_base64": encoded}],
        logger=logger,
    )

    assert built.segments == [{"type": "image", "data": {"file": f"base64://{encoded}"}}]


def test_image_with_local_path_is_passed_through(logger):
    built = _build([{"type": "image", "data": "file:///D:/pic/a.png"}], logger=logger)

    assert built.segments == [{"type": "image", "data": {"file": "file:///D:/pic/a.png"}}]


def test_image_with_http_url_is_dropped(logger):
    built = _build([{"type": "image", "data": "https://example.com/a.png"}], logger=logger)

    assert built.segments == []
    assert "网络地址不代下" in built.dropped[0]


def test_emoji_is_treated_as_image(logger):
    built = _build([{"type": "emoji", "data": "file:///D:/pic/e.gif"}], logger=logger)

    assert built.segments == [{"type": "image", "data": {"file": "file:///D:/pic/e.gif"}}]


def test_voice_with_inline_bytes_becomes_record_segment(logger):
    encoded = base64.b64encode(b"mp3").decode("ascii")

    built = _build(
        [{"type": "voice", "data": "x", "binary_data_base64": encoded}],
        logger=logger,
    )

    assert built.segments == [{"type": "record", "data": {"file": f"base64://{encoded}"}}]


def test_file_with_base64_payload_becomes_file_segment(logger):
    encoded = base64.b64encode(b"data").decode("ascii")

    built = _build(
        [{"type": "file", "data": {"name": "报表.xlsx", "base64": encoded}}],
        logger=logger,
    )

    assert built.segments == [
        {"type": "file", "data": {"file": f"base64://{encoded}", "name": "报表.xlsx"}}
    ]


def test_file_with_http_url_degrades_to_text(logger):
    built = _build(
        [{"type": "file", "data": {"name": "报表.xlsx", "url": "https://example.com/a.xlsx"}}],
        logger=logger,
    )

    assert built.segments == [{"type": "text", "data": {"text": "[文件] 报表.xlsx"}}]
    assert built.dropped


def test_reply_component_is_dropped(logger):
    built = _build([{"type": "reply", "data": {"target_message_id": "1"}}], logger=logger)

    assert built.segments == []
    assert built.dropped == ["reply:引用段跳过"]


def test_forward_component_is_flattened_to_text(logger):
    built = _build(
        [
            {
                "type": "forward",
                "data": [
                    {"user_nickname": "甲", "content": [{"type": "text", "data": "第一句"}]},
                    {"user_nickname": "乙", "content": [{"type": "image", "data": "x"}]},
                ],
            }
        ],
        logger=logger,
    )

    assert len(built.segments) == 1
    text = built.segments[0]["data"]["text"]
    assert text.startswith("[合并转发]\n")
    assert "甲：第一句" in text
    assert "乙：[图片]" in text


def test_unknown_component_is_dropped(logger):
    built = _build([{"type": "unknown", "data": {}}], logger=logger)

    assert built.segments == []
    assert built.dropped == ["unknown:未识别的类型"]


def test_segments_preserve_order(logger):
    built = _build(
        [
            {"type": "text", "data": "看这个"},
            {"type": "image", "data": "file:///D:/pic/a.png"},
        ],
        logger=logger,
    )

    assert [segment["type"] for segment in built.segments] == ["text", "image"]
