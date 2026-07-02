"""Read-only live canvas helpers for ComfyUI-visible workflow graphs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from managers.workflow_graph import WorkflowGraphInspector


BRIDGE_STATE_ENV = "COMFY_MCP_CANVAS_BRIDGE_STATE"
DEFAULT_BRIDGE_STATE_NAME = ".tomtom_canvas_bridge.json"


def current_canvas_state(workflow_manager, comfyui_client, include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> Dict[str, Any]:
    """Return the best available read-only canvas state.

    Priority:
    1. Optional bridge state written by a ComfyUI extension/browser bridge.
    2. Running or pending queue prompt graph from ComfyUI's HTTP API.
    3. Most recently saved workflow JSON.
    """
    bridge = bridge_canvas_state(workflow_manager, include_nodes=include_nodes)
    if bridge:
        return {
            "status": "success",
            "source": "canvas_bridge",
            "is_live_ui_canvas": True,
            "is_live_execution_graph": False,
            "message": "Read editor canvas state from the TomTom ComfyUI canvas bridge.",
            "canvases": [bridge],
        }

    try:
        queue_data = comfyui_client.get_queue()
        canvases = queue_canvas_states(queue_data, include_nodes=include_nodes)
    except Exception:
        queue_data = {}
        canvases = []

    if canvases:
        return {
            "status": "success",
            "source": "comfyui_queue",
            "is_live_ui_canvas": False,
            "is_live_execution_graph": True,
            "message": "Read live execution graph data from ComfyUI's running/pending queue.",
            "running_count": len(queue_data.get("queue_running", [])) if isinstance(queue_data, dict) else None,
            "pending_count": len(queue_data.get("queue_pending", [])) if isinstance(queue_data, dict) else None,
            "canvases": canvases,
        }

    if fallback_to_latest_saved:
        saved_canvas = latest_saved_canvas(workflow_manager, include_nodes=include_nodes)
        if saved_canvas:
            return {
                "status": "success",
                "source": "latest_saved_workflow",
                "is_live_ui_canvas": False,
                "is_live_execution_graph": False,
                "message": (
                    "No bridge or running prompt graph is available. "
                    "ComfyUI's normal HTTP API does not expose the unsaved editor canvas, "
                    "so this returns the most recently saved workflow."
                ),
                "canvases": [saved_canvas],
            }

    return {
        "status": "unavailable",
        "source": "none",
        "is_live_ui_canvas": False,
        "is_live_execution_graph": False,
        "message": (
            "No bridge state, queue graph, or saved workflow fallback was available. "
            "To inspect the unsaved editor canvas, install a ComfyUI frontend/plugin "
            "bridge that writes the TomTom canvas bridge state file."
        ),
        "canvases": [],
    }


def bridge_canvas_state(workflow_manager, include_nodes: bool = True) -> Optional[Dict[str, Any]]:
    """Read a bridge-authored canvas state file if present.

    The bridge file is intentionally simple JSON so a future ComfyUI extension,
    browser helper, or local frontend can publish the currently open canvas
    without this MCP server needing to control the UI.
    """
    bridge_path = _bridge_state_path(workflow_manager.workflows_dir)
    if not bridge_path.exists():
        return None

    try:
        state = json.loads(bridge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "source": "canvas_bridge",
            "bridge_path": str(bridge_path),
            "bridge_error": str(exc),
            "workflow_name": None,
            "workflow_id": None,
            "saved": None,
            "modified": None,
            "selected_node": None,
            "summary": {"node_count": 0, "edge_count": 0},
            "nodes": [] if include_nodes else None,
            "edges": [],
            "validation": {"valid": False, "warnings": ["Canvas bridge state could not be parsed."]},
        }

    workflow = _extract_bridge_workflow(state)
    graph = _graph_payload(workflow, include_nodes=include_nodes) if workflow else {
        "summary": {"node_count": 0, "edge_count": 0},
        "edges": [],
        "validation": {"valid": True, "warnings": []},
        "editable_parameters": [],
    }
    graph.update(
        {
            "source": "canvas_bridge",
            "bridge_path": str(bridge_path),
            "bridge_version": state.get("bridge_version"),
            "revision": state.get("revision"),
            "updated_at": state.get("updated_at"),
            "workflow_name": state.get("workflow_name") or state.get("name"),
            "workflow_id": state.get("workflow_id"),
            "saved": state.get("saved"),
            "modified": state.get("modified"),
            "selected_node": _selected_node_payload(state, workflow),
        }
    )
    return graph


def selected_node_state(workflow_manager) -> Dict[str, Any]:
    """Return the selected editor node from bridge state, if available."""
    bridge = bridge_canvas_state(workflow_manager, include_nodes=True)
    if not bridge:
        return {
            "status": "unavailable",
            "source": "none",
            "is_live_ui_canvas": False,
            "message": "No canvas bridge state is available, so selected node cannot be read yet.",
            "selected_node": None,
        }
    return {
        "status": "success",
        "source": "canvas_bridge",
        "is_live_ui_canvas": True,
        "workflow_id": bridge.get("workflow_id"),
        "workflow_name": bridge.get("workflow_name"),
        "selected_node": bridge.get("selected_node"),
    }


def execution_state(comfyui_client) -> Dict[str, Any]:
    """Return queue-oriented execution state from ComfyUI's public HTTP API."""
    queue_data = comfyui_client.get_queue()
    running = queue_data.get("queue_running", []) if isinstance(queue_data, dict) else []
    pending = queue_data.get("queue_pending", []) if isinstance(queue_data, dict) else []
    if running:
        state = "running"
    elif pending:
        state = "queued"
    else:
        state = "idle"
    return {
        "status": "success",
        "source": "comfyui_queue",
        "state": state,
        "running_count": len(running) if isinstance(running, list) else None,
        "pending_count": len(pending) if isinstance(pending, list) else None,
        "running": [_queue_item_preview(item) for item in running[:5]] if isinstance(running, list) else [],
        "pending": [_queue_item_preview(item) for item in pending[:5]] if isinstance(pending, list) else [],
    }


