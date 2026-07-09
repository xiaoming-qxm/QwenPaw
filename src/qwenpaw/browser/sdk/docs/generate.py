# -*- coding: utf-8 -*-
"""Generate Browser SDK public API catalog artifacts."""
# pylint: disable=unused-argument,redefined-builtin,too-many-return-statements

from __future__ import annotations

import argparse
import inspect
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from ..contracts import BrowserAPIContract


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "generated" / "api_catalog.json"
)
GENERATED_DIR = Path(__file__).resolve().parents[1] / "generated"
CAPABILITIES_PATH = GENERATED_DIR / "capabilities.json"
HELP_INDEX_PATH = GENERATED_DIR / "help" / "index.md"


def build_api_catalog() -> dict[str, Any]:
    """Build the public API catalog payload from real public methods."""
    return {
        "version": 1,
        "source": "browser_api",
        "apis": [
            _api_catalog_entry(func)
            for func in sorted(
                _real_public_api_callables(),
                key=lambda item: _contract_for(item).api_id,
            )
        ],
    }


def write_api_catalog(path: Path = CATALOG_PATH) -> None:
    """Write the generated API catalog artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_catalog_text(), encoding="utf-8")


def check_api_catalog(path: Path = CATALOG_PATH) -> bool:
    """Return whether the committed API catalog matches regenerated content."""
    if not path.exists():
        return False
    return path.read_text(encoding="utf-8") == _catalog_text()


def build_capabilities() -> dict[str, Any]:
    """Build compact machine-readable capabilities from the API catalog."""
    apis = build_api_catalog()["apis"]
    compact = {api["api_id"]: _compact_api_entry(api) for api in apis}
    scopes = {
        "all": sorted(compact),
        "actions": _ids_for_kind(apis, "action"),
        "primitives": _ids_for_kind(apis, "primitive"),
        "diagnostics": _ids_for_kind(apis, "diagnostic"),
        "lifecycle": _ids_for_kind(apis, "lifecycle"),
    }
    return {
        "version": 1,
        "source": "api_catalog.json",
        "contexts": ["auto", "user", "isolated"],
        "scopes": scopes,
        "apis": compact,
        "actions": _entries_for_ids(compact, scopes["actions"]),
        "primitives": _entries_for_ids(compact, scopes["primitives"]),
        "diagnostics": _entries_for_ids(compact, scopes["diagnostics"]),
        "lifecycle": _entries_for_ids(compact, scopes["lifecycle"]),
        "help": build_help_payload(compact=compact, scopes=scopes),
    }


def build_help_payload(
    *,
    compact: dict[str, Any] | None = None,
    scopes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build generated help text from compact capabilities."""
    if compact is None or scopes is None:
        capabilities = build_capabilities()
        if compact is None:
            compact = capabilities["apis"]
        if scopes is None:
            scopes = capabilities["scopes"]
    scope_help = {
        scope: _scope_help(scope, [compact[api_id] for api_id in api_ids])
        for scope, api_ids in scopes.items()
        if scope != "all"
    }
    api_help = {
        api_id: _api_help(entry) for api_id, entry in sorted(compact.items())
    }
    index = _index_help(compact, scopes)
    return {
        "index": index,
        "scopes": scope_help,
        "apis": api_help,
    }


def write_generated_artifacts(output_dir: Path = GENERATED_DIR) -> None:
    """Write the generated catalog, capabilities, and help artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "api_catalog.json").write_text(
        _json_text(build_api_catalog()),
        encoding="utf-8",
    )
    (output_dir / "capabilities.json").write_text(
        _json_text(build_capabilities()),
        encoding="utf-8",
    )
    help_dir = output_dir / "help"
    help_dir.mkdir(parents=True, exist_ok=True)
    (help_dir / "index.md").write_text(
        build_help_payload()["index"],
        encoding="utf-8",
    )


def check_generated_artifacts(output_dir: Path = GENERATED_DIR) -> bool:
    """Return whether all generated artifacts match regenerated content."""
    expected = {
        output_dir / "api_catalog.json": _json_text(build_api_catalog()),
        output_dir / "capabilities.json": _json_text(build_capabilities()),
        output_dir / "help" / "index.md": build_help_payload()["index"],
    }
    for path, content in expected.items():
        if not path.exists():
            return False
        if path.read_text(encoding="utf-8") != content:
            return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run the catalog generator command."""
    parser = argparse.ArgumentParser(
        description="Generate Browser SDK API catalog artifacts.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if generated artifacts differ from committed files",
    )
    args = parser.parse_args(argv)
    if args.check:
        return 0 if check_generated_artifacts() else 1
    write_generated_artifacts()
    return 0


