# -*- coding: utf-8 -*-
"""Build role snapshot + refs from Playwright aria_snapshot."""

import re
from typing import Any

INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "treeitem",
    },
)

CONTENT_ROLES = frozenset(
    {
        "heading",
        "cell",
        "gridcell",
        "columnheader",
        "rowheader",
        "listitem",
        "article",
        "region",
        "main",
        "navigation",
    },
)

STRUCTURAL_ROLES = frozenset(
    {
        "generic",
        "group",
        "list",
        "table",
        "row",
        "rowgroup",
        "grid",
        "treegrid",
        "menu",
        "menubar",
        "toolbar",
        "tablist",
        "tree",
        "directory",
        "document",
        "application",
        "presentation",
        "none",
    },
)

_DOM_SNAPSHOT_MAX_LINES = 220
_DOM_SNAPSHOT_MAX_TEXT_LENGTH = 180

_BASE64_IMAGE_PREFIXES = (
    "ivborw0kggo",  # PNG
    "/9j/",  # JPEG
    "r0lgod",  # GIF
    "uklgr",  # WebP RIFF
)


def _get_indent_level(line: str) -> int:
    m = re.match(r"^(\s*)", line)
    return int(len(m.group(1)) / 2) if m else 0


def _create_tracker() -> dict[str, Any]:
    counts: dict[str, int] = {}
    refs_by_key: dict[str, list[str]] = {}

    def get_key(role: str, name: str | None) -> str:
        return f"{role}:{name or ''}"

    def get_next_index(role: str, name: str | None) -> int:
        key = get_key(role, name)
        current = counts.get(key, 0)
        counts[key] = current + 1
        return current

    def track_ref(role: str, name: str | None, ref: str) -> None:
        key = get_key(role, name)
        refs_by_key.setdefault(key, []).append(ref)

    def get_duplicate_keys() -> set[str]:
        return {k for k, refs in refs_by_key.items() if len(refs) > 1}

    return {
        "get_next_index": get_next_index,
        "track_ref": track_ref,
        "get_duplicate_keys": get_duplicate_keys,
        "get_key": get_key,
    }


def _remove_nth_from_non_duplicates(
    refs: dict[str, dict],
    tracker: dict,
) -> None:
    dup_keys = tracker["get_duplicate_keys"]()
    for _, data in list(refs.items()):
        key = tracker["get_key"](data["role"], data.get("name"))
        if key not in dup_keys and "nth" in data:
            del data["nth"]


def _compact_tree(tree: str) -> str:
    lines = tree.split("\n")
    result = []
    for i, line in enumerate(lines):
        if "[ref=" in line:
            result.append(line)
            continue
        if ":" in line and not line.rstrip().endswith(":"):
            result.append(line)
            continue
        current_indent = _get_indent_level(line)
        has_relevant = False
        for j in range(i + 1, len(lines)):
            if _get_indent_level(lines[j]) <= current_indent:
                break
            if "[ref=" in lines[j]:
                has_relevant = True
                break
        if has_relevant:
            result.append(line)
    return "\n".join(result)


def _process_line(  # pylint: disable=too-many-return-statements
    line: str,
    refs: dict[str, dict],
    options: dict[str, Any],
    tracker: dict,
    next_ref: Any,
) -> str | None:
    depth = _get_indent_level(line)
    max_depth_val = options.get("maxDepth")
    if max_depth_val is not None and depth > max_depth_val:
        return None

    m = re.match(r'^(\s*-\s*)(\w+)(?:\s+"([^"]*)")?(.*)$', line)
    if not m:
        return None if options.get("interactive") else line

    prefix, role_raw, name, suffix = m.groups()
    if role_raw.startswith("/"):
        return None if options.get("interactive") else line

    role = role_raw.lower()
    is_interactive = role in INTERACTIVE_ROLES
    is_content = role in CONTENT_ROLES
    is_structural = role in STRUCTURAL_ROLES

    if options.get("interactive") and not is_interactive:
        return None
    if options.get("compact") and is_structural and not name:
        return None

    should_have_ref = is_interactive or (is_content and name)
    if not should_have_ref:
        return line

    ref = next_ref()
    nth = tracker["get_next_index"](role, name)
    tracker["track_ref"](role, name, ref)
    refs[ref] = {"role": role, "name": name, "nth": nth}

    enhanced = f"{prefix}{role_raw}"
    if name:
        enhanced += f' "{name}"'
    enhanced += f" [ref={ref}]"
    if nth is not None and nth > 0:
        enhanced += f" [nth={nth}]"
    if suffix:
        enhanced += suffix
    return enhanced


