# -*- coding: utf-8 -*-
"""DashScope provider using agentscope 2.0 native ``DashScopeChatModel``.

Most surface area (connection check, model listing, multimodal probe) is
reused from :class:`OpenAIProvider` because DashScope's
``compatible-mode/v1`` endpoint speaks OpenAI HTTP.  Only
:meth:`get_chat_model_instance` is overridden to construct the native 2.0
``DashScopeChatModel(credential=DashScopeCredential(...), ...)`` instead
of the OpenAI-compat wrapper.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Dict

from agentscope.model import ChatModelBase
from pydantic import Field

from .openai_provider import (
    CODING_DASHSCOPE_BASE_URL,
    DASHSCOPE_BASE_URLS,
    TOKEN_PLAN_BASE_URL,
    OpenAIProvider,
)

logger = logging.getLogger(__name__)


def _clone_with_overrides(obj: Any, **overrides: Any) -> Any:
    """Clone an SDK stream object into a mutable namespace."""
    data = dict(getattr(obj, "__dict__", {}))
    data.update(overrides)
    return SimpleNamespace(**data)


def _stringify_tool_arguments(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


class _DashScopeToolCallStreamCompat:
    """Normalize partial DashScope tool-call deltas before AgentScope parses.

    DashScope can stream function-call chunks whose ``function.name`` is
    temporarily ``None``.  AgentScope's native parser constructs
    ``ToolCallBlock`` immediately for each delta, so those partial chunks
    otherwise crash the whole response stream.  This wrapper preserves
    recoverable arguments until a name appears, and reuses a known name for
    later argument-only chunks.
    """

    def __init__(self, response: Any):
        self._response = response
        self._ctx_stream: Any | None = None
        self._names: dict[Any, str] = {}
        self._ids: dict[Any, str] = {}
        self._pending_args: dict[Any, str] = {}

    async def __aenter__(self) -> "_DashScopeToolCallStreamCompat":
        self._ctx_stream = await self._response.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> bool | None:
        return await self._response.__aexit__(exc_type, exc, tb)

    def __aiter__(self) -> "_DashScopeToolCallStreamCompat":
        return self

    async def __anext__(self) -> Any:
        if self._ctx_stream is None:
            raise StopAsyncIteration
        chunk = await self._ctx_stream.__anext__()
        return self._normalize_chunk(chunk)

    def _normalize_chunk(self, chunk: Any) -> Any:
        choices = getattr(chunk, "choices", None)
        if not choices:
            return chunk

        sanitized_choices: list[Any] = []
        changed = False
        for choice in choices:
            sanitized_choice = self._normalize_choice(choice)
            if sanitized_choice is not choice:
                changed = True
            sanitized_choices.append(sanitized_choice)

        if not changed:
            return chunk
        return _clone_with_overrides(chunk, choices=sanitized_choices)

    def _normalize_choice(self, choice: Any) -> Any:
        delta = getattr(choice, "delta", None)
        if delta is None:
            return choice

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if not raw_tool_calls:
            return choice

        sanitized_calls: list[Any] = []
        changed = False
        for fallback_index, tool_call in enumerate(raw_tool_calls):
            sanitized = self._normalize_tool_call(
                tool_call,
                fallback_index,
            )
            if sanitized is not tool_call:
                changed = True
            if sanitized is not None:
                sanitized_calls.append(sanitized)

        if not changed:
            return choice
        sanitized_delta = _clone_with_overrides(
            delta,
            tool_calls=sanitized_calls,
        )
        return _clone_with_overrides(choice, delta=sanitized_delta)

    def _normalize_tool_call(
        self,
        tool_call: Any,
        fallback_index: int,
    ) -> Any | None:
        idx = getattr(tool_call, "index", None)
        if idx is None:
            idx = fallback_index

        raw_id = getattr(tool_call, "id", None)
        if isinstance(raw_id, str) and raw_id:
            self._ids[idx] = raw_id

        function = getattr(tool_call, "function", None)
        if function is None:
            return None

        args = _stringify_tool_arguments(
            getattr(function, "arguments", ""),
        )
        raw_name = getattr(function, "name", None)

        name = ""
        if isinstance(raw_name, str) and raw_name:
            name = raw_name
            self._names[idx] = name
        elif raw_name not in (None, ""):
            name = str(raw_name)
            self._names[idx] = name
        else:
            name = self._names.get(idx, "")

        pending = self._pending_args.pop(idx, "")
        if pending:
            args = pending + args

        if not name:
            if args:
                previous_args = self._pending_args.get(idx, "")
                self._pending_args[idx] = f"{previous_args}{args}"
            return None

        safe_function = SimpleNamespace(name=name, arguments=args)
        safe_id = raw_id
        if not isinstance(safe_id, str):
            safe_id = self._ids.get(idx, "")
        return _clone_with_overrides(
            tool_call,
            id=safe_id,
            index=idx,
            function=safe_function,
        )


class DashScopeProvider(OpenAIProvider):
    """Provider that wires the builtin DashScope endpoint to 2.0 native
    ``DashScopeChatModel``."""

    chat_model: str = Field(default="DashScopeChatModel")

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        from agentscope.credential import DashScopeCredential
        from agentscope.model import DashScopeChatModel

        if not self.api_key:
            from qwenpaw.exceptions import ProviderError

            provider_name = f"DashScope provider '{self.id}'"
            raise ProviderError(
                message=f"{provider_name} has no api_key configured.",
            )

        credential = DashScopeCredential(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        effective = self.get_effective_generate_kwargs(model_id)
        param_kwargs: Dict[str, Any] = {}
        for key in (
            "max_tokens",
            "thinking_enable",
            "thinking_budget",
            "temperature",
            "top_p",
            "top_k",
            "parallel_tool_calls",
        ):
            if key in effective:
                param_kwargs[key] = effective[key]

        merged_headers = self._build_default_headers()
        dashscope_meta = json.dumps(
            {
                "agentType": "QwenPaw",
                "deployType": "UnKnown",
                "moduleCode": "model",
                "agentCode": "UnKnown",
            },
            ensure_ascii=False,
        )
        if self.base_url in DASHSCOPE_BASE_URLS:
            merged_headers["x-dashscope-agentapp"] = dashscope_meta
        elif self.base_url in (
            CODING_DASHSCOPE_BASE_URL,
            TOKEN_PLAN_BASE_URL,
        ):
            merged_headers["X-DashScope-Cdpl"] = dashscope_meta

        return _DashScopeChatModelCompat(
            credential=credential,
            model=model_id,
            parameters=DashScopeChatModel.Parameters(**param_kwargs),
            stream=True,
            default_headers=merged_headers or None,
            context_size=self._get_context_size(model_id),
        )


class _DashScopeChatModelCompat:
    """Factory that creates a ``DashScopeChatModel`` subclass with custom
    tracking headers injected into every API call via ``extra_headers``."""

    def __new__(cls, **kwargs: Any) -> Any:
        from agentscope.model import DashScopeChatModel

        default_headers = kwargs.pop("default_headers", None)

        class _Compat(DashScopeChatModel):
            _qp_default_headers = default_headers

            async def _call_api(
                self,
                model_name,
                messages,
                tools=None,
                tool_choice=None,
                **extra_kwargs,
            ):
                if self._qp_default_headers:
                    existing = extra_kwargs.get("extra_headers") or {}
                    extra_kwargs["extra_headers"] = {
                        **self._qp_default_headers,
                        **existing,
                    }
                response = await super()._call_api(
                    model_name,
                    messages,
                    tools,
                    tool_choice,
                    **extra_kwargs,
                )
                if hasattr(response, "__aenter__") and hasattr(
                    response,
                    "__aiter__",
                ):
                    return _DashScopeToolCallStreamCompat(response)
                return response

        return _Compat(**kwargs)
