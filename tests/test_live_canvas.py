import json
from pathlib import Path

from managers.live_canvas import latest_saved_canvas, queue_canvas_states


def sample_workflow():
    return {
        "1": {"class_type": "LoadAudio", "inputs": {"audio": "input.wav"}},
        "2": {"class_type": "PreviewAudio", "inputs": {"audio": ["1", 0]}},
    }


def test_queue_canvas_states_extracts_prompt_graph_from_comfyui_queue_shape():
    queue_data = {
        "queue_running": [[12, "prompt-1", sample_workflow(), {"client_id": "abc"}, ["2"]]],
        "queue_pending": [],
    }

    canvases = queue_canvas_states(queue_data, include_nodes=True)

    assert len(canvases) == 1
    assert canvases[0]["source"] == "queue_running"
    assert canvases[0]["prompt_id"] == "prompt-1"
    assert canvases[0]["summary"]["node_count"] == 2
    assert canvases[0]["summary"]["output_nodes"][0]["id"] == "2"
    assert canvases[0]["nodes"][0]["id"] == "1"


def test_queue_canvas_states_ignores_items_without_workflow_graph():
    queue_data = {
        "queue_running": [[12, "prompt-1", {"not": "a workflow"}]],
        "queue_pending": [],
    }

    assert queue_canvas_states(queue_data) == []


class FakeWorkflowManager:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = workflows_dir

    def load_workflow(self, workflow_id):
        workflow_path = self.workflows_dir / f"{workflow_id}.json"
        return json.loads(workflow_path.read_text(encoding="utf-8"))


def test_latest_saved_canvas_uses_most_recent_workflow(tmp_path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps({"1": {"class_type": "PreviewAny", "inputs": {}}}), encoding="utf-8")
    new_path.write_text(json.dumps(sample_workflow()), encoding="utf-8")

    canvas = latest_saved_canvas(FakeWorkflowManager(tmp_path), include_nodes=False)

    assert canvas["source"] == "latest_saved_workflow"
    assert canvas["workflow_id"] == "new"
    assert canvas["summary"]["node_count"] == 2
    assert "nodes" not in canvas