def build_role_snapshot_from_aria(
    aria_snapshot: str,
    *,
    interactive: bool = False,
    compact: bool = False,
    max_depth: int | None = None,
) -> tuple[str, dict[str, dict]]:
    """Build snapshot + refs from Playwright locator.aria_snapshot() output."""
    options = {
        "interactive": interactive,
        "compact": compact,
        "maxDepth": max_depth,
    }
    lines = aria_snapshot.split("\n")
    refs: dict[str, dict] = {}
    tracker = _create_tracker()
    counter = [0]

    def next_ref() -> str:
        counter[0] += 1
        return f"e{counter[0]}"

    if options.get("interactive"):
        result_lines = []
        for line in lines:
            depth = _get_indent_level(line)
            max_d = options.get("maxDepth")
            if max_d is not None and depth > max_d:
                continue
            m = re.match(r'^(\s*-\s*)(\w+)(?:\s+"([^"]*)")?(.*)$', line)
            if not m:
                continue
            _, role_raw, name, suffix = m.groups()
            if role_raw.startswith("/"):
                continue
            role = role_raw.lower()
            if role not in INTERACTIVE_ROLES:
                continue
            ref = next_ref()
            nth = tracker["get_next_index"](role, name)
            tracker["track_ref"](role, name, ref)
            refs[ref] = {"role": role, "name": name, "nth": nth}
            enhanced = f"- {role_raw}"
            if name:
                enhanced += f' "{name}"'
            enhanced += f" [ref={ref}]"
            if nth is not None and nth > 0:
                enhanced += f" [nth={nth}]"
            if "[" in suffix:
                enhanced += suffix
            result_lines.append(enhanced)
        _remove_nth_from_non_duplicates(refs, tracker)
        snapshot = "\n".join(result_lines) or "(no interactive elements)"
        return snapshot, refs

    result_lines = []
    for line in lines:
        processed = _process_line(line, refs, options, tracker, next_ref)
        if processed is not None:
            result_lines.append(processed)
    _remove_nth_from_non_duplicates(refs, tracker)
    tree = "\n".join(result_lines) or "(empty)"
    snapshot = _compact_tree(tree) if options.get("compact") else tree
    return snapshot, refs


