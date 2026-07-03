import json
from pathlib import Path

from managers.live_canvas import (
    canvas_event_subscription_info,
    canvas_snapshot,
    canvas_snapshot_history,
    current_canvas_state,
    diff_canvas_snapshots,
    execution_state,
    latest_saved_canvas,
    queue_canvas_states,
    selected_node_state,
)


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


class FakeComfyUIClient:
    def __init__(self, queue_data):
        self.queue_data = queue_data

    def get_queue(self):
        return self.queue_data


def test_current_canvas_state_prefers_bridge_state(tmp_path, monkeypatch):
    bridge_path = tmp_path / "bridge.json"
    bridge_path.write_text(
        json.dumps(
            {
                "bridge_version": "0.1",
                "revision": 7,
                "workflow_id": "open_workflow",
                "workflow_name": "Open Workflow",
                "saved": False,
                "modified": True,
                "selected_node_id": "2",
                "workflow": sample_workflow(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COMFY_MCP_CANVAS_BRIDGE_STATE", str(bridge_path))

    state = current_canvas_state(
        FakeWorkflowManager(tmp_path),
        FakeComfyUIClient({"queue_running": [[1, "prompt", sample_workflow()]], "queue_pending": []}),
    )

    assert state["source"] == "canvas_bridge"
    assert state["is_live_ui_canvas"] is True
    assert state["canvases"][0]["workflow_id"] == "open_workflow"
    assert state["canvases"][0]["modified"] is True
    assert state["canvases"][0]["selected_node"]["id"] == "2"
    assert state["canvases"][0]["selected_node"]["class_type"] == "PreviewAudio"


def test_current_canvas_state_falls_back_to_queue_when_no_bridge(tmp_path, monkeypatch):
    monkeypatch.delenv("COMFY_MCP_CANVAS_BRIDGE_STATE", raising=False)

    state = current_canvas_state(
        FakeWorkflowManager(tmp_path),
        FakeComfyUIClient({"queue_running": [[1, "prompt-1", sample_workflow()]], "queue_pending": []}),
    )

    assert state["source"] == "comfyui_queue"
    assert state["is_live_execution_graph"] is True
    assert state["canvases"][0]["prompt_id"] == "prompt-1"


def test_selected_node_state_reports_unavailable_without_bridge(tmp_path, monkeypatch):
    monkeypatch.delenv("COMFY_MCP_CANVAS_BRIDGE_STATE", raising=False)

    state = selected_node_state(FakeWorkflowManager(tmp_path))

    assert state["status"] == "unavailable"
    assert state["selected_node"] is None


def test_execution_state_reports_running_queue():
    state = execution_state(FakeComfyUIClient({"queue_running": [[1, "prompt-1", sample_workflow()]], "queue_pending": []}))

    assert state["status"] == "success"
    assert state["state"] == "running"
    assert state["running_count"] == 1


def test_canvas_event_subscription_info_without_bridge(tmp_path, monkeypatch):
    monkeypatch.delenv("COMFY_MCP_CANVAS_BRIDGE_STATE", raising=False)

    state = canvas_event_subscription_info(FakeWorkflowManager(tmp_path))

    assert state["status"] == "not_configured"
    assert "refresh_canvas" in state["poll_tools"]


def write_snapshot(history_dir: Path, revision: int, workflow: dict, selected_node_id: str | None = None):
    payload = {
        "snapshot_id": f"rev-{revision}",
        "revision": revision,
        "updated_at": f"2026-07-03T00:00:0{revision}Z",
        "workflow_id": "live_workflow",
        "workflow_name": "Live Workflow",
        "selected_node_id": selected_node_id,
        "workflow": workflow,
    }
    path = history_dir / f"rev-{revision}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_canvas_snapshot_history_lists_recent_snapshots(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    monkeypatch.setenv("COMFY_MCP_CANVAS_BRIDGE_HISTORY_DIR", str(history_dir))
    write_snapshot(history_dir, 1, sample_workflow(), "1")
    write_snapshot(history_dir, 2, sample_workflow(), "2")

    history = canvas_snapshot_history(FakeWorkflowManager(tmp_path), limit=10)

    assert history["status"] == "success"
    assert history["count"] == 2
    assert history["snapshots"][0]["revision"] == 1
    assert history["snapshots"][1]["revision"] == 2


def test_canvas_snapshot_gets_latest_without_full_workflow(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    monkeypatch.setenv("COMFY_MCP_CANVAS_BRIDGE_HISTORY_DIR", str(history_dir))
    write_snapshot(history_dir, 1, sample_workflow(), "1")
    write_snapshot(history_dir, 2, sample_workflow(), "2")

    snapshot = canvas_snapshot(FakeWorkflowManager(tmp_path))

    assert snapshot["status"] == "success"
    assert snapshot["revision"] == 2
    assert snapshot["selected_node"]["id"] == "2"
    assert "workflow" not in snapshot


def test_diff_canvas_snapshots_reports_node_changes(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    monkeypatch.setenv("COMFY_MCP_CANVAS_BRIDGE_HISTORY_DIR", str(history_dir))
    first = sample_workflow()
    second = dict(sample_workflow())
    second["3"] = {"class_type": "SaveAudio", "inputs": {"audio": ["2", 0]}}
    write_snapshot(history_dir, 1, first, "1")
    write_snapshot(history_dir, 2, second, "3")

    diff = diff_canvas_snapshots(FakeWorkflowManager(tmp_path), base_revision=1, target_revision=2)

    assert diff["status"] == "success"
    assert diff["node_count_delta"] == 1
    assert diff["edge_count_delta"] == 1
    assert diff["added_node_ids"] == ["3"]
    assert diff["selected_node_changed"] is True
