# -*- coding: utf-8 -*-
"""Click effect tracker behavior."""
# pylint: disable=protected-access

from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule

_observation = load_browser_bridge_submodule("engine.observation")
_click_effect_check = _observation._click_effect_check
_click_effect_record_click = _observation._click_effect_record_click


def test_record_click_stores_pre_click_state() -> None:
    state: dict = {}

    _click_effect_record_click(state, 42, "e5", "abc123")

    assert state["control_click_effects"]["42"] == {
        "ref": "e5",
        "snapshot_hash": "abc123",
        "consecutive_no_effect": 0,
        "pending": True,
    }


def test_check_effect_detects_unchanged_snapshot_hash() -> None:
    state: dict = {}
    _click_effect_record_click(state, 42, "e5", "abc123")

    escalated, info = _click_effect_check(state, 42, "abc123")

    assert escalated is False
    assert info["no_effect"] is True
    assert info["failed_ref"] == "e5"
    assert info["consecutive_no_effect"] == 1


def test_check_effect_escalates_after_two_consecutive_no_effects() -> None:
    state: dict = {}
    _click_effect_record_click(state, 42, "e5", "abc123")
    _click_effect_check(state, 42, "abc123")
    _click_effect_record_click(state, 42, "e5", "abc123")

    escalated, info = _click_effect_check(state, 42, "abc123")

    assert escalated is True
    assert info["failed_ref"] == "e5"
    assert info["consecutive_no_effect"] == 2


def test_check_effect_resets_when_snapshot_changes() -> None:
    state: dict = {}
    _click_effect_record_click(state, 42, "e5", "abc123")

    escalated, info = _click_effect_check(state, 42, "changed")

    assert escalated is False
    assert info["no_effect"] is False
    assert "42" not in state.get("control_click_effects", {})


def test_record_click_resets_counter_for_different_ref() -> None:
    state: dict = {}
    _click_effect_record_click(state, 42, "e5", "abc123")
    _click_effect_check(state, 42, "abc123")

    _click_effect_record_click(state, 42, "e6", "abc123")

    assert state["control_click_effects"]["42"] == {
        "ref": "e6",
        "snapshot_hash": "abc123",
        "consecutive_no_effect": 0,
        "pending": True,
    }
