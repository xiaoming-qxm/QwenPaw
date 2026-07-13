# -*- coding: utf-8 -*-
"""Message conversion between AgentRequest and agentscope Msg."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, cast
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrustedAttachmentDescriptor:
    """Host-issued local attachment identity kept outside model blocks."""

    name: str
    media_type: str
    _location: Path = field(repr=False)

    @property
    def location(self) -> Path:
        """Return the private host location to trusted Runtime code only."""
        return self._location


def _media_type_to_block_type(media_type: str | None) -> str:
    """Map a MIME media_type to the 1.x block type the frontend expects.

    AS 2.0 uses ``"data"`` for all media; the frontend renderer still
    expects ``"image"``/``"video"``/``"audio"``.
    """
    if not media_type:
        return "data"
    major = media_type.split("/", 1)[0]
    if major in ("image", "video", "audio"):
        return major
    return "data"


def _get_last_user_text(msgs: List[Any]) -> str | None:
    """Extract the text of the last user message from a list of ``Msg``."""
    if not msgs:
        return None
    last = msgs[-1]
    if hasattr(last, "get_text_content"):
        return last.get_text_content()
    return None


def _ensure_url_scheme(url: str) -> str:
    """Prepend ``file://`` when *url* is an absolute local path.

    Handles both Unix paths (``/``, ``~``) and Windows paths
    (e.g. ``C:\\`` or ``C:/``).

    Always ``unquote()`` first so percent-encoded non-ASCII characters
    (e.g. ``%E6%B5%8B%E8%AF%95`` → ``测试``) resolve to the real
    filename on disk.  Then uses ``file://`` + raw path (not
    ``Path.as_uri()``) to avoid re-encoding.
    """
    if url.startswith(("/", "~")):
        resolved = str(Path(unquote(url)).expanduser().resolve())
    elif len(url) >= 3 and url[1] == ":" and url[2] in ("/", "\\"):
        resolved = str(Path(unquote(url)).resolve())
    else:
        return url

    resolved = resolved.replace("\\", "/")
    if not resolved.startswith("/"):
        resolved = "/" + resolved
    return "file://" + resolved


def _request_input_to_msgs(
    input_list: List[Any],
    *,
    trusted_attachments: list[TrustedAttachmentDescriptor] | None = None,
) -> List[Any]:
    """Convert ``AgentRequest.input`` (list of 1.x Message) to a list of
    agentscope 2.0 ``Msg`` objects.

    Handles text, image, audio, video, and file content blocks.
    """
    try:
        from agentscope.message import Msg, TextBlock, DataBlock
        from agentscope.message._block import URLSource
    except Exception:
        logger.error(
            "Failed to import agentscope.message; user input will be dropped",
            exc_info=True,
        )
        return []

    _MEDIA_TYPES = {
        "image": "image",
        "audio": "audio",
        "video": "video",
    }

    out: List[Any] = []
    for m in input_list:
        role_raw = getattr(m, "role", None)
        role_value = getattr(role_raw, "value", role_raw) or "user"
        role = str(role_value)
        if role == "tool":
            role = "assistant"
        if role not in ("user", "assistant", "system"):
            role = "user"
        msg_role = cast(Literal["user", "assistant", "system"], role)

        blocks: list = []
        for c in getattr(m, "content", None) or []:
            block = _request_content_block(
                c,
                text_block=TextBlock,
                data_block=DataBlock,
                url_source=URLSource,
                media_types=_MEDIA_TYPES,
                trusted_attachments=trusted_attachments,
            )
            if block is not None:
                blocks.append(block)

        if not blocks:
            continue

        out.append(Msg(name=msg_role, role=msg_role, content=blocks))
    return out


def _request_content_block(
    content: object,
    *,
    text_block: Any,
    data_block: Any,
    url_source: Any,
    media_types: dict[str, str],
    trusted_attachments: list[TrustedAttachmentDescriptor] | None,
) -> object | None:
    """Convert one input part and capture only trusted local file facts."""
    ctype_raw = getattr(content, "type", None)
    ctype = getattr(ctype_raw, "value", ctype_raw)
    if ctype == "text":
        text = getattr(content, "text", None) or ""
        return text_block(type="text", text=text) if text else None
    if ctype in media_types:
        return _media_content_block(
            content,
            ctype=str(ctype),
            media_types=media_types,
            data_block=data_block,
            url_source=url_source,
        )
    if ctype == "file":
        return _file_content_block(
            content,
            data_block=data_block,
            url_source=url_source,
            trusted_attachments=trusted_attachments,
        )
    return None


def _media_content_block(
    content: object,
    *,
    ctype: str,
    media_types: dict[str, str],
    data_block: Any,
    url_source: Any,
) -> object | None:
    url = (
        getattr(content, "image_url", None)
        or getattr(content, "audio_url", None)
        or getattr(content, "video_url", None)
        or getattr(content, "url", None)
    )
    if not url:
        return None
    normalized = _ensure_url_scheme(str(url))
    guessed, _ = mimetypes.guess_type(urlparse(normalized).path)
    media_kind = media_types[ctype]
    media_type = (
        guessed
        if guessed and guessed.startswith(f"{media_kind}/")
        else f"{media_kind}/{'jpeg' if ctype == 'image' else 'mpeg'}"
    )
    try:
        return data_block(
            source=url_source(
                url=cast(Any, normalized),
                media_type=media_type,
            ),
        )
    except Exception:
        logger.debug(
            "Failed to create DataBlock for %s url=%s",
            ctype,
            normalized,
        )
        return None


def _file_content_block(
    content: object,
    *,
    data_block: Any,
    url_source: Any,
    trusted_attachments: list[TrustedAttachmentDescriptor] | None,
) -> object | None:
    url = getattr(content, "file_url", None) or getattr(content, "url", None)
    if not url:
        return None
    normalized = _ensure_url_scheme(str(url))
    filename = (
        getattr(content, "filename", None)
        or getattr(content, "file_name", None)
        or Path(unquote(urlparse(normalized).path)).name
        or "attachment.bin"
    )
    media_type = (
        mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
    )
    try:
        block = data_block(
            source=url_source(
                url=cast(Any, normalized),
                media_type=media_type,
            ),
            name=filename,
        )
        descriptor = _trusted_local_attachment(
            normalized,
            name=str(filename),
            media_type=media_type,
        )
        if descriptor is not None and trusted_attachments is not None:
            trusted_attachments.append(descriptor)
        return block
    except Exception:
        logger.debug(
            "Failed to create DataBlock for file url=%s",
            normalized,
        )
        return None


def _trusted_local_attachment(
    url: str,
    *,
    name: str,
    media_type: str,
) -> TrustedAttachmentDescriptor | None:
    """Capture only a typed host-local FileContent source."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    try:
        location = Path(unquote(parsed.path)).resolve(strict=True)
    except OSError:
        return None
    if not location.is_file():
        return None
    return TrustedAttachmentDescriptor(
        name=Path(name).name or location.name,
        media_type=media_type,
        _location=location,
    )
