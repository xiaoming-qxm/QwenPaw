# -*- coding: utf-8 -*-
"""Generate Browser SDK public API catalog artifacts."""
# pylint: disable=unused-argument,redefined-builtin,too-many-return-statements

from __future__ import annotations

import argparse
import inspect
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, NoReturn, get_args, get_origin, get_type_hints

from ..contracts import BrowserAPIContract
from ..contracts import BrowserTargetContract
from ..contracts import browser_api
from ..primitives.types import BrowserActionResult
from ..primitives.types import BrowserDiagnostics
from ..primitives.types import BrowserExtractionResult
from ..primitives.types import BrowserObservation
from ..primitives.types import BrowserPageInfo
from ..primitives.types import BrowserScreenshot


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "generated" / "api_catalog.json"
)
GENERATED_DIR = Path(__file__).resolve().parents[1] / "generated"
CAPABILITIES_PATH = GENERATED_DIR / "capabilities.json"
HELP_INDEX_PATH = GENERATED_DIR / "help" / "index.md"

_REQUIRED_TARGET = BrowserTargetContract(
    required=True,
    methods=("ref", "role_name", "text_exact", "coords"),
    snapshot_bound=True,
)
_OPTIONAL_TARGET = BrowserTargetContract(
    required=False,
    methods=("ref", "role_name", "text_exact", "coords"),
    snapshot_bound=True,
)


def _catalog_seed() -> NoReturn:
    raise NotImplementedError(
        "Browser API catalog seed callables are not run.",
    )


@browser_api(
    public_name="browser.connect",
    kind="lifecycle",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
)
async def _seed_browser_connect(
    context: str = "auto",
    *,
    requires_user_state: bool | None = None,
    session_id: str | None = None,
    retention: str = "clean",
) -> Any:
    """Connect to a browser backend using runtime context arbitration."""
    _catalog_seed()


@browser_api(
    public_name="browser.capabilities",
    kind="diagnostic",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
)
def _seed_browser_capabilities(scope: str = "all") -> dict[str, Any]:
    """Return generated Browser SDK capabilities."""
    _catalog_seed()


@browser_api(
    public_name="browser.help",
    kind="diagnostic",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
)
def _seed_browser_help(
    scope: str | None = None,
    api_id: str | None = None,
) -> str:
    """Return generated Browser SDK help text."""
    _catalog_seed()


@browser_api(
    public_name="browser.diagnostics",
    kind="diagnostic",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
)
async def _seed_browser_diagnostics(
    context: str = "auto",
) -> BrowserDiagnostics:
    """Return backend availability diagnostics without connecting."""
    _catalog_seed()


@browser_api(
    public_name="browser.close",
    kind="lifecycle",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
)
async def _seed_browser_close() -> None:
    """Release browser session resources through the selected backend."""
    _catalog_seed()


@browser_api(
    public_name="browser.tabs.open",
    kind="primitive",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="open_workspace_tab",
)
async def _seed_tabs_open(url: str) -> Any:
    """Reuse the request workspace tab and navigate it to a URL."""
    _catalog_seed()


@browser_api(
    public_name="browser.tabs.new",
    kind="primitive",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="create_tab",
)
async def _seed_tabs_new(url: str) -> Any:
    """Explicitly create a new browser tab for the request workspace."""
    _catalog_seed()


@browser_api(
    public_name="browser.tabs.active",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="active_tab",
)
async def _seed_tabs_active() -> Any:
    """Return the current request tab without creating one."""
    _catalog_seed()


@browser_api(
    public_name="browser.tabs.list",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="list_tabs",
)
async def _seed_tabs_list() -> list[Any]:
    """List browser tabs."""
    _catalog_seed()


@browser_api(
    public_name="browser.tabs.select",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="select_tab",
)
async def _seed_tabs_select(tab_id: str) -> Any:
    """Select a tab by id."""
    _catalog_seed()


@browser_api(
    public_name="tab.snapshot",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=True,
    invalidates_observation=False,
    backend_op="snapshot",
)
async def _seed_tab_snapshot() -> BrowserObservation:
    """Observe the tab and satisfy the fresh-observation guard."""
    _catalog_seed()


@browser_api(
    public_name="tab.screenshot",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=True,
    invalidates_observation=False,
    backend_op="screenshot",
)
async def _seed_tab_screenshot() -> BrowserScreenshot:
    """Capture a visual observation and satisfy the guard."""
    _catalog_seed()


@browser_api(
    public_name="tab.page_info",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="page_info",
)
async def _seed_tab_page_info() -> BrowserPageInfo:
    """Read tab metadata without satisfying the observation guard."""
    _catalog_seed()


@browser_api(
    public_name="tab.extract",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="extract",
)
async def _seed_tab_extract(
    instruction: str,
    format: Literal["text", "json"] = "text",
) -> BrowserExtractionResult:
    """Extract page data according to an instruction."""
    _catalog_seed()


