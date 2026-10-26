"""Flandora 适配器的编解码层。"""

from __future__ import annotations

from .inbound import build_inbound_segments, build_message_dict
from .notice import build_notice_dedupe_key, build_notice_message_dict
from .outbound import OutboundRequest, build_outbound_request, resolve_target
from .segments_in import InboundSegments, build_components, build_plain_text
from .segments_out import OutboundSegments, build_outbound_segments

__all__ = [
    "InboundSegments",
    "OutboundRequest",
    "OutboundSegments",
    "build_components",
    "build_inbound_segments",
    "build_message_dict",
    "build_notice_dedupe_key",
    "build_notice_message_dict",
    "build_outbound_request",
    "build_outbound_segments",
    "build_plain_text",
    "resolve_target",
]
