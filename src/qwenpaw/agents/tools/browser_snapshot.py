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
_DOM_TREE_MAX_LINES = 160
_AX_TREE_MAX_LINES = 180
_AX_TREE_MAX_TEXT_LENGTH = 240
_DOM_TREE_TEXT_ATTRIBUTES = (
    "aria-label",
    "alt",
    "title",
    "placeholder",
    "value",
)
_DOM_TREE_CLICKABLE_ATTRIBUTES = {
    "onclick",
    "onmousedown",
    "onmouseup",
    "data-click",
    "data-clickid",
}
_DOM_TREE_SKIPPED_NODES = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
}

_BASE64_IMAGE_PREFIXES = (
    "ivborw0kggo",  # PNG
    "/9j/",  # JPEG
    "r0lgod",  # GIF
    "uklgr",  # WebP RIFF
)
_AX_TREE_REDUNDANT_ROLES = frozenset({"inlinetextbox"})


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


def _normalize_ax_text(text: str | None) -> str | None:
    if text is None:
        return None
    if _is_private_use_only(text) or _looks_like_encoded_blob(text):
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    if not normalized:
        return None
    if len(normalized) > _AX_TREE_MAX_TEXT_LENGTH:
        normalized = normalized[: _AX_TREE_MAX_TEXT_LENGTH - 1].rstrip() + "…"
    return normalized


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


def _dom_tree_attributes(attributes: Any) -> dict[str, str]:
    if not isinstance(attributes, list):
        return {}
    result: dict[str, str] = {}
    for index in range(0, len(attributes) - 1, 2):
        name = str(attributes[index] or "").strip().lower()
        if not name:
            continue
        result[name] = str(attributes[index + 1] or "")
    return result


def _dom_tree_interactive_role(
    node_name: str,
    attributes: dict[str, str],
) -> str | None:
    role = str(attributes.get("role") or "").strip().lower()
    if role in INTERACTIVE_ROLES:
        return role

    if node_name == "a" and attributes.get("href"):
        return "link"
    if node_name == "button":
        return "button"
    if node_name == "textarea":
        return "textbox"
    if node_name == "select":
        return "combobox"
    if node_name == "summary":
        return "button"
    if node_name == "option":
        return "option"
    if node_name == "input":
        input_type = str(attributes.get("type") or "text").lower()
        if input_type in {"checkbox"}:
            return "checkbox"
        if input_type in {"radio"}:
            return "radio"
        if input_type in {"range"}:
            return "slider"
        if input_type in {"number"}:
            return "spinbutton"
        if input_type in {"search"}:
            return "searchbox"
        if input_type in {"button", "submit", "reset"}:
            return "button"
        return "textbox"
    if attributes.get("contenteditable") in {"", "true", "plaintext-only"}:
        return "textbox"
    if any(name in attributes for name in _DOM_TREE_CLICKABLE_ATTRIBUTES):
        return "button"
    return None


def _dom_tree_node_id_data(node: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    backend_node_id = node.get("backendNodeId")
    if isinstance(backend_node_id, int):
        result["backendNodeId"] = backend_node_id
    node_id = node.get("nodeId")
    if isinstance(node_id, int):
        result["nodeId"] = node_id
    return result


def _dom_tree_collect_text(node: dict[str, Any], limit: int = 600) -> str:
    pieces: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "")
        if text:
            pieces.append(text)

    def walk(current: dict[str, Any]) -> None:
        if len(" ".join(pieces)) >= limit:
            return
        node_name = str(current.get("nodeName") or "").lower()
        if node_name in _DOM_TREE_SKIPPED_NODES:
            return
        node_type = current.get("nodeType")
        if node_type == 3 or node_name == "#text":
            add(current.get("nodeValue"))
            return

        attributes = _dom_tree_attributes(current.get("attributes"))
        for attr_name in _DOM_TREE_TEXT_ATTRIBUTES:
            add(attributes.get(attr_name))

        for key in ("children", "shadowRoots", "pseudoElements"):
            children = current.get(key)
            if not isinstance(children, list):
                continue
            for child in children:
                if isinstance(child, dict):
                    walk(child)
                if len(" ".join(pieces)) >= limit:
                    return

        content_document = current.get("contentDocument")
        if isinstance(content_document, dict):
            walk(content_document)

    walk(node)
    return _normalize_dom_text(" ".join(pieces))


