"""Safe edit planning and copy-first workflow JSON editing."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


UI_FIELD_ALLOWLIST = {
    "_meta",
    "bgcolor",
    "color",
    "flags",
    "mode",
    "order",
    "pos",
    "properties",
    "size",
    "widgets_values",
}


class WorkflowEditError(ValueError):
    """Raised for rejected workflow edit requests."""


def copy_workflow(workflow_manager, workflow_id: str, new_workflow_id: Optional[str] = None) -> Dict[str, Any]:
    """Copy a workflow JSON file inside the workflow directory."""
    source_path = _existing_workflow_path(workflow_manager, workflow_id)
    if new_workflow_id is None:
        new_workflow_id = _default_copy_id(workflow_id)
    target_path = _new_workflow_path(workflow_manager, new_workflow_id)
    if target_path.exists():
        raise WorkflowEditError(f"Target workflow already exists: {new_workflow_id}")

    workflow = _read_json(source_path)
    _write_json(target_path, workflow)
    return {
        "source_workflow_id": workflow_id,
        "new_workflow_id": target_path.stem,
        "source_path": str(source_path),
        "new_path": str(target_path),
        "message": "Created an editable workflow copy. Original workflow was not modified.",
    }


def plan_edits(workflow: Dict[str, Any], edits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply edits in memory and return a dry-run diff."""
    edited = copy.deepcopy(workflow)
    applied = _apply_edits(edited, edits)
    return {
        "status": "planned",
        "will_write": False,
        "applied_operations": applied,
        "diff": diff_workflow_dicts(workflow, edited),
    }


def edit_workflow_copy(
    workflow_manager,
    workflow_id: str,
    edits: List[Dict[str, Any]],
    require_ai_edit_copy: bool = True,
) -> Dict[str, Any]:
    """Apply edits to a saved workflow file, normally only an *_ai_edit* copy."""
    if require_ai_edit_copy and "_ai_edit" not in workflow_id:
        raise WorkflowEditError("Refusing to edit original workflow. Copy it first, then edit the *_ai_edit* workflow.")

    workflow_path = _existing_workflow_path(workflow_manager, workflow_id)
    before = _read_json(workflow_path)
    after = copy.deepcopy(before)
    applied = _apply_edits(after, edits)
    diff = diff_workflow_dicts(before, after)
    if not diff:
        return {
            "status": "unchanged",
            "workflow_id": workflow_id,
            "path": str(workflow_path),
            "applied_operations": applied,
            "diff": [],
        }

    _write_json(workflow_path, after)
    return {
        "status": "edited",
        "workflow_id": workflow_id,
        "path": str(workflow_path),
        "applied_operations": applied,
        "diff": diff,
    }


def diff_saved_workflows(workflow_manager, base_workflow_id: str, edited_workflow_id: str) -> Dict[str, Any]:
    base_path = _existing_workflow_path(workflow_manager, base_workflow_id)
    edited_path = _existing_workflow_path(workflow_manager, edited_workflow_id)
    base = _read_json(base_path)
    edited = _read_json(edited_path)
    return {
        "base_workflow_id": base_workflow_id,
        "edited_workflow_id": edited_workflow_id,
        "base_path": str(base_path),
        "edited_path": str(edited_path),
        "diff": diff_workflow_dicts(base, edited),
    }