def _api_catalog_entry(func: Callable[..., Any]) -> dict[str, Any]:
    contract = _contract_for(func)
    hints = _type_hints_for(func)
    parameters = _parameters_for(func, hints)
    return_type = _format_annotation(hints.get("return", Any))
    entry = {
        **contract.as_dict(),
        "callable_path": _callable_path_for(func),
        "signature": _format_signature(func, parameters, return_type),
        "parameters": parameters,
        "return_type": return_type,
        "summary": _summary_for(func),
    }
    entry.pop("backend_op", None)
    return entry


def _contract_for(func: Callable[..., Any]) -> BrowserAPIContract:
    contract = getattr(func, "__browser_api_contract__", None)
    if not isinstance(contract, BrowserAPIContract):
        raise TypeError(f"Missing Browser API contract for {func!r}")
    return contract


def _compact_api_entry(api: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "api_id": api["api_id"],
        "kind": api["kind"],
        "summary": api["summary"],
        "callable_path": api["callable_path"],
        "signature": api["signature"],
        "parameters": api["parameters"],
        "return_type": api["return_type"],
        "mutates": api["mutates"],
        "requires_observation": api["requires_observation"],
        "satisfies_observation": api["satisfies_observation"],
        "invalidates_observation": api["invalidates_observation"],
    }
    for key in ("target", "backend_op"):
        if key in api:
            entry[key] = api[key]
    return entry


def _ids_for_kind(apis: list[dict[str, Any]], kind: str) -> list[str]:
    return sorted(
        api["api_id"]
        for api in apis
        if api["kind"] == kind and api["visibility"] == "default"
    )


def _entries_for_ids(
    compact: dict[str, Any],
    api_ids: list[str],
) -> dict[str, Any]:
    return {api_id: compact[api_id] for api_id in api_ids}