def from_cdp_dom_tree(
    document_json: dict[str, Any],
) -> tuple[str, dict[str, dict]]:
    """Build a bounded read-only text snapshot from CDP DOM.getDocument."""
    root = (
        document_json.get("root") if isinstance(document_json, dict) else None
    )
    if not isinstance(root, dict):
        return "(empty)", {}

    lines: list[str] = []
    seen: set[str] = set()
    refs: dict[str, dict] = {}
    tracker = _create_tracker()
    counter = 0

    def next_ref() -> str:
        nonlocal counter
        counter += 1
        return f"e{counter}"

    def append_line(text: Any) -> None:
        if len(lines) >= _DOM_TREE_MAX_LINES:
            return
        normalized = _unique_dom_text(seen, str(text or ""))
        if normalized is None:
            return
        escaped = normalized.replace('"', '\\"')
        lines.append(f'- text "{escaped}"')

    def append_interactive_line(
        role: str,
        text: Any,
        node: dict[str, Any],
    ) -> bool:
        if len(lines) >= _DOM_TREE_MAX_LINES:
            return False
        normalized = _unique_dom_text(seen, str(text or ""))
        if normalized is None:
            return False
        ref = next_ref()
        nth = tracker["get_next_index"](role, normalized)
        tracker["track_ref"](role, normalized, ref)
        ref_data = {
            "role": role,
            "name": normalized,
            "nth": nth,
            **_dom_tree_node_id_data(node),
        }
        refs[ref] = ref_data
        escaped = normalized.replace('"', '\\"')
        suffix = f" [ref={ref}]"
        if nth is not None and nth > 0:
            suffix += f" [nth={nth}]"
        lines.append(f'- {role} "{escaped}"{suffix}')
        return True

    def visit(node: dict[str, Any]) -> None:
        if len(lines) >= _DOM_TREE_MAX_LINES:
            return
        node_name = str(node.get("nodeName") or "").lower()
        if node_name in _DOM_TREE_SKIPPED_NODES:
            return

        node_type = node.get("nodeType")
        if node_type == 3 or node_name == "#text":
            append_line(node.get("nodeValue"))

        attributes = _dom_tree_attributes(node.get("attributes"))
        role = _dom_tree_interactive_role(node_name, attributes)
        if role is not None and append_interactive_line(
            role,
            _dom_tree_collect_text(node),
            node,
        ):
            return

        for attr_name in _DOM_TREE_TEXT_ATTRIBUTES:
            append_line(attributes.get(attr_name))

        for key in ("children", "shadowRoots", "pseudoElements"):
            children = node.get(key)
            if not isinstance(children, list):
                continue
            for child in children:
                if isinstance(child, dict):
                    visit(child)
                if len(lines) >= _DOM_TREE_MAX_LINES:
                    return

        content_document = node.get("contentDocument")
        if isinstance(content_document, dict):
            visit(content_document)

    visit(root)
    if not lines:
        return "(empty)", {}
    _remove_nth_from_non_duplicates(refs, tracker)
    return "\n".join(lines), refs


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

    truncated = False

    def can_add_content_line() -> bool:
        return len(lines) < max(_AX_TREE_MAX_LINES - 1, 1)

    def mark_truncated() -> None:
        nonlocal truncated
        truncated = True

    def visit_children(node: dict[str, Any], depth: int) -> None:
        if truncated:
            return
        for child_id in node.get("childIds", []) or []:
            child = by_id.get(str(child_id))
            if child is not None:
                visit(child, depth)
            if truncated:
                return

    def visit(node: dict[str, Any], depth: int) -> None:
        if truncated:
            return
        if node.get("ignored"):
            visit_children(node, depth)
            return

        role_raw = _ax_value(node.get("role"))
        if not role_raw:
            visit_children(node, depth)
            return
        role = role_raw.lower()
        name = _normalize_ax_text(_ax_value(node.get("name")))

        if role in _AX_TREE_REDUNDANT_ROLES:
            visit_children(node, depth)
            return

        is_interactive = role in INTERACTIVE_ROLES
        is_content = role in CONTENT_ROLES
        should_have_ref = is_interactive or (is_content and name)
        should_emit = not (
            role in STRUCTURAL_ROLES and not name and not should_have_ref
        )

        child_depth = depth
        if should_emit:
            if not can_add_content_line():
                mark_truncated()
                return

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
            child_depth = depth + 1
        visit_children(node, child_depth)

    for root in roots:
        visit(root, 0)
        if truncated:
            break

    _remove_nth_from_non_duplicates(refs, tracker)
    if truncated:
        lines.append(
            '- note "Snapshot truncated; use visible refs, page search, '
            'or a narrower route instead of reading offloaded files."',
        )
    return "\n".join(lines) or "(empty)", refs


__all__ = [
    "INTERACTIVE_ROLES",
    "from_cdp_ax_tree",
    "from_cdp_dom_tree",
    "from_cdp_dom_snapshot",
]
