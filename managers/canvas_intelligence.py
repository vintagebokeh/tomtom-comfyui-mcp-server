"""Read-only intelligence helpers for the live ComfyUI canvas."""

from __future__ import annotations

from collections import Counter, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from managers.live_canvas import bridge_canvas_state
from managers.node_schema import schema_for_node, validate_workflow_against_schemas
from managers.workflow_graph import WorkflowGraphInspector


DOMAIN_KEYWORDS = {
    "video": ("video", "wan", "frame", "movie", "vae decode"),
    "image": ("image", "mask", "sam", "seg", "krea", "latent"),
    "text": ("text", "clip", "prompt", "llm", "conditioning"),
    "audio": ("audio", "sound", "voice", "tts", "wav"),
    "model": ("loader", "checkpoint", "unet", "lora", "vae", "controlnet"),
    "output": ("save", "preview", "display"),
}


def explain_selected_canvas_node(workflow_manager, comfyui_client, max_depth: int = 2) -> Dict[str, Any]:
    """Explain the currently selected live-canvas node with schema and neighbors."""
    bridge = bridge_canvas_state(workflow_manager, include_nodes=False)
    if not bridge:
        return {
            "status": "unavailable",
            "source": "canvas_bridge",
            "message": "No live canvas bridge state is available.",
        }

    selected = bridge.get("selected_node") or {}
    selected_id = selected.get("id") if isinstance(selected, dict) else None
    workflow = _bridge_workflow_from_canvas(bridge)
    if not selected_id:
        return {
            "status": "no_selection",
            "source": "canvas_bridge",
            "workflow_id": bridge.get("workflow_id"),
            "workflow_name": bridge.get("workflow_name"),
            "message": "No node is currently selected in the ComfyUI canvas.",
        }
    if not workflow or str(selected_id) not in workflow:
        return {
            "status": "not_found",
            "source": "canvas_bridge",
            "workflow_id": bridge.get("workflow_id"),
            "workflow_name": bridge.get("workflow_name"),
            "selected_node": selected,
            "message": "Selected node was reported by the bridge but was not found in the workflow graph.",
        }

    inspector = WorkflowGraphInspector(workflow)
    node = workflow[str(selected_id)]
    details = inspector.node_details(str(selected_id), include_neighbors=True) or {}
    try:
        object_info = comfyui_client.get_object_info()
        schema = schema_for_node(node, object_info)
    except Exception as exc:
        schema = {"available": False, "error": str(exc)}

    return {
        "status": "success",
        "source": "canvas_bridge",
        "workflow_id": bridge.get("workflow_id"),
        "workflow_name": bridge.get("workflow_name"),
        "revision": bridge.get("revision"),
        "selected_node": _node_identity(str(selected_id), node),
        "role": _infer_node_role(node),
        "explanation": _node_explanation(node, details, schema),
        "schema": _compact_schema(schema),
        "inputs": details.get("inputs", {}),
        "incoming_edges": details.get("incoming_edges", []),
        "outgoing_edges": details.get("outgoing_edges", []),
        "upstream_trace": inspector.trace_inputs(str(selected_id), max_depth=max_depth),
        "downstream_trace": inspector.trace_outputs(str(selected_id), max_depth=max_depth),
        "safe_notes": _safe_node_notes(node, details, schema),
    }


def live_canvas_graph_insight(workflow_manager, comfyui_client, max_sections: int = 8) -> Dict[str, Any]:
    """Summarize the current live canvas as functional graph sections."""
    bridge = bridge_canvas_state(workflow_manager, include_nodes=False)
    if not bridge:
        return {
            "status": "unavailable",
            "source": "canvas_bridge",
            "message": "No live canvas bridge state is available.",
        }

    workflow = _bridge_workflow_from_canvas(bridge)
    inspector = WorkflowGraphInspector(workflow)
    components = _connected_components(inspector)
    domains = _domain_counts(workflow)
    sections = [_component_summary(component, workflow, inspector) for component in components]
    sections.sort(key=lambda item: item["node_count"], reverse=True)

    return {
        "status": "success",
        "source": "canvas_bridge",
        "workflow_id": bridge.get("workflow_id"),
        "workflow_name": bridge.get("workflow_name"),
        "revision": bridge.get("revision"),
        "summary": inspector.summary(),
        "validation": inspector.validation(),
        "domain_counts": domains,
        "component_count": len(components),
        "sections": sections[: max(1, min(int(max_sections), 20))],
        "entry_nodes": _entry_nodes(inspector, workflow)[:30],
        "terminal_nodes": _terminal_nodes(inspector, workflow)[:30],
    }


