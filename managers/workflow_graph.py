"""Workflow graph inspection helpers for ComfyUI workflow JSON."""

from __future__ import annotations

from collections import Counter, deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


LINK_VALUE_LENGTH = 2
OUTPUT_CLASS_HINTS = ("save", "preview", "display", "image", "video", "audio")


def _is_node(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("inputs", {}), dict)


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= LINK_VALUE_LENGTH
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def _node_title(node: Dict[str, Any], node_id: str) -> str:
    meta = node.get("_meta", {})
    if isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return str(node.get("class_type") or f"Node {node_id}")


def _iter_nodes(workflow: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for node_id, node in workflow.items():
        if _is_node(node):
            yield str(node_id), node


class WorkflowGraphInspector:
    """Build compact, AI-readable graph views from ComfyUI workflow JSON."""

    def __init__(self, workflow: Dict[str, Any]):
        self.workflow = workflow
        self.nodes = {node_id: node for node_id, node in _iter_nodes(workflow)}
        self.edges = self._build_edges()
        self.incoming = self._index_edges("target_id")
        self.outgoing = self._index_edges("source_id")

    def _build_edges(self) -> List[Dict[str, Any]]:
        edges: List[Dict[str, Any]] = []
        for target_id, node in self.nodes.items():
            for input_name, value in node.get("inputs", {}).items():
                if not _is_link(value):
                    continue
                source_id = str(value[0])
                edges.append(
                    {
                        "source_id": source_id,
                        "source_output_index": value[1],
                        "target_id": target_id,
                        "target_input": input_name,
                        "source_exists": source_id in self.nodes,
                    }
                )
        return edges

    def _index_edges(self, key: str) -> Dict[str, List[Dict[str, Any]]]:
        indexed: Dict[str, List[Dict[str, Any]]] = {}
        for edge in self.edges:
            indexed.setdefault(str(edge[key]), []).append(edge)
        return indexed

    def summary(self) -> Dict[str, Any]:
        class_counts = Counter(str(node.get("class_type", "Unknown")) for node in self.nodes.values())
        missing_sources = [edge for edge in self.edges if not edge["source_exists"]]
        output_nodes = self._find_output_nodes()
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "class_counts": dict(class_counts.most_common()),
            "output_nodes": output_nodes,
            "missing_source_edges": missing_sources,
            "has_missing_sources": bool(missing_sources),
        }

    def node_list(self, class_type: Optional[str] = None) -> List[Dict[str, Any]]:
        class_filter = class_type.lower() if class_type else None
        nodes: List[Dict[str, Any]] = []
        for node_id, node in sorted(self.nodes.items(), key=lambda item: _sort_key(item[0])):
            node_class = str(node.get("class_type", "Unknown"))
            if class_filter and class_filter not in node_class.lower():
                continue
            nodes.append(self._node_brief(node_id, node))
        return nodes

    def node_details(self, node_id: str, include_neighbors: bool = True) -> Optional[Dict[str, Any]]:
        node = self.nodes.get(str(node_id))
        if not node:
            return None

        details = self._node_brief(str(node_id), node)
        details["inputs"] = self._split_inputs(node)
        if include_neighbors:
            details["incoming_edges"] = self.incoming.get(str(node_id), [])
            details["outgoing_edges"] = self.outgoing.get(str(node_id), [])
            details["upstream_node_ids"] = sorted({edge["source_id"] for edge in self.incoming.get(str(node_id), [])}, key=_sort_key)
            details["downstream_node_ids"] = sorted({edge["target_id"] for edge in self.outgoing.get(str(node_id), [])}, key=_sort_key)
        return details

    def trace_inputs(self, node_id: str, max_depth: int = 3) -> Dict[str, Any]:
        return self._trace(str(node_id), "upstream", max_depth)

    def trace_outputs(self, node_id: str, max_depth: int = 3) -> Dict[str, Any]:
        return self._trace(str(node_id), "downstream", max_depth)

    def editable_parameters(self) -> List[Dict[str, Any]]:
        params: List[Dict[str, Any]] = []
        for node_id, node in sorted(self.nodes.items(), key=lambda item: _sort_key(item[0])):
            for input_name, value in node.get("inputs", {}).items():
                if isinstance(value, str) and value.startswith("PARAM_"):
                    params.append(
                        {
                            "parameter": _normalize_param_name(value),
                            "placeholder": value,
                            "node_id": node_id,
                            "node_class": node.get("class_type"),
                            "node_title": _node_title(node, node_id),
                            "input_name": input_name,
                        }
                    )
        return params

    def validation(self) -> Dict[str, Any]:
        missing_source_edges = [edge for edge in self.edges if not edge["source_exists"]]
        isolated_nodes = [
            node_id
            for node_id in self.nodes
            if not self.incoming.get(node_id) and not self.outgoing.get(node_id)
        ]
        return {
            "valid": not missing_source_edges,
            "missing_source_edges": missing_source_edges,
            "isolated_nodes": sorted(isolated_nodes, key=_sort_key),
            "warnings": self._warnings(missing_source_edges, isolated_nodes),
        }

    def _node_brief(self, node_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
        literal_inputs, linked_inputs = self._split_inputs(node)
        return {
            "id": node_id,
            "class_type": node.get("class_type"),
            "title": _node_title(node, node_id),
            "literal_input_count": len(literal_inputs),
            "linked_input_count": len(linked_inputs),
            "incoming_count": len(self.incoming.get(node_id, [])),
            "outgoing_count": len(self.outgoing.get(node_id, [])),
        }

    def _split_inputs(self, node: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        literal_inputs: Dict[str, Any] = {}
        linked_inputs: Dict[str, Any] = {}
        for input_name, value in node.get("inputs", {}).items():
            if _is_link(value):
                linked_inputs[input_name] = {
                    "source_id": str(value[0]),
                    "source_output_index": value[1],
                }
            else:
                literal_inputs[input_name] = value
        return literal_inputs, linked_inputs

    def _trace(self, node_id: str, direction: str, max_depth: int) -> Dict[str, Any]:
        if node_id not in self.nodes:
            return {"error": f"Node '{node_id}' not found"}

        max_depth = max(0, min(int(max_depth), 10))
        queue = deque([(node_id, 0)])
        visited: Set[str] = {node_id}
        ordered_nodes: List[Dict[str, Any]] = []
        trace_edges: List[Dict[str, Any]] = []

        while queue:
            current_id, depth = queue.popleft()
            current_node = self.nodes[current_id]
            ordered_nodes.append(
                {
                    "id": current_id,
                    "depth": depth,
                    "class_type": current_node.get("class_type"),
                    "title": _node_title(current_node, current_id),
                }
            )
            if depth >= max_depth:
                continue

            edges = self.incoming.get(current_id, []) if direction == "upstream" else self.outgoing.get(current_id, [])
            for edge in edges:
                next_id = edge["source_id"] if direction == "upstream" else edge["target_id"]
                trace_edges.append(edge)
                if next_id in self.nodes and next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, depth + 1))

        return {
            "root_node_id": node_id,
            "direction": direction,
            "max_depth": max_depth,
            "nodes": ordered_nodes,
            "edges": trace_edges,
        }

    def _find_output_nodes(self) -> List[Dict[str, Any]]:
        output_nodes = []
        for node_id, node in self.nodes.items():
            class_type = str(node.get("class_type", ""))
            lower_class = class_type.lower()
            if any(hint in lower_class for hint in OUTPUT_CLASS_HINTS) and "loader" not in lower_class:
                output_nodes.append(
                    {
                        "id": node_id,
                        "class_type": class_type,
                        "title": _node_title(node, node_id),
                    }
                )
        return sorted(output_nodes, key=lambda item: _sort_key(item["id"]))

    def _warnings(self, missing_source_edges: List[Dict[str, Any]], isolated_nodes: List[str]) -> List[str]:
        warnings = []
        if missing_source_edges:
            warnings.append(f"{len(missing_source_edges)} linked inputs point to missing source nodes.")
        if isolated_nodes:
            warnings.append(f"{len(isolated_nodes)} nodes are isolated from the graph.")
        if not self._find_output_nodes():
            warnings.append("No obvious output/save/preview node was detected.")
        return warnings


def _sort_key(node_id: str) -> Tuple[int, str]:
    try:
        return (0, f"{int(node_id):010d}")
    except (TypeError, ValueError):
        return (1, str(node_id))


def _normalize_param_name(placeholder: str) -> str:
    token = placeholder[len("PARAM_") :]
    if "_" in token:
        first, rest = token.split("_", 1)
        if first.upper() in {"STR", "STRING", "TEXT", "INT", "FLOAT", "BOOL"}:
            token = rest
    cleaned = ["_" if not char.isalnum() else char.lower() for char in token.strip()]
    return "".join(cleaned).strip("_") or "param"