def canvas_event_subscription_info(workflow_manager) -> Dict[str, Any]:
    """Describe the current event bridge status.

    MCP tools are request/response here, so this returns a polling-friendly
    event cursor instead of opening a long-lived stream.
    """
    bridge = bridge_canvas_state(workflow_manager, include_nodes=False)
    bridge_path = _bridge_state_path(workflow_manager.workflows_dir)
    if not bridge:
        return {
            "status": "not_configured",
            "source": "none",
            "message": (
                "Canvas event subscription needs the TomTom ComfyUI bridge to write "
                "state updates. Poll get_current_canvas or refresh_canvas until the "
                "bridge extension is installed."
            ),
            "bridge_path": str(bridge_path),
            "poll_tools": ["get_current_canvas", "refresh_canvas"],
        }
    return {
        "status": "ready",
        "source": "canvas_bridge",
        "message": "Bridge state is available. Poll refresh_canvas and compare revision for updates.",
        "bridge_path": str(bridge_path),
        "revision": bridge.get("revision"),
        "updated_at": bridge.get("updated_at"),
        "poll_tools": ["refresh_canvas"],
    }


def queue_canvas_states(queue_data: Dict[str, Any], include_nodes: bool = True) -> List[Dict[str, Any]]:
    """Build graph views for prompts currently visible in ComfyUI's queue."""
    canvases: List[Dict[str, Any]] = []
    for queue_name in ("queue_running", "queue_pending"):
        items = queue_data.get(queue_name, [])
        if not isinstance(items, list):
            continue
        for position, item in enumerate(items, start=1):
            prompt_id, workflow = _extract_prompt_from_queue_item(item)
            if not workflow:
                continue
            graph = _graph_payload(workflow, include_nodes=include_nodes)
            graph.update(
                {
                    "source": queue_name,
                    "prompt_id": prompt_id,
                    "position": position,
                    "queue_item_preview": _queue_item_preview(item),
                }
            )
            canvases.append(graph)
    return canvases