def diff_workflow_dicts(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return compact node-level changes between two workflow dicts."""
    changes: List[Dict[str, Any]] = []
    before_nodes = _nodes(before)
    after_nodes = _nodes(after)

    for node_id in sorted(before_nodes.keys() | after_nodes.keys(), key=_sort_key):
        if node_id not in before_nodes:
            changes.append({"node_id": node_id, "change": "node_added", "after": _node_label(after_nodes[node_id], node_id)})
            continue
        if node_id not in after_nodes:
            changes.append({"node_id": node_id, "change": "node_removed", "before": _node_label(before_nodes[node_id], node_id)})
            continue

        node_changes = _diff_values(before_nodes[node_id], after_nodes[node_id])
        for item in node_changes:
            item["node_id"] = node_id
            item["node_title"] = _node_title(after_nodes[node_id], node_id)
            item["class_type"] = after_nodes[node_id].get("class_type")
            changes.append(item)
    return changes


def _apply_edits(workflow: Dict[str, Any], edits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(edits, list) or not edits:
        raise WorkflowEditError("edits must be a non-empty list")

    applied = []
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise WorkflowEditError(f"Edit #{index + 1} must be an object")
        operation = edit.get("operation")
        node_id = str(edit.get("node_id", ""))
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            raise WorkflowEditError(f"Node '{node_id}' not found")

        if operation == "set_node_position":
            position = edit.get("position")
            if not _is_number_pair(position):
                raise WorkflowEditError("set_node_position requires position=[x, y]")
            node["pos"] = [position[0], position[1]]
        elif operation == "set_node_title":
            title = edit.get("title")
            if not isinstance(title, str) or not title.strip():
                raise WorkflowEditError("set_node_title requires a non-empty title")
            meta = node.setdefault("_meta", {})
            if not isinstance(meta, dict):
                raise WorkflowEditError(f"Node '{node_id}' _meta is not an object")
            meta["title"] = title
        elif operation == "set_node_input":
            input_name = edit.get("input_name")
            if not isinstance(input_name, str) or not input_name:
                raise WorkflowEditError("set_node_input requires input_name")
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                raise WorkflowEditError(f"Node '{node_id}' inputs is not an object")
            inputs[input_name] = edit.get("value")
        elif operation == "set_node_ui_field":
            field = edit.get("field")
            if field not in UI_FIELD_ALLOWLIST:
                raise WorkflowEditError(f"UI field '{field}' is not editable by this tool")
            node[field] = edit.get("value")
        else:
            raise WorkflowEditError(f"Unsupported edit operation: {operation}")

        applied.append({"index": index, "operation": operation, "node_id": node_id})
    return applied


def _existing_workflow_path(workflow_manager, workflow_id: str) -> Path:
    path = workflow_manager._safe_workflow_path(workflow_id)
    if not path:
        raise WorkflowEditError(f"Workflow '{workflow_id}' not found")
    return Path(path)


def _new_workflow_path(workflow_manager, workflow_id: str) -> Path:
    safe_id = _safe_workflow_id(workflow_id)
    path = (Path(workflow_manager.workflows_dir) / f"{safe_id}.json").resolve()
    try:
        path.relative_to(Path(workflow_manager.workflows_dir).resolve())
    except ValueError as exc:
        raise WorkflowEditError("Target workflow path is outside workflow directory") from exc
    return path


def _default_copy_id(workflow_id: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_safe_workflow_id(workflow_id)}_ai_edit_{stamp}"


def _safe_workflow_id(workflow_id: str) -> str:
    safe_id = str(workflow_id).replace("/", "_").replace("\\", "_").replace("..", "_")
    safe_id = "".join(char for char in safe_id if char.isalnum() or char in ("_", "-"))
    if not safe_id:
        raise WorkflowEditError("Invalid workflow id")
    return safe_id


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise WorkflowEditError(f"Workflow JSON is not an object: {path}")
    return data


def _write_json(path: Path, workflow: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(workflow, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _nodes(workflow: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(node_id): node for node_id, node in workflow.items() if isinstance(node, dict) and isinstance(node.get("inputs", {}), dict)}


def _diff_values(before: Any, after: Any, path: str = "") -> List[Dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"change": "added", "path": child_path, "after": after[key]})
            elif key not in after:
                changes.append({"change": "removed", "path": child_path, "before": before[key]})
            else:
                changes.extend(_diff_values(before[key], after[key], child_path))
        return changes
    return [{"change": "changed", "path": path, "before": before, "after": after}]


def _is_number_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value)


def _node_label(node: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    return {"id": node_id, "class_type": node.get("class_type"), "title": _node_title(node, node_id)}


def _node_title(node: Dict[str, Any], node_id: str) -> str:
    meta = node.get("_meta", {})
    if isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return str(node.get("class_type") or f"Node {node_id}")


def _sort_key(node_id: str) -> Tuple[int, str]:
    try:
        return (0, f"{int(node_id):010d}")
    except (TypeError, ValueError):
        return (1, str(node_id))