def _ax_value(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        value = raw.get("value")
    else:
        value = raw
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _dom_snapshot_string(strings: Any, value: Any) -> str:
    if isinstance(value, int) and isinstance(strings, list):
        if 0 <= value < len(strings):
            return str(strings[value])
        return ""
    if isinstance(value, str):
        return value
    return ""


def _dom_snapshot_value_at(values: Any, index: int) -> Any:
    return (
        values[index]
        if isinstance(values, list) and index < len(values)
        else None
    )


def _normalize_dom_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _DOM_SNAPSHOT_MAX_TEXT_LENGTH:
        text = text[: _DOM_SNAPSHOT_MAX_TEXT_LENGTH - 1].rstrip() + "…"
    return text


def _is_private_use_only(text: str) -> bool:
    compact = "".join(ch for ch in text if not ch.isspace())
    return bool(compact) and all("\ue000" <= ch <= "\uf8ff" for ch in compact)


def _looks_like_encoded_blob(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False

    lower = compact.lower()
    if "base64," in lower and lower.startswith("data:"):
        return True
    if lower.startswith(_BASE64_IMAGE_PREFIXES):
        return True
    if re.search(r"[\u4e00-\u9fff]", compact):
        return False
    if len(compact) < 120:
        return False

    base64_chars = sum(
        1 for ch in compact if ch.isalnum() or ch in {"+", "/", "="}
    )
    symbol_hint = any(ch in compact for ch in ("+", "/", "="))
    digit_count = sum(1 for ch in compact if ch.isdigit())
    return base64_chars / len(compact) > 0.96 and (
        symbol_hint or digit_count / len(compact) > 0.12
    )


def _dom_snapshot_backend_node_id(
    nodes: dict[str, Any],
    node_index: int,
) -> int | None:
    backend_ids = nodes.get("backendNodeId")
    value = _dom_snapshot_value_at(backend_ids, node_index)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _dom_snapshot_bounds_center(bounds: Any) -> tuple[float, float] | None:
    if not isinstance(bounds, list) or len(bounds) < 4:
        return None
    x, y, width, height = bounds[:4]
    if not all(
        isinstance(value, (int, float)) for value in (x, y, width, height)
    ):
        return None
    if width <= 0 or height <= 0:
        return None
    return (float(x) + float(width) / 2, float(y) + float(height) / 2)


def _unique_dom_text(
    seen: set[str],
    text: str,
) -> str | None:
    if _is_private_use_only(text) or _looks_like_encoded_blob(text):
        return None
    text = _normalize_dom_text(text)
    if not text or text in seen:
        return None
    seen.add(text)
    return text


# pylint: disable-next=too-many-branches,too-many-statements
def from_cdp_dom_snapshot(
    snapshot_json: dict[str, Any],
) -> tuple[str, dict[str, dict]]:
    """Build a read-only text snapshot from CDP DOMSnapshot output."""
    documents = snapshot_json.get("documents")
    strings = snapshot_json.get("strings") or []
    if not isinstance(documents, list):
        return "(empty)", {}

    lines: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    refs: dict[str, dict] = {}
    ref_counter = 0

    def append_line(text: str, ref_data: dict[str, Any] | None = None) -> None:
        nonlocal ref_counter
        normalized = _unique_dom_text(seen, text)
        if normalized is None:
            return
        ref: str | None = None
        if ref_data is not None:
            ref_counter += 1
            ref = f"e{ref_counter}"
            refs[ref] = {
                "role": "text",
                "name": normalized,
                **ref_data,
            }
        lines.append((normalized, ref))

    for document in documents:
        if not isinstance(document, dict):
            continue
        nodes = document.get("nodes") or {}
        layout = document.get("layout") or {}
        node_names = nodes.get("nodeName") or []
        node_values = nodes.get("nodeValue") or []
        text_values = nodes.get("textValue") or {}
        input_values = nodes.get("inputValue") or {}
        layout_node_indexes = layout.get("nodeIndex") or []
        layout_texts = layout.get("text") or []
        layout_bounds = layout.get("bounds") or []

        for index, raw_text in enumerate(layout_texts):
            text = _dom_snapshot_string(strings, raw_text)
            node_index = _dom_snapshot_value_at(layout_node_indexes, index)
            if not text:
                if isinstance(node_index, int):
                    text = _dom_snapshot_string(
                        strings,
                        _dom_snapshot_value_at(node_values, node_index),
                    )
            ref_data = None
            if isinstance(node_index, int):
                center = _dom_snapshot_bounds_center(
                    _dom_snapshot_value_at(layout_bounds, index),
                )
                if center is not None:
                    ref_data = {"x": center[0], "y": center[1]}
                    backend_id = _dom_snapshot_backend_node_id(
                        nodes,
                        node_index,
                    )
                    if backend_id is not None:
                        ref_data["backendNodeId"] = backend_id
            append_line(text, ref_data)
            if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
                break

        if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
            break

        for values in (text_values, input_values):
            if not isinstance(values, dict):
                continue
            value_indexes = values.get("index") or []
            raw_values = values.get("value") or []
            for pos, _node_index in enumerate(value_indexes):
                raw_value = _dom_snapshot_value_at(raw_values, pos)
                text = _dom_snapshot_string(strings, raw_value)
                append_line(text)
                if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
                    break
            if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
                break

        if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
            break

        for node_index, raw_name in enumerate(node_names):
            name = _dom_snapshot_string(strings, raw_name).lower()
            if name not in {"title", "h1", "h2", "h3", "button", "a"}:
                continue
            text = _dom_snapshot_string(
                strings,
                _dom_snapshot_value_at(node_values, node_index),
            )
            append_line(text)
            if len(lines) >= _DOM_SNAPSHOT_MAX_LINES:
                break

    if not lines:
        return "(empty)", {}
    rendered_lines = []
    for line, ref in lines:
        escaped = line.replace('"', '\\"')
        suffix = f" [ref={ref}]" if ref else ""
        rendered_lines.append(f'- text "{escaped}"{suffix}')
    return "\n".join(rendered_lines), refs


def from_cdp_ax_tree(
    ax_tree_json: dict[str, Any],
) -> tuple[str, dict[str, dict]]:
    """Build snapshot + refs from CDP Accessibility.getFullAXTree output."""
    nodes = ax_tree_json.get("nodes", ax_tree_json)
    if not isinstance(nodes, list):
        return "(empty)", {}

    by_id = {
        str(node.get("nodeId")): node for node in nodes if "nodeId" in node
    }
    child_ids = {
        str(child_id)
        for node in nodes
        for child_id in node.get("childIds", []) or []
    }
    roots = [
        node for node in nodes if str(node.get("nodeId")) not in child_ids
    ] or nodes[:1]

    refs: dict[str, dict] = {}
    tracker = _create_tracker()
    counter = [0]
    lines: list[str] = []

    def next_ref() -> str:
        counter[0] += 1
        return f"e{counter[0]}"

    def visit(node: dict[str, Any], depth: int) -> None:
        if node.get("ignored"):
            return

        role_raw = _ax_value(node.get("role"))
        if not role_raw:
            return
        role = role_raw.lower()
        name = _ax_value(node.get("name"))

        is_interactive = role in INTERACTIVE_ROLES
        is_content = role in CONTENT_ROLES
        should_have_ref = is_interactive or (is_content and name)

        prefix = "  " * depth
        line = f"{prefix}- {role_raw}"
        if name:
            escaped_name = name.replace('"', '\\"')
            line += f' "{escaped_name}"'

        if should_have_ref:
            ref = next_ref()
            nth = tracker["get_next_index"](role, name)
            tracker["track_ref"](role, name, ref)
            ref_data = {"role": role, "name": name, "nth": nth}
            backend_id = node.get("backendDOMNodeId") or node.get(
                "backendNodeId",
            )
            if backend_id is not None:
                ref_data["backendNodeId"] = backend_id
            refs[ref] = ref_data

            line += f" [ref={ref}]"
            if nth is not None and nth > 0:
                line += f" [nth={nth}]"

        lines.append(line)
        for child_id in node.get("childIds", []) or []:
            child = by_id.get(str(child_id))
            if child is not None:
                visit(child, depth + 1)

    for root in roots:
        visit(root, 0)

    _remove_nth_from_non_duplicates(refs, tracker)
    return "\n".join(lines) or "(empty)", refs
