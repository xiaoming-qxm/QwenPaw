# -*- coding: utf-8 -*-
"""Browser Bridge action handler registry."""

from __future__ import annotations

from .capabilities import (
    DIALOG_HANDLER,
    DOWNLOAD_HANDLER,
    PAGE_PDF_HANDLER,
    UPLOAD_HANDLER,
)
from .claim_tab import CLAIM_TAB_HANDLER
from .click import CLICK_HANDLER
from .dispatcher import _REGISTRY, register_handler
from .drag import DRAG_HANDLER
from .hover import HOVER_HANDLER
from .navigate import NAVIGATE_HANDLER
from .navigate_back import NAVIGATE_BACK_HANDLER, NAVIGATE_FORWARD_HANDLER
from .open import OPEN_HANDLER
from .paste import PASTE_HANDLER
from .press_key import PRESS_KEY_HANDLER
from .release_tab import RELEASE_TAB_HANDLER
from .reload import RELOAD_HANDLER
from .scroll import SCROLL_HANDLER
from .set_checked import SET_CHECKED_HANDLER
from .select_option import SELECT_OPTION_HANDLER
from .screenshot import SCREENSHOT_HANDLER
from .snapshot import SNAPSHOT_HANDLER
from .start import START_HANDLER
from .stop import STOP_HANDLER
from .tabs import TABS_HANDLER
from .type_text import FILL_HANDLER, TYPE_HANDLER, TYPE_TEXT_HANDLER
from .wait_for import WAIT_FOR_HANDLER

register_handler("start", START_HANDLER)
register_handler("tabs", TABS_HANDLER)
register_handler("stop", STOP_HANDLER)
register_handler("open", OPEN_HANDLER)
register_handler("claim_tab", CLAIM_TAB_HANDLER)
register_handler("release_tab", RELEASE_TAB_HANDLER)
register_handler("navigate", NAVIGATE_HANDLER)
register_handler("navigate_back", NAVIGATE_BACK_HANDLER)
register_handler("navigate_forward", NAVIGATE_FORWARD_HANDLER)
register_handler("reload", RELOAD_HANDLER)
register_handler("scroll", SCROLL_HANDLER)
register_handler("hover", HOVER_HANDLER)
register_handler("select_option", SELECT_OPTION_HANDLER)
register_handler("click", CLICK_HANDLER)
register_handler("type", TYPE_HANDLER)
register_handler("fill", FILL_HANDLER)
register_handler("type_text", TYPE_TEXT_HANDLER)
register_handler("press_key", PRESS_KEY_HANDLER)
register_handler("drag", DRAG_HANDLER)
register_handler("set_checked", SET_CHECKED_HANDLER)
register_handler("upload", UPLOAD_HANDLER)
register_handler("download", DOWNLOAD_HANDLER)
register_handler("page_pdf", PAGE_PDF_HANDLER)
register_handler("paste", PASTE_HANDLER)
register_handler("dialog", DIALOG_HANDLER)
register_handler("snapshot", SNAPSHOT_HANDLER)
register_handler("screenshot", SCREENSHOT_HANDLER)
register_handler("wait_for", WAIT_FOR_HANDLER)

SUPPORTED_ACTIONS = frozenset((*_REGISTRY, "resize", "new_tab"))


__all__ = ["SUPPORTED_ACTIONS"]