def live_canvas_suggestions(workflow_manager, comfyui_client, limit: int = 20) -> Dict[str, Any]:
    """Return read-only suggestions for the current live canvas."""
    bridge = bridge_canvas_state(workflow_manager, include_nodes=False)
    if not bridge:
        return {
            "status": "unavailable",
            "source": "canvas_bridge",
            "message": "No live canvas bridge state is available.",
        }

    workflow = _bridge_workflow_from_canvas(bridge)
    inspector = WorkflowGraphInspector(workflow)
    suggestions: List[Dict[str, Any]] = []
    validation = inspector.validation()
    for edge in validation.get("missing_source_edges", []):
        suggestions.append(
            {
                "severity": "error",
                "kind": "missing_source",
                "message": "A linked input points to a missing source node.",
                "edge": edge,
            }
        )
    for node_id in validation.get("isolated_nodes", []):
        suggestions.append(
            {
                "severity": "warning",
                "kind": "isolated_node",
                "message": "This node is isolated from the rest of the graph.",
                "node": _node_identity(node_id, inspector.nodes[node_id]),
            }
        )

    try:
        object_info = comfyui_client.get_object_info()
        schema_validation = validate_workflow_against_schemas(workflow, object_info)
    except Exception as exc:
        schema_validation = {"valid": False, "error": str(exc), "errors": [], "warnings": []}

    for error in schema_validation.get("errors", []):
        suggestions.append(
            {
                "severity": "error",
                "kind": "schema_error",
                "message": "Node does not match its ComfyUI schema.",
                "details": error,
            }
        )
    for warning in schema_validation.get("warnings", []):
        suggestions.append(
            {
                "severity": "warning",
                "kind": "schema_warning",
                "message": "Node input is unusual for its schema.",
                "details": warning,
            }
        )

    suggestions.extend(_fanout_suggestions(inspector))
    suggestions.extend(_parameter_suggestions(workflow))
    suggestions.extend(_output_suggestions(inspector))

    severity_order = {"error": 0, "warning": 1, "info": 2}
    suggestions.sort(key=lambda item: severity_order.get(item.get("severity", "info"), 9))
    limit = max(1, min(int(limit), 100))
    return {
        "status": "success",
        "source": "canvas_bridge",
        "workflow_id": bridge.get("workflow_id"),
        "workflow_name": bridge.get("workflow_name"),
        "revision": bridge.get("revision"),
        "schema_validation": {
            "valid": schema_validation.get("valid"),
            "error_count": schema_validation.get("error_count", len(schema_validation.get("errors", []))),
            "warning_count": schema_validation.get("warning_count", len(schema_validation.get("warnings", []))),
            "ui_metadata_count": schema_validation.get("ui_metadata_count", 0),
            "nested_schema_input_count": schema_validation.get("nested_schema_input_count", 0),
        },
        "suggestion_count": len(suggestions),
        "suggestions": suggestions[:limit],
    }


