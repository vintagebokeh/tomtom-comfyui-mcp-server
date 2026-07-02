from managers.workflow_graph import WorkflowGraphInspector


def sample_workflow():
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "_meta": {"title": "Load Checkpoint"},
            "inputs": {"ckpt_name": "PARAM_MODEL"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "Positive Prompt"},
            "inputs": {"clip": ["1", 1], "text": "PARAM_PROMPT"},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["1", 0], "positive": ["2", 0], "steps": "PARAM_INT_STEPS"},
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {"images": ["3", 0], "filename_prefix": "test"},
        },
    }


def test_inspector_builds_edges_and_summary():
    inspector = WorkflowGraphInspector(sample_workflow())

    summary = inspector.summary()

    assert summary["node_count"] == 4
    assert summary["edge_count"] == 4
    assert summary["has_missing_sources"] is False
    assert summary["output_nodes"][0]["id"] == "4"


def test_output_nodes_are_terminal_output_like_nodes():
    workflow = {
        "3": {
            "class_type": "LoadAudio",
            "_meta": {"title": "Load Audio"},
            "inputs": {"audio": "input.wav"},
        },
        "4": {
            "class_type": "PreviewAudio",
            "_meta": {"title": "Preview Audio"},
            "inputs": {"audio": ["3", 0]},
        },
    }
    inspector = WorkflowGraphInspector(workflow)

    output_nodes = inspector.summary()["output_nodes"]

    assert [node["id"] for node in output_nodes] == ["4"]


def test_inspector_reports_node_details():
    inspector = WorkflowGraphInspector(sample_workflow())

    details = inspector.node_details("3")

    assert details["class_type"] == "KSampler"
    assert details["linked_input_count"] == 2
    assert details["literal_input_count"] == 1
    assert set(details["upstream_node_ids"]) == {"1", "2"}
    assert details["downstream_node_ids"] == ["4"]


def test_inspector_traces_upstream_inputs():
    inspector = WorkflowGraphInspector(sample_workflow())

    trace = inspector.trace_inputs("4", max_depth=3)
    traced_ids = {node["id"] for node in trace["nodes"]}

    assert traced_ids == {"1", "2", "3", "4"}
    assert trace["direction"] == "upstream"


def test_inspector_detects_editable_parameters():
    inspector = WorkflowGraphInspector(sample_workflow())

    params = inspector.editable_parameters()
    names = {param["parameter"] for param in params}

    assert names == {"model", "prompt", "steps"}


def test_inspector_validates_missing_source_edge():
    workflow = sample_workflow()
    workflow["4"]["inputs"]["images"] = ["999", 0]
    inspector = WorkflowGraphInspector(workflow)

    validation = inspector.validation()

    assert validation["valid"] is False
    assert validation["missing_source_edges"][0]["source_id"] == "999"
