import json
from pathlib import Path

from managers.canvas_intelligence import (
    explain_selected_canvas_node,
    live_canvas_graph_insight,
    live_canvas_suggestions,
)


class FakeWorkflowManager:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = workflows_dir


class FakeComfyUIClient:
    def get_object_info(self):
        return {
            "LoadAudio": {
                "input": {"required": {"audio": ["STRING", {"default": ""}]}},
                "output": ["AUDIO"],
                "output_name": ["audio"],
                "category": "audio",
            },
            "PreviewAudio": {
                "input": {"required": {"audio": ["AUDIO"]}},
                "output": [],
                "output_node": True,
                "category": "audio",
            },
            "UnusedNode": {
                "input": {"required": {"value": ["STRING"]}},
                "output": ["STRING"],
                "category": "test",
            },
        }


def sample_workflow():
    return {
        "1": {"class_type": "LoadAudio", "inputs": {"audio": "input.wav"}, "_meta": {"title": "Load Audio"}},
        "2": {"class_type": "PreviewAudio", "inputs": {"audio": ["1", 0]}, "_meta": {"title": "Preview Audio"}},
    }


def write_bridge_state(tmp_path: Path, workflow: dict, selected_node_id: str | None, monkeypatch):
    bridge_path = tmp_path / ".tomtom_canvas_bridge.json"
    bridge_path.write_text(
        json.dumps(
            {
                "bridge_version": "0.1",
                "revision": 3,
                "workflow_id": "live_test",
                "workflow_name": "Live Test",
                "selected_node_id": selected_node_id,
                "workflow": workflow,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COMFY_MCP_CANVAS_BRIDGE_STATE", str(bridge_path))
    return bridge_path


def test_explain_selected_canvas_node_uses_schema_and_neighbors(tmp_path, monkeypatch):
    write_bridge_state(tmp_path, sample_workflow(), "2", monkeypatch)

    result = explain_selected_canvas_node(FakeWorkflowManager(tmp_path), FakeComfyUIClient())

    assert result["status"] == "success"
    assert result["selected_node"]["id"] == "2"
    assert result["schema"]["is_output_node"] is True
    assert result["incoming_edges"][0]["source_id"] == "1"
    assert "AUDIO" in result["explanation"]["input_types"]


def test_live_canvas_graph_insight_reports_sections(tmp_path, monkeypatch):
    write_bridge_state(tmp_path, sample_workflow(), "2", monkeypatch)

    result = live_canvas_graph_insight(FakeWorkflowManager(tmp_path), FakeComfyUIClient())

    assert result["status"] == "success"
    assert result["summary"]["node_count"] == 2
    assert result["component_count"] == 1
    assert result["sections"][0]["node_count"] == 2
    assert result["terminal_nodes"][0]["id"] == "2"


def test_live_canvas_suggestions_reports_isolated_node(tmp_path, monkeypatch):
    workflow = sample_workflow()
    workflow["3"] = {"class_type": "UnusedNode", "inputs": {"value": "orphan"}, "_meta": {"title": "Unused"}}
    write_bridge_state(tmp_path, workflow, "3", monkeypatch)

    result = live_canvas_suggestions(FakeWorkflowManager(tmp_path), FakeComfyUIClient())

    assert result["status"] == "success"
    assert any(item["kind"] == "isolated_node" for item in result["suggestions"])
