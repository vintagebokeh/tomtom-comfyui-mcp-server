"""Normalize ComfyUI /object_info node schemas for AI inspection."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


INPUT_SECTIONS = ("required", "optional", "hidden")


def normalize_node_schema(class_type: str, object_info: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one ComfyUI object_info entry into a compact schema."""
    raw_schema = object_info.get(class_type, object_info)
    if not isinstance(raw_schema, dict):
        return {"class_type": class_type, "available": False, "error": "Invalid object_info schema"}

    inputs = _normalize_inputs(raw_schema.get("input", {}), raw_schema.get("input_order", {}))
    outputs = _normalize_outputs(raw_schema)
    return {
        "class_type": class_type,
        "available": True,
        "name": raw_schema.get("name", class_type),
        "display_name": raw_schema.get("display_name"),
        "description": raw_schema.get("description"),
        "category": raw_schema.get("category"),
        "python_module": raw_schema.get("python_module"),
        "is_output_node": bool(raw_schema.get("output_node", False)),
        "deprecated": bool(raw_schema.get("deprecated", False)),
        "experimental": bool(raw_schema.get("experimental", False)),
        "inputs": inputs,
        "outputs": outputs,
    }


def normalize_workflow_schemas(workflow: Dict[str, Any], object_info: Dict[str, Any]) -> Dict[str, Any]:
    """Return schemas for every unique class type used by a workflow."""
    class_types = sorted(
        {
            str(node.get("class_type"))
            for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type")
        }
    )
    schemas = {}
    missing = []
    for class_type in class_types:
        if class_type not in object_info:
            missing.append(class_type)
            schemas[class_type] = {"class_type": class_type, "available": False}
            continue
        schemas[class_type] = normalize_node_schema(class_type, object_info[class_type])
    return {
        "schemas": schemas,
        "class_count": len(class_types),
        "missing_class_types": missing,
    }


def schema_for_node(node: Dict[str, Any], object_info: Dict[str, Any]) -> Dict[str, Any]:
    class_type = str(node.get("class_type", ""))
    if not class_type:
        return {"available": False, "error": "Node has no class_type"}
    if class_type not in object_info:
        return {"class_type": class_type, "available": False}
    return normalize_node_schema(class_type, object_info[class_type])


def validate_workflow_against_schemas(workflow: Dict[str, Any], object_info: Dict[str, Any]) -> Dict[str, Any]:
    """Basic schema-aware validation for node classes and declared inputs."""
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for node_id, node in _iter_nodes(workflow):
        class_type = str(node.get("class_type", ""))
        raw_schema = object_info.get(class_type)
        if not isinstance(raw_schema, dict):
            errors.append({"node_id": node_id, "class_type": class_type, "error": "NODE_CLASS_NOT_FOUND"})
            continue

        schema = normalize_node_schema(class_type, raw_schema)
        declared_inputs = {item["name"]: item for item in schema["inputs"]}
        actual_inputs = node.get("inputs", {})
        if not isinstance(actual_inputs, dict):
            errors.append({"node_id": node_id, "class_type": class_type, "error": "NODE_INPUTS_NOT_OBJECT"})
            continue

        for input_schema in schema["inputs"]:
            if input_schema["section"] != "required":
                continue
            if input_schema["name"] not in actual_inputs:
                errors.append(
                    {
                        "node_id": node_id,
                        "class_type": class_type,
                        "input_name": input_schema["name"],
                        "input_type": input_schema["type"],
                        "error": "REQUIRED_INPUT_MISSING",
                    }
                )

        for input_name, value in actual_inputs.items():
            input_schema = declared_inputs.get(input_name)
            if not input_schema:
                warnings.append(
                    {
                        "node_id": node_id,
                        "class_type": class_type,
                        "input_name": input_name,
                        "warning": "INPUT_NOT_DECLARED_IN_SCHEMA",
                    }
                )
                continue
            _validate_literal_value(node_id, class_type, input_name, value, input_schema, errors, warnings)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def _normalize_inputs(input_info: Any, input_order: Any) -> List[Dict[str, Any]]:
    if not isinstance(input_info, dict):
        return []
    inputs: List[Dict[str, Any]] = []
    for section in INPUT_SECTIONS:
        section_inputs = input_info.get(section, {})
        if not isinstance(section_inputs, dict):
            continue
        for name in _ordered_names(section_inputs, input_order.get(section, []) if isinstance(input_order, dict) else []):
            inputs.append(_normalize_input_schema(name, section, section_inputs[name]))
    return inputs


