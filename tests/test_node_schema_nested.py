from managers.node_schema import validate_workflow_against_schemas


def test_nested_input_namespace_is_accepted_when_parent_is_declared():
    workflow = {
        "1": {
            "class_type": "TextGenerate",
            "inputs": {
                "prompt": "hello",
                "sampling_mode.temperature": 0.8,
                "sampling_mode.top_k": 40,
            },
        }
    }
    object_info = {
        "TextGenerate": {
            "input": {
                "required": {
                    "prompt": ["STRING"],
                    "sampling_mode": ["SAMPLING_MODE"],
                }
            },
            "output": ["STRING"],
        }
    }

    result = validate_workflow_against_schemas(workflow, object_info)

    assert result["valid"] is True
    assert result["warning_count"] == 0
    assert result["nested_schema_input_count"] == 2
    assert {item["parent_input"] for item in result["nested_schema_inputs"]} == {"sampling_mode"}


def test_nested_input_namespace_warns_when_parent_is_not_declared():
    workflow = {
        "1": {
            "class_type": "TextGenerate",
            "inputs": {
                "prompt": "hello",
                "sampling_mode.temperature": 0.8,
            },
        }
    }
    object_info = {
        "TextGenerate": {
            "input": {"required": {"prompt": ["STRING"]}},
            "output": ["STRING"],
        }
    }

    result = validate_workflow_against_schemas(workflow, object_info)

    assert result["valid"] is True
    assert result["warning_count"] == 1
    assert result["nested_schema_input_count"] == 0
    assert result["warnings"][0]["input_name"] == "sampling_mode.temperature"
