"""TomTom ComfyUI Canvas Bridge.

This custom node package exposes a tiny local HTTP endpoint and a frontend
extension. The frontend reads the open ComfyUI canvas and posts snapshots here;
the endpoint writes those snapshots to the MCP bridge state JSON file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from server import PromptServer


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

BRIDGE_STATE_ENV = "COMFY_MCP_CANVAS_BRIDGE_STATE"
BRIDGE_STATE_ENV_LEGACY = "TOMTOM_CANVAS_BRIDGE_FILE"
DEFAULT_BRIDGE_RELATIVE = Path("Documents") / "ComfyUI" / "user" / "default" / "workflows" / ".tomtom_canvas_bridge.json"


def _bridge_state_path() -> Path:
    configured = os.environ.get(BRIDGE_STATE_ENV) or os.environ.get(BRIDGE_STATE_ENV_LEGACY)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / DEFAULT_BRIDGE_RELATIVE).resolve()


def _json_default(value: Any) -> str:
    return str(value)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _safe_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="Canvas bridge payload must be a JSON object")

    payload = dict(payload)
    payload.setdefault("bridge_version", "0.1")
    payload.setdefault("source", "tomtom_comfyui_frontend_bridge")
    payload["server_received_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    workflow = payload.get("workflow")
    if workflow is not None and not isinstance(workflow, dict):
        raise web.HTTPBadRequest(text="Canvas bridge field 'workflow' must be an object")

    return payload


@PromptServer.instance.routes.post("/tomtom_canvas_bridge/state")
async def update_canvas_bridge_state(request: web.Request) -> web.Response:
    payload = _safe_payload(await request.json())
    bridge_path = _bridge_state_path()
    _atomic_write_json(bridge_path, payload)
    return web.json_response(
        {
            "ok": True,
            "bridge_path": str(bridge_path),
            "revision": payload.get("revision"),
            "node_count": len(payload.get("workflow") or {}),
        }
    )


@PromptServer.instance.routes.get("/tomtom_canvas_bridge/state")
async def read_canvas_bridge_state(_: web.Request) -> web.Response:
    bridge_path = _bridge_state_path()
    if not bridge_path.exists():
        return web.json_response(
            {
                "ok": False,
                "bridge_path": str(bridge_path),
                "error": "bridge state file does not exist yet",
            },
            status=404,
        )
    return web.json_response(json.loads(bridge_path.read_text(encoding="utf-8")))
