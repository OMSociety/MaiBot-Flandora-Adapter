"""把内联的二进制数据折叠成占位说明。

一条消息里的内联载荷是 base64 编码的字节串，本意是给程序解码用的；一旦它落进日志、
`raw_message` 兜底文本或模型上下文，就会白白吃掉几 MB 的配额，还把内容变成噪声。
凡是可能被当作文本看待的地方，都先过一遍 `fold_inline_base64`。
"""

from __future__ import annotations

import re

# 只折叠足够长、明显是二进制载荷的串：短串可能是文件名或占位说明
_INLINE_PATTERN = re.compile(r"base64://([A-Za-z0-9+/=]{32,})")


def fold_inline_base64(text: str) -> str:
    """把 ``base64://<长串>`` 折成 ``base64://<N 字符已省略>``。

    Args:
        text: 任意可能含内联载荷的文本。

    Returns:
        str: 折叠后的文本；不含内联载荷时原样返回。
    """

    if not text or "base64://" not in text:
        return text or ""

    def _replace(match: re.Match[str]) -> str:
        return f"base64://<{len(match.group(1))} 字符已省略>"

    return _INLINE_PATTERN.sub(_replace, text)
