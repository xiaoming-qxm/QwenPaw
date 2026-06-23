# -*- coding: utf-8 -*-
"""JSON-RPC stdio worker for Local Vision."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_engine_class():
    try:
        from .engine import VisionEngine

        return VisionEngine
    except ImportError:
        engine_path = Path(__file__).resolve().parent / "engine.py"
        spec = importlib.util.spec_from_file_location(
            "local_vision_worker_engine",
            engine_path,
        )
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        sys.modules["local_vision_worker_engine"] = module
        spec.loader.exec_module(module)
        return module.VisionEngine


async def handle_request(
    engine: Any,
    request: dict[str, Any],
) -> dict[str, Any]:
    request_id = request.get("id")
    method = str(request.get("method") or "")
    params = request.get("params") or {}
    try:
        if method == "parse":
            result = await engine.parse(**params)
            return {"id": request_id, "result": result}
        if method == "health":
            return {"id": request_id, "result": engine.health()}
        if method == "shutdown":
            return {"id": request_id, "result": "ok"}
        return {
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Unknown method: {method}",
            },
        }
    except Exception as exc:
        return {
            "id": request_id,
            "error": {"code": -1, "message": str(exc)},
        }


def _write_json(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def _run() -> None:
    engine_cls = _load_engine_class()
    engine = engine_cls()
    await engine.load()
    _write_json(
        {
            "ready": True,
            "model": engine.model_id,
            "device": engine.device,
        },
    )
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            return
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_json(
                {
                    "id": None,
                    "error": {"code": -32700, "message": str(exc)},
                },
            )
            continue
        response = await handle_request(engine, request)
        _write_json(response)
        if request.get("method") == "shutdown":
            return


def main() -> None:
    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"Local Vision worker failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
