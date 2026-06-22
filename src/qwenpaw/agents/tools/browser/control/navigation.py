# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Browser Control navigation scope helpers."""

from ..runtime import *
from .session_manager import *

def _control_tab_id(page_id: str, index: int = -1) -> int:
    if index >= 0:
        return index
    raw = (page_id or "").strip()
    if raw.startswith("tab_"):
        raw = raw[4:]
    if raw.isdigit():
        return int(raw)
    raise ValueError("control actions require page_id/tab id or index")


def _control_page_id_is_tab_id(page_id: str) -> bool:
    raw = (page_id or "").strip()
    if not raw or raw == "default":
        return False
    if raw.startswith("tab_"):
        raw = raw[4:]
    return raw.isdigit()


def _control_url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _control_site_domain(domain: str) -> str:
    domain = domain.lower().strip(".")
    if not domain or domain == "localhost":
        return domain
    parts = [part for part in domain.split(".") if part]
    if len(parts) <= 2:
        return domain
    if (
        len(parts) >= 3
        and len(parts[-1]) == 2
        and parts[-2] in {"ac", "co", "com", "edu", "gov", "net", "org"}
    ):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _control_navigation_domains(url: str) -> set[str]:
    domain = (urlparse(url).hostname or "").lower().strip(".")
    if not domain:
        return set()
    return {domain, _control_site_domain(domain)}


def _control_same_site(url_a: str, url_b: str) -> bool:
    domains_a = _control_navigation_domains(url_a)
    domains_b = _control_navigation_domains(url_b)
    return bool(domains_a and domains_b and domains_a.intersection(domains_b))


def _control_remember_approved_navigation(state: dict, url: str) -> None:
    domains = _control_navigation_domains(url)
    if not domains:
        return
    approved = state.setdefault("control_approved_domains", set())
    if not isinstance(approved, set):
        approved = set(approved or [])
        state["control_approved_domains"] = approved
    approved.update(domains)


def _control_sync_session_navigation_scope(
    state: dict,
    session: Any,
) -> None:
    approved = state.get("control_approved_domains") or set()
    if not approved:
        return
    domains = {str(domain) for domain in approved if domain}
    config = getattr(session, "permissions_config", None)
    approved_domains = getattr(config, "approved_domains", None)
    if isinstance(approved_domains, set):
        approved_domains.update(domains)
    session_approved_domains = getattr(session, "approved_domains", None)
    if isinstance(session_approved_domains, set):
        session_approved_domains.update(domains)




__all__ = [name for name in globals() if not name.startswith("__")]
