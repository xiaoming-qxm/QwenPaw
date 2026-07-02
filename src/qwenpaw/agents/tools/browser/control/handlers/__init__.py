# -*- coding: utf-8 -*-
"""Browser Control action handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentscope.tool import ToolChunk

from .claim_tab import CLAIM_TAB_HANDLER
from .click import CLICK_HANDLER
from .dispatcher import register_handler
from .hover import HOVER_HANDLER
from .misc import (
    handle_unsupported,
)
from .navigate import NAVIGATE_HANDLER
from .navigate_back import NAVIGATE_BACK_HANDLER, NAVIGATE_FORWARD_HANDLER
from .open import OPEN_HANDLER
from .press_key import PRESS_KEY_HANDLER
from .release_tab import RELEASE_TAB_HANDLER
from .reload import RELOAD_HANDLER
from .scroll import SCROLL_HANDLER
from .select_option import SELECT_OPTION_HANDLER
from .screenshot import SCREENSHOT_HANDLER
from .snapshot import SNAPSHOT_HANDLER
from .start import START_HANDLER
from .stop import STOP_HANDLER
from .tabs import TABS_HANDLER
from .type_text import TYPE_HANDLER
from .wait_for import WAIT_FOR_HANDLER

ActionHandler = Callable[..., Awaitable[ToolChunk]]

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
register_handler("press_key", PRESS_KEY_HANDLER)
register_handler("snapshot", SNAPSHOT_HANDLER)
register_handler("screenshot", SCREENSHOT_HANDLER)
register_handler("wait_for", WAIT_FOR_HANDLER)

ACTION_HANDLERS: dict[str, ActionHandler] = {
    "start": START_HANDLER.execute,
    "tabs": TABS_HANDLER.execute,
    "open": OPEN_HANDLER.execute,
    "claim_tab": CLAIM_TAB_HANDLER.execute,
    "navigate": NAVIGATE_HANDLER.execute,
    "navigate_back": NAVIGATE_BACK_HANDLER.execute,
    "navigate_forward": NAVIGATE_FORWARD_HANDLER.execute,
    "reload": RELOAD_HANDLER.execute,
    "scroll": SCROLL_HANDLER.execute,
    "hover": HOVER_HANDLER.execute,
    "select_option": SELECT_OPTION_HANDLER.execute,
    "release_tab": RELEASE_TAB_HANDLER.execute,
    "snapshot": SNAPSHOT_HANDLER.execute,
    "click": CLICK_HANDLER.execute,
    "type": TYPE_HANDLER.execute,
    "press_key": PRESS_KEY_HANDLER.execute,
    "screenshot": SCREENSHOT_HANDLER.execute,
    "wait_for": WAIT_FOR_HANDLER.execute,
    "stop": STOP_HANDLER.execute,
    # Spec-listed actions not yet implemented by the control backend.
    "drag": handle_unsupported,
    "resize": handle_unsupported,
    "new_tab": handle_unsupported,
}


__all__ = ["ACTION_HANDLERS", "ActionHandler"]