def latest_saved_canvas(workflow_manager, include_nodes: bool = True) -> Optional[Dict[str, Any]]:
    """Return graph data for the most recently modified saved workflow."""
    workflow_path = _latest_workflow_path(workflow_manager.workflows_dir)
    if workflow_path is None:
        return None

    workflow_id = workflow_path.stem
    workflow = workflow_manager.load_workflow(workflow_id)
    if not workflow:
        return None

    graph = _graph_payload(workflow, include_nodes=include_nodes)
    graph.update(
        {
            "source": "latest_saved_workflow",
            "workflow_id": workflow_id,
            "workflow_path": str(workflow_path),
            "modified_at": workflow_path.stat().st_mtime,
        }
    )
    return graph


def _graph_payload(workflow: Dict[str, Any], include_nodes: bool = True) -> Dict[str, Any]:
    inspector = WorkflowGraphInspector(workflow)
    payload = {
        "summary": inspector.summary(),
        "edges": inspector.edges,
        "validation": inspector.validation(),
        "editable_parameters": inspector.editable_parameters(),
    }
    if include_nodes:
        payload["nodes"] = inspector.node_list()
    return payload


def _bridge_state_path(workflows_dir: Path) -> Path:
    configured = os.environ.get(BRIDGE_STATE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(workflows_dir) / DEFAULT_BRIDGE_STATE_NAME).resolve()


def _extract_bridge_workflow(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    workflow = state.get("workflow") or state.get("graph") or state.get("prompt")
    return workflow if isinstance(workflow, dict) else None


def _selected_node_payload(state: Dict[str, Any], workflow: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    selected = state.get("selected_node")
    if isinstance(selected, dict):
        return selected
    selected_id = state.get("selected_node_id")
    if selected_id is None:
        return None
    payload: Dict[str, Any] = {"id": str(selected_id)}
    if workflow and str(selected_id) in workflow and isinstance(workflow[str(selected_id)], dict):
        node = workflow[str(selected_id)]
        payload.update(
            {
                "class_type": node.get("class_type"),
                "title": node.get("_meta", {}).get("title") if isinstance(node.get("_meta"), dict) else node.get("class_type"),
            }
        )
    return payload


def _extract_prompt_from_queue_item(item: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract prompt_id and workflow graph from known ComfyUI queue item shapes."""
    if isinstance(item, dict):
        prompt_id = item.get("prompt_id") or item.get("id")
        prompt = item.get("prompt") or item.get("workflow")
        return str(prompt_id) if prompt_id else None, prompt if isinstance(prompt, dict) else None

    if isinstance(item, list):
        prompt_id = str(item[1]) if len(item) > 1 and item[1] is not None else None
        for value in item[2:]:
            if isinstance(value, dict) and _looks_like_workflow(value):
                return prompt_id, value
            if isinstance(value, dict) and isinstance(value.get("prompt"), dict):
                return prompt_id, value["prompt"]
    return None, None


def _looks_like_workflow(value: Dict[str, Any]) -> bool:
    return any(isinstance(node, dict) and isinstance(node.get("inputs"), dict) for node in value.values())


def _queue_item_preview(item: Any) -> Any:
    if isinstance(item, list):
        return [
            _preview_value(value)
            for value in item[:5]
        ]
    if isinstance(item, dict):
        return {key: _preview_value(value) for key, value in list(item.items())[:8]}
    return _preview_value(item)


def _preview_value(value: Any) -> Any:
    if isinstance(value, dict):
        if _looks_like_workflow(value):
            return {"workflow_node_count": len(value)}
        return {"dict_keys": list(value.keys())[:8]}
    if isinstance(value, list):
        return {"list_length": len(value)}
    return value


def _latest_workflow_path(workflows_dir: Path) -> Optional[Path]:
    paths = [
        path
        for path in Path(workflows_dir).glob("*.json")
        if not path.name.endswith(".meta.json")
    ]
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)