def _index_help(
    compact: dict[str, Any],
    scopes: dict[str, list[str]],
) -> str:
    lines = [
        "# Browser SDK Generated Help",
        "",
        "Generated from `api_catalog.json`.",
        "",
        'Use `Browser.capabilities(scope="actions")` for compact indexes.',
        'Use `Browser.help(api_id="tab.actions.click")` for one API.',
        "",
    ]
    for scope in ("actions", "primitives", "diagnostics", "lifecycle"):
        lines.append(f"## {scope.title()}")
        lines.append("")
        for api_id in scopes[scope]:
            entry = compact[api_id]
            summary = entry["summary"]
            if summary:
                lines.append(f"- `{api_id}` - {summary}")
            else:
                lines.append(f"- `{api_id}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _scope_help(scope: str, entries: list[dict[str, Any]]) -> str:
    lines = [
        f"# Browser SDK {scope.title()}",
        "",
        "Generated from `api_catalog.json`.",
        "",
    ]
    for entry in entries:
        lines.append(f"## `{entry['api_id']}`")
        lines.append("")
        lines.append(entry["summary"])
        lines.append("")
        lines.append(f"Signature: `{entry['signature']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _api_help(entry: dict[str, Any]) -> str:
    lines = [
        f"# `{entry['api_id']}`",
        "",
        entry["summary"],
        "",
        f"Kind: `{entry['kind']}`",
        f"Signature: `{entry['signature']}`",
        "",
        "Metadata:",
        f"- mutates: `{entry['mutates']}`",
        f"- requires_observation: `{entry['requires_observation']}`",
        f"- satisfies_observation: `{entry['satisfies_observation']}`",
        f"- invalidates_observation: `{entry['invalidates_observation']}`",
    ]
    if "target" in entry:
        target = entry["target"]
        methods = ", ".join(target["methods"])
        lines.extend(
            [
                f"- target_required: `{target['required']}`",
                f"- target_methods: `{methods}`",
                f"- target_snapshot_bound: `{target['snapshot_bound']}`",
            ],
        )
    if "backend_op" in entry:
        lines.append(f"- backend_op: `{entry['backend_op']}`")
    return "\n".join(lines).rstrip() + "\n"


def _parameters_for(
    func: Callable[..., Any],
    hints: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    signature = inspect.signature(func)
    parameters: dict[str, dict[str, Any]] = {}
    for name, parameter in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        payload = {
            "kind": parameter.kind.name.lower(),
            "annotation": _format_annotation(hints.get(name, Any)),
            "required": parameter.default is inspect.Signature.empty,
        }
        if parameter.default is not inspect.Signature.empty:
            payload["default"] = repr(parameter.default)
        parameters[name] = payload
    return parameters


def _format_signature(
    func: Callable[..., Any],
    parameters: dict[str, dict[str, Any]],
    return_type: str,
) -> str:
    signature = inspect.signature(func)
    formatted: list[str] = []
    inserted_kw_separator = False
    for name, parameter in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        if (
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            and not inserted_kw_separator
        ):
            formatted.append("*")
            inserted_kw_separator = True
        part = f"{name}: {parameters[name]['annotation']}"
        if "default" in parameters[name]:
            part = f"{part} = {parameters[name]['default']}"
        formatted.append(part)
    return f"({', '.join(formatted)}) -> {return_type}"


def _format_annotation(annotation: Any) -> str:
    if annotation is Any:
        return "Any"
    if annotation is type(None):
        return "None"
    origin = get_origin(annotation)
    if origin is None:
        name = getattr(annotation, "__name__", None)
        if name:
            return str(name)
        return str(annotation).replace("typing.", "")
    if origin is Literal:
        return (
            "Literal["
            + ", ".join(repr(arg) for arg in get_args(annotation))
            + "]"
        )
    args = get_args(annotation)
    if origin is list:
        return f"list[{_format_annotation(args[0])}]"
    if origin is dict:
        key, value = args
        return f"dict[{_format_annotation(key)}, {_format_annotation(value)}]"
    if origin is tuple:
        return (
            "tuple[" + ", ".join(_format_annotation(arg) for arg in args) + "]"
        )
    if origin is Callable:
        return "Callable"
    if str(origin) in {"typing.Union", "types.UnionType"} or args:
        return " | ".join(_format_annotation(arg) for arg in args)
    return str(annotation).replace("typing.", "")


def _summary_for(func: Callable[..., Any]) -> str:
    docstring = inspect.getdoc(func) or ""
    if not docstring:
        return ""
    first_line = docstring.strip().splitlines()[0].strip()
    if "." not in first_line:
        return first_line
    return first_line.split(".", 1)[0].strip() + "."


def _real_public_api_callables() -> tuple[Callable[..., Any], ...]:
    from ..actions.tab_actions import BrowserActions
    from ..actions.tab_actions import TabActions
    from ..facade.browser import Browser
    from ..primitives.tab import Tab
    from ..primitives.tabs import BrowserTabs

    return (
        Browser.connect,
        Browser.capabilities,
        Browser.help,
        Browser.diagnostics,
        Browser.close,
        BrowserTabs.open,
        BrowserTabs.new,
        BrowserTabs.active,
        BrowserTabs.list,
        BrowserTabs.select,
        Tab.snapshot,
        Tab.screenshot,
        Tab.page_info,
        Tab.extract,
        Tab.wait_for,
        Tab.close,
        BrowserActions.search_web,
        TabActions.navigate,
        TabActions.back,
        TabActions.forward,
        TabActions.reload,
        TabActions.click,
        TabActions.fill,
        TabActions.press_key,
        TabActions.scroll,
        TabActions.select_option,
        TabActions.upload_file,
        TabActions.download_file,
        TabActions.handle_dialog,
        TabActions.hover,
    )


def _callable_path_for(func: Callable[..., Any]) -> str:
    raw_func = _introspection_callable(func)
    return f"{raw_func.__module__}:{raw_func.__qualname__}"


def _type_hints_for(func: Callable[..., Any]) -> dict[str, Any]:
    return get_type_hints(_introspection_callable(func))


def _introspection_callable(func: Callable[..., Any]) -> Callable[..., Any]:
    return getattr(func, "__func__", func)


def _catalog_text() -> str:
    return _json_text(build_api_catalog())


def _json_text(payload: dict[str, Any]) -> str:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPABILITIES_PATH",
    "CATALOG_PATH",
    "GENERATED_DIR",
    "HELP_INDEX_PATH",
    "build_api_catalog",
    "build_capabilities",
    "build_help_payload",
    "check_api_catalog",
    "check_generated_artifacts",
    "main",
    "write_generated_artifacts",
    "write_api_catalog",
]
