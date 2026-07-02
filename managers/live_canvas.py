"""Read-only live canvas helpers for ComfyUI-visible workflow graphs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from managers.workflow_graph import WorkflowGraphInspector


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
