from managers.node_schema import (
    normalize_node_schema,
    normalize_workflow_schemas,
    validate_workflow_against_schemas,
)


def object_info():
    return {
        "LoadAudio": {
            "input": {
                "required": {
                    "audio": [
                        "COMBO",
                        {"options": ["a.wav", "b.wav"], "audio_upload": True},
                    ]
                }
            },
            "input_order": {"required": ["audio"]},
            "output": ["AUDIO"],
            "output_name": ["AUDIO"],
            "output_is_list": [False],
            "name": "LoadAudio",
            "display_name": "Load Audio",
            "category": "audio",
            "python_module": "comfy_extras.nodes_audio",
            "output_node": False,
        },
        "KSampler": {
            "input": {
                "required": {
                    "steps": ["INT", {"default": 20, "min": 1, "max": 100}],
                    "sampler_name": [["euler", "ddim"], {"tooltip": "Sampler"}],
                }
            },
            "input_order": {"required": ["steps", "sampler_name"]},
            "output": ["LATENT"],
            "output_name": ["LATENT"],
            "output_is_list": [False],
            "name": "KSampler",
            "display_name": "KSampler",
            "output_node": False,
        },
    }


def test_normalize_node_schema_extracts_inputs_outputs_and_metadata():
    schema = normalize_node_schema("KSampler", object_info()["KSampler"])

    assert schema["available"] is True
    assert schema["display_name"] == "KSampler"
    assert schema["inputs"][0]["name"] == "steps"
    assert schema["inputs"][0]["type"] == "INT"
    assert schema["inputs"][0]["default"] == 20
    assert schema["inputs"][0]["min"] == 1
    assert schema["inputs"][1]["type"] == "COMBO"
    assert schema["inputs"][1]["options_preview"] == ["euler", "ddim"]
    assert schema["outputs"][0]["type"] == "LATENT"


def test_normalize_workflow_schemas_reports_missing_classes():
    workflow = {
        "1": {"class_type": "LoadAudio", "inputs": {"audio": "a.wav"}},
        "2": {"class_type": "MissingNode", "inputs": {}},
    }

    result = normalize_workflow_schemas(workflow, object_info())

    assert result["class_count"] == 2
    assert result["missing_class_types"] == ["MissingNode"]
    assert result["schemas"]["LoadAudio"]["available"] is True
    assert result["schemas"]["MissingNode"]["available"] is False


def test_validate_workflow_against_schemas_catches_required_and_range_errors():
    workflow = {
        "1": {"class_type": "KSampler", "inputs": {"steps": 0, "sampler_name": "euler"}},
        "2": {"class_type": "KSampler", "inputs": {"steps": 20}},
        "3": {"class_type": "NoSuchNode", "inputs": {}},
    }

    validation = validate_workflow_against_schemas(workflow, object_info())

    assert validation["valid"] is False
    errors = {error["error"] for error in validation["errors"]}
    assert "VALUE_BELOW_MIN" in errors
    assert "REQUIRED_INPUT_MISSING" in errors
    assert "NODE_CLASS_NOT_FOUND" in errors