def _bridge_workflow_from_canvas(canvas: Dict[str, Any]) -> Dict[str, Any]:
    bridge_path = canvas.get("bridge_path")
    if not bridge_path:
        return {}
    try:
        import json
        from pathlib import Path

        payload = json.loads(Path(bridge_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    workflow = payload.get("workflow") or payload.get("graph") or payload.get("prompt")
    return workflow if isinstance(workflow, dict) else {}


def _node_identity(node_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
    meta = node.get("_meta", {}) if isinstance(node.get("_meta"), dict) else {}
    return {
        "id": str(node_id),
        "class_type": node.get("class_type"),
        "title": meta.get("title") or node.get("class_type") or f"Node {node_id}",
    }


def _infer_node_role(node: Dict[str, Any]) -> str:
    text = f"{node.get('class_type', '')} {node.get('_meta', {}).get('title', '') if isinstance(node.get('_meta'), dict) else ''}".lower()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return domain
    return "processing"


def _node_explanation(node: Dict[str, Any], details: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    class_type = node.get("class_type")
    incoming = len(details.get("incoming_edges", []))
    outgoing = len(details.get("outgoing_edges", []))
    schema_inputs = schema.get("inputs", []) if schema.get("available") else []
    schema_outputs = schema.get("outputs", []) if schema.get("available") else []
    return {
        "plain": (
            f"{class_type} receives {incoming} linked input(s), has {details.get('literal_input_count', 0)} literal setting(s), "
            f"and sends data to {outgoing} downstream node(s)."
        ),
        "input_types": _type_names(schema_inputs),
        "output_types": [item.get("type") for item in schema_outputs],
        "category": schema.get("category"),
        "description": schema.get("description"),
    }


def _compact_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    if not schema.get("available"):
        return schema
    return {
        "available": True,
        "class_type": schema.get("class_type"),
        "display_name": schema.get("display_name"),
        "category": schema.get("category"),
        "is_output_node": schema.get("is_output_node"),
        "inputs": schema.get("inputs", [])[:30],
        "outputs": schema.get("outputs", []),
    }


def _type_names(inputs: List[Dict[str, Any]]) -> List[str]:
    seen = []
    for item in inputs:
        value = item.get("type")
        if value and value not in seen:
            seen.append(value)
    return seen


def _safe_node_notes(node: Dict[str, Any], details: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    notes = []
    if not schema.get("available"):
        notes.append("Schema is unavailable, so type-level guidance may be incomplete.")
    if not details.get("outgoing_edges") and not schema.get("is_output_node"):
        notes.append("This node has no downstream consumers and is not marked as an output node.")
    if details.get("incoming_edges") and not details.get("outgoing_edges"):
        notes.append("This node is a terminal point in the current graph path.")
    if not details.get("incoming_edges") and details.get("outgoing_edges"):
        notes.append("This node appears to be an entry/source node for downstream work.")
    return notes


def _connected_components(inspector: WorkflowGraphInspector) -> List[Set[str]]:
    unvisited = set(inspector.nodes)
    components: List[Set[str]] = []
    while unvisited:
        start = unvisited.pop()
        component = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            neighbors = {
                edge["source_id"] for edge in inspector.incoming.get(current, []) if edge["source_exists"]
            } | {edge["target_id"] for edge in inspector.outgoing.get(current, [])}
            for neighbor in neighbors:
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def _component_summary(component: Set[str], workflow: Dict[str, Any], inspector: WorkflowGraphInspector) -> Dict[str, Any]:
    class_counts = Counter(str(workflow[node_id].get("class_type", "Unknown")) for node_id in component)
    domains = Counter(_infer_node_role(workflow[node_id]) for node_id in component)
    entry = [node_id for node_id in component if not inspector.incoming.get(node_id)]
    terminal = [node_id for node_id in component if not inspector.outgoing.get(node_id)]
    return {
        "node_count": len(component),
        "edge_count": sum(1 for edge in inspector.edges if edge["source_id"] in component and edge["target_id"] in component),
        "dominant_domains": dict(domains.most_common(5)),
        "top_classes": dict(class_counts.most_common(8)),
        "entry_nodes": [_node_identity(node_id, workflow[node_id]) for node_id in sorted(entry, key=_sort_node_id)[:10]],
        "terminal_nodes": [_node_identity(node_id, workflow[node_id]) for node_id in sorted(terminal, key=_sort_node_id)[:10]],
    }


def _domain_counts(workflow: Dict[str, Any]) -> Dict[str, int]:
    counts = Counter(_infer_node_role(node) for node in workflow.values() if isinstance(node, dict))
    return dict(counts.most_common())


def _entry_nodes(inspector: WorkflowGraphInspector, workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        _node_identity(node_id, workflow[node_id])
        for node_id in sorted(inspector.nodes, key=_sort_node_id)
        if not inspector.incoming.get(node_id) and inspector.outgoing.get(node_id)
    ]


def _terminal_nodes(inspector: WorkflowGraphInspector, workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        _node_identity(node_id, workflow[node_id])
        for node_id in sorted(inspector.nodes, key=_sort_node_id)
        if inspector.incoming.get(node_id) and not inspector.outgoing.get(node_id)
    ]


def _fanout_suggestions(inspector: WorkflowGraphInspector) -> List[Dict[str, Any]]:
    suggestions = []
    for node_id, edges in inspector.outgoing.items():
        if len(edges) >= 6 and node_id in inspector.nodes:
            suggestions.append(
                {
                    "severity": "info",
                    "kind": "high_fanout",
                    "message": "This node feeds many downstream nodes and may be an important hub.",
                    "node": _node_identity(node_id, inspector.nodes[node_id]),
                    "downstream_count": len(edges),
                }
            )
    return suggestions


def _parameter_suggestions(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    suggestions = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if isinstance(value, str) and value.startswith("PARAM_"):
                suggestions.append(
                    {
                        "severity": "info",
                        "kind": "editable_parameter",
                        "message": "This input is explicitly marked as AI-editable through a PARAM_ placeholder.",
                        "node": _node_identity(str(node_id), node),
                        "input_name": input_name,
                        "placeholder": value,
                    }
                )
    return suggestions


def _output_suggestions(inspector: WorkflowGraphInspector) -> List[Dict[str, Any]]:
    if inspector.summary().get("output_nodes"):
        return []
    return [
        {
            "severity": "warning",
            "kind": "no_output_node",
            "message": "No obvious save/preview/output node was detected.",
        }
    ]


def _sort_node_id(node_id: str) -> Tuple[int, str]:
    try:
        return (0, f"{int(node_id):010d}")
    except (TypeError, ValueError):
        return (1, str(node_id))
