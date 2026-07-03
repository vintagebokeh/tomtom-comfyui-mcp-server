"""Read-only live canvas helpers for ComfyUI-visible workflow graphs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from managers.workflow_graph import WorkflowGraphInspector


BRIDGE_STATE_ENV = "COMFY_MCP_CANVAS_BRIDGE_STATE"
BRIDGE_HISTORY_ENV = "COMFY_MCP_CANVAS_BRIDGE_HISTORY_DIR"
DEFAULT_BRIDGE_STATE_NAME = ".tomtom_canvas_bridge.json"
DEFAULT_BRIDGE_HISTORY_DIR_NAME = ".tomtom_canvas_bridge_history"


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
            "history_dir": str(_bridge_history_dir(workflow_manager.workflows_dir)),
            "poll_tools": ["get_current_canvas", "refresh_canvas"],
        }
    return {
        "status": "ready",
        "source": "canvas_bridge",
        "message": "Bridge state is available. Poll refresh_canvas and compare revision for updates.",
        "bridge_path": str(bridge_path),
        "history_dir": str(_bridge_history_dir(workflow_manager.workflows_dir)),
        "revision": bridge.get("revision"),
        "updated_at": bridge.get("updated_at"),
        "poll_tools": ["refresh_canvas"],
    }


def canvas_snapshot_history(workflow_manager, limit: int = 20) -> Dict[str, Any]:
    """List recent canvas bridge snapshots without returning full workflows."""
    history_dir = _bridge_history_dir(workflow_manager.workflows_dir)
    snapshots = _history_snapshot_paths(history_dir)
    limit = max(1, min(int(limit), 100))
    entries = []
    for path in snapshots[:limit]:
        payload = _read_snapshot_payload(path)
        if not payload:
            continue
        entries.append(_snapshot_summary(path, payload))
    return {
        "status": "success",
        "source": "canvas_bridge_history",
        "history_dir": str(history_dir),
        "count": len(entries),
        "total_available": len(snapshots),
        "snapshots": entries,
    }


def canvas_snapshot(workflow_manager, revision: Optional[int] = None, snapshot_id: Optional[str] = None, include_workflow: bool = False) -> Dict[str, Any]:
    """Get one canvas snapshot by revision, snapshot id, or latest."""
    path = _find_snapshot_path(workflow_manager.workflows_dir, revision=revision, snapshot_id=snapshot_id)
    if not path:
        return {
            "status": "not_found",
            "source": "canvas_bridge_history",
            "revision": revision,
            "snapshot_id": snapshot_id,
            "message": "No matching canvas snapshot was found.",
        }
    payload = _read_snapshot_payload(path)
    if not payload:
        return {
            "status": "error",
            "source": "canvas_bridge_history",
            "snapshot_path": str(path),
            "message": "Canvas snapshot could not be parsed.",
        }
    result = _snapshot_summary(path, payload)
    result.update(
        {
            "status": "success",
            "source": "canvas_bridge_history",
            "selected_node": _selected_node_payload(payload, _extract_bridge_workflow(payload)),
            "viewport": payload.get("viewport"),
        }
    )
    if include_workflow:
        result["workflow"] = _extract_bridge_workflow(payload) or {}
        result["ui_workflow"] = payload.get("ui_workflow")
    return result


def diff_canvas_snapshots(workflow_manager, base_revision: Optional[int] = None, target_revision: Optional[int] = None) -> Dict[str, Any]:
    """Diff two canvas snapshots by revision.

    If target_revision is omitted, the latest snapshot is used. If
    base_revision is omitted, the previous snapshot before the target is used.
    """
    history_dir = _bridge_history_dir(workflow_manager.workflows_dir)
    snapshots = _load_history_payloads(history_dir)
    if len(snapshots) < 2:
        return {
            "status": "not_available",
            "source": "canvas_bridge_history",
            "message": "At least two canvas snapshots are required to diff history.",
            "snapshot_count": len(snapshots),
        }

    target_index = _snapshot_index_by_revision(snapshots, target_revision) if target_revision is not None else len(snapshots) - 1
    if target_index is None:
        return {"status": "not_found", "source": "canvas_bridge_history", "message": "Target revision was not found."}

    if base_revision is not None:
        base_index = _snapshot_index_by_revision(snapshots, base_revision)
    else:
        base_index = target_index - 1
    if base_index is None or base_index < 0:
        return {"status": "not_found", "source": "canvas_bridge_history", "message": "Base revision was not found."}

    base_path, base = snapshots[base_index]
    target_path, target = snapshots[target_index]
    base_workflow = _extract_bridge_workflow(base) or {}
    target_workflow = _extract_bridge_workflow(target) or {}
    base_nodes = set(str(node_id) for node_id in base_workflow)
    target_nodes = set(str(node_id) for node_id in target_workflow)
    common_nodes = base_nodes & target_nodes
    changed_nodes = [
        node_id
        for node_id in sorted(common_nodes, key=_sort_node_id)
        if base_workflow.get(node_id) != target_workflow.get(node_id)
    ]
    return {
        "status": "success",
        "source": "canvas_bridge_history",
        "base": _snapshot_summary(base_path, base),
        "target": _snapshot_summary(target_path, target),
        "node_count_delta": len(target_nodes) - len(base_nodes),
        "edge_count_delta": _edge_count(target_workflow) - _edge_count(base_workflow),
        "added_node_ids": sorted(target_nodes - base_nodes, key=_sort_node_id),
        "removed_node_ids": sorted(base_nodes - target_nodes, key=_sort_node_id),
        "changed_node_ids": changed_nodes[:100],
        "changed_node_count": len(changed_nodes),
        "selected_node_changed": base.get("selected_node_id") != target.get("selected_node_id"),
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


def _bridge_history_dir(workflows_dir: Path) -> Path:
    configured = os.environ.get(BRIDGE_HISTORY_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return _bridge_state_path(workflows_dir).parent / DEFAULT_BRIDGE_HISTORY_DIR_NAME


def _history_snapshot_paths(history_dir: Path) -> List[Path]:
    if not history_dir.exists():
        return []
    return sorted(history_dir.glob("rev-*.json"), key=lambda path: (path.stat().st_mtime, path.name))


def _read_snapshot_payload(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _snapshot_summary(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    workflow = _extract_bridge_workflow(payload) or {}
    return {
        "snapshot_id": payload.get("snapshot_id") or path.stem,
        "snapshot_path": str(path),
        "revision": payload.get("revision"),
        "updated_at": payload.get("updated_at"),
        "server_received_at": payload.get("server_received_at"),
        "workflow_id": payload.get("workflow_id"),
        "workflow_name": payload.get("workflow_name") or payload.get("name"),
        "selected_node_id": payload.get("selected_node_id"),
        "node_count": len(workflow),
        "edge_count": _edge_count(workflow),
    }


def _find_snapshot_path(workflows_dir: Path, revision: Optional[int] = None, snapshot_id: Optional[str] = None) -> Optional[Path]:
    snapshots = _history_snapshot_paths(_bridge_history_dir(workflows_dir))
    if not snapshots:
        return None
    if snapshot_id:
        for path in snapshots:
            if path.stem == snapshot_id or path.name == snapshot_id:
                return path
    if revision is not None:
        for path in reversed(snapshots):
            payload = _read_snapshot_payload(path)
            if payload and payload.get("revision") == revision:
                return path
        return None
    return snapshots[-1]


def _load_history_payloads(history_dir: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    loaded = []
    for path in _history_snapshot_paths(history_dir):
        payload = _read_snapshot_payload(path)
        if payload:
            loaded.append((path, payload))
    return loaded


def _snapshot_index_by_revision(snapshots: List[Tuple[Path, Dict[str, Any]]], revision: Optional[int]) -> Optional[int]:
    for index, (_, payload) in enumerate(snapshots):
        if payload.get("revision") == revision:
            return index
    return None


def _edge_count(workflow: Dict[str, Any]) -> int:
    count = 0
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        count += sum(1 for value in inputs.values() if isinstance(value, list) and len(value) >= 2)
    return count


def _sort_node_id(node_id: str) -> Tuple[int, str]:
    try:
        return (0, f"{int(node_id):010d}")
    except (TypeError, ValueError):
        return (1, str(node_id))


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
        if not path.name.endswith(".meta.json") and not path.name.startswith(".")
    ]
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)
