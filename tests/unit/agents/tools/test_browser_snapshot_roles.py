# -*- coding: utf-8 -*-
"""Browser snapshot role exports."""

from qwenpaw.agents.tools.browser_snapshot import INTERACTIVE_ROLES


def test_interactive_roles_are_importable() -> None:
    assert {"button", "link", "textbox"}.issubset(INTERACTIVE_ROLES)