def _normalize_input_schema(name: str, section: str, spec: Any) -> Dict[str, Any]:
    input_type = "UNKNOWN"
    options: Optional[List[Any]] = None
    metadata: Dict[str, Any] = {}

    if isinstance(spec, list) and spec:
        first = spec[0]
        if isinstance(first, list):
            input_type = "COMBO"
            options = first
        else:
            input_type = str(first)
        if len(spec) > 1 and isinstance(spec[1], dict):
            metadata = dict(spec[1])
        elif len(spec) > 1 and isinstance(spec[1], list):
            options = spec[1]
    elif isinstance(spec, str):
        input_type = spec
    elif isinstance(spec, dict):
        metadata = dict(spec)
        input_type = str(metadata.pop("type", "UNKNOWN"))

    if options is None and isinstance(metadata.get("options"), list):
        options = metadata["options"]

    normalized = {
        "name": str(name),
        "section": section,
        "required": section == "required",
        "type": input_type,
        "default": metadata.get("default"),
        "min": metadata.get("min"),
        "max": metadata.get("max"),
        "step": metadata.get("step"),
        "tooltip": metadata.get("tooltip"),
        "options_count": len(options) if isinstance(options, list) else 0,
        "options_preview": options[:20] if isinstance(options, list) else None,
        "has_more_options": len(options) > 20 if isinstance(options, list) else False,
        "raw_metadata": metadata,
    }
    return normalized


def _normalize_outputs(raw_schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    output_types = raw_schema.get("output", [])
    output_names = raw_schema.get("output_name", [])
    output_is_list = raw_schema.get("output_is_list", [])
    tooltips = raw_schema.get("output_tooltips", [])

    outputs = []
    for index, output_type in enumerate(output_types if isinstance(output_types, list) else []):
        outputs.append(
            {
                "index": index,
                "type": str(output_type),
                "name": _value_at(output_names, index, str(output_type)),
                "is_list": bool(_value_at(output_is_list, index, False)),
                "tooltip": _value_at(tooltips, index, None),
            }
        )
    return outputs


def _validate_literal_value(
    node_id: str,
    class_type: str,
    input_name: str,
    value: Any,
    input_schema: Dict[str, Any],
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    if _is_link(value):
        return

    input_type = input_schema.get("type")
    if input_type == "COMBO" and input_schema.get("options_preview") is not None:
        options = input_schema.get("raw_metadata", {}).get("options")
        if isinstance(options, list) and value not in options:
            errors.append(
                {
                    "node_id": node_id,
                    "class_type": class_type,
                    "input_name": input_name,
                    "value": value,
                    "error": "VALUE_NOT_IN_OPTIONS",
                }
            )

    min_value = input_schema.get("min")
    max_value = input_schema.get("max")
    if isinstance(value, (int, float)):
        if isinstance(min_value, (int, float)) and value < min_value:
            errors.append({"node_id": node_id, "class_type": class_type, "input_name": input_name, "error": "VALUE_BELOW_MIN", "value": value, "min": min_value})
        if isinstance(max_value, (int, float)) and value > max_value:
            errors.append({"node_id": node_id, "class_type": class_type, "input_name": input_name, "error": "VALUE_ABOVE_MAX", "value": value, "max": max_value})


def _ordered_names(section_inputs: Dict[str, Any], order: Iterable[str]) -> List[str]:
    names = []
    seen = set()
    for name in order:
        if name in section_inputs and name not in seen:
            names.append(name)
            seen.add(name)
    for name in section_inputs:
        if name not in seen:
            names.append(name)
    return names


def _iter_nodes(workflow: Dict[str, Any]):
    for node_id, node in workflow.items():
        if isinstance(node, dict) and isinstance(node.get("inputs", {}), dict):
            yield str(node_id), node


def _value_at(values: Any, index: int, default: Any) -> Any:
    if isinstance(values, list) and index < len(values):
        return values[index]
    return default


def _is_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 2 and isinstance(value[0], str) and isinstance(value[1], int)