@browser_api(
    public_name="tab.wait_for",
    kind="primitive",
    visibility="default",
    mutates=False,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="wait_for",
)
async def _seed_tab_wait_for(
    condition: dict[str, Any] | str,
    timeout_ms: int = 10000,
) -> BrowserActionResult:
    """Wait until the page matches a structured condition."""
    _catalog_seed()


@browser_api(
    public_name="tab.close",
    kind="primitive",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=False,
    backend_op="close_tab",
)
async def _seed_tab_close() -> BrowserActionResult:
    """Close or release the tab through the backend."""
    _catalog_seed()


@browser_api(
    public_name="browser.actions.search_web",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
)
async def _seed_browser_actions_search_web(
    query: str,
    engine: str = "google",
) -> BrowserActionResult:
    """Search the public web using a supported engine."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.navigate",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="navigate",
)
async def _seed_tab_actions_navigate(url: str) -> BrowserActionResult:
    """Navigate the tab to a URL."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.back",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="back",
)
async def _seed_tab_actions_back() -> BrowserActionResult:
    """Navigate the tab backward in history."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.forward",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="forward",
)
async def _seed_tab_actions_forward() -> BrowserActionResult:
    """Navigate the tab forward in history."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.reload",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="reload",
)
async def _seed_tab_actions_reload() -> BrowserActionResult:
    """Reload the current tab."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.click",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=True,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_REQUIRED_TARGET,
    backend_op="click",
)
async def _seed_tab_actions_click(
    target: dict[str, Any],
    allow_new_context: bool = False,
) -> BrowserActionResult:
    """Click one target from the latest observation."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.fill",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=True,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_REQUIRED_TARGET,
    backend_op="fill",
)
async def _seed_tab_actions_fill(
    target: dict[str, Any],
    text: str,
) -> BrowserActionResult:
    """Fill an editable target with text."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.press_key",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="press_key",
)
async def _seed_tab_actions_press_key(key: str) -> BrowserActionResult:
    """Press a page-level keyboard key."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.scroll",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_OPTIONAL_TARGET,
    backend_op="scroll",
)
async def _seed_tab_actions_scroll(
    direction: str = "down",
    amount: str | int | None = None,
    target: dict[str, Any] | None = None,
) -> BrowserActionResult:
    """Scroll the page or a target region."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.select_option",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=True,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_REQUIRED_TARGET,
    backend_op="select_option",
)
async def _seed_tab_actions_select_option(
    target: dict[str, Any],
    value: str,
) -> BrowserActionResult:
    """Select an option on a target control."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.upload_file",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=True,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_REQUIRED_TARGET,
    backend_op="upload_file",
)
async def _seed_tab_actions_upload_file(
    target: dict[str, Any],
    file_path: str | list[str],
) -> BrowserActionResult:
    """Upload one or more files through a target control."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.download_file",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_OPTIONAL_TARGET,
    backend_op="download_file",
)
async def _seed_tab_actions_download_file(
    target: dict[str, Any] | None = None,
    timeout_ms: int = 30000,
) -> BrowserActionResult:
    """Download a file from the page."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.handle_dialog",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=False,
    satisfies_observation=False,
    invalidates_observation=True,
    backend_op="handle_dialog",
)
async def _seed_tab_actions_handle_dialog(
    accept: bool = True,
    prompt_text: str | None = None,
) -> BrowserActionResult:
    """Handle a browser dialog."""
    _catalog_seed()


@browser_api(
    public_name="tab.actions.hover",
    kind="action",
    visibility="default",
    mutates=True,
    requires_observation=True,
    satisfies_observation=False,
    invalidates_observation=True,
    target=_REQUIRED_TARGET,
    backend_op="hover",
)
async def _seed_tab_actions_hover(
    target: dict[str, Any],
) -> BrowserActionResult:
    """Hover over one target from the latest observation."""
    _catalog_seed()


_SEED_APIS: tuple[Callable[..., Any], ...] = (
    _seed_browser_connect,
    _seed_browser_capabilities,
    _seed_browser_help,
    _seed_browser_diagnostics,
    _seed_browser_close,
    _seed_tabs_open,
    _seed_tabs_new,
    _seed_tabs_active,
    _seed_tabs_list,
    _seed_tabs_select,
    _seed_tab_snapshot,
    _seed_tab_screenshot,
    _seed_tab_page_info,
    _seed_tab_extract,
    _seed_tab_wait_for,
    _seed_tab_close,
    _seed_browser_actions_search_web,
    _seed_tab_actions_navigate,
    _seed_tab_actions_back,
    _seed_tab_actions_forward,
    _seed_tab_actions_reload,
    _seed_tab_actions_click,
    _seed_tab_actions_fill,
    _seed_tab_actions_press_key,
    _seed_tab_actions_scroll,
    _seed_tab_actions_select_option,
    _seed_tab_actions_upload_file,
    _seed_tab_actions_download_file,
    _seed_tab_actions_handle_dialog,
    _seed_tab_actions_hover,
)


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
