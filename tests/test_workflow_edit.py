import json
from pathlib import Path

import pytest

from managers.workflow_edit import (
    WorkflowEditError,
    copy_workflow,
    diff_saved_workflows,
    edit_workflow_copy,
    plan_edits,
)


class FakeWorkflowManager:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = workflows_dir

    def _safe_workflow_path(self, workflow_id: str):
        safe_id = workflow_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        path = (self.workflows_dir / f"{safe_id}.json").resolve()
        if not path.exists():
            return None
        path.relative_to(self.workflows_dir.resolve())
        return path


def sample_workflow():
    return {
        "1": {
            "class_type": "LoadAudio",
            "_meta": {"title": "Load Audio"},
            "inputs": {"audio": "voice.wav"},
            "pos": [10, 20],
        },
        "2": {
            "class_type": "PreviewAudio",
            "_meta": {"title": "Preview Audio"},
            "inputs": {"audio": ["1", 0]},
            "pos": [300, 20],
        },
    }


def write_workflow(tmp_path, workflow_id, workflow=None):
    path = tmp_path / f"{workflow_id}.json"
    path.write_text(json.dumps(workflow or sample_workflow()), encoding="utf-8")
    return path


def test_plan_edits_returns_diff_without_mutating_workflow():
    workflow = sample_workflow()

    result = plan_edits(
        workflow,
        [
            {"operation": "set_node_position", "node_id": "2", "position": [420, 100]},
            {"operation": "set_node_title", "node_id": "2", "title": "Preview Cloned Audio"},
        ],
    )

    assert result["will_write"] is False
    assert workflow["2"]["pos"] == [300, 20]
    paths = {change["path"] for change in result["diff"]}
    assert "pos" in paths
    assert "_meta.title" in paths


def test_copy_workflow_creates_editable_copy(tmp_path):
    write_workflow(tmp_path, "voice")
    manager = FakeWorkflowManager(tmp_path)

    result = copy_workflow(manager, "voice", "voice_ai_edit_test")

    assert result["new_workflow_id"] == "voice_ai_edit_test"
    assert (tmp_path / "voice_ai_edit_test.json").exists()
    assert json.loads((tmp_path / "voice_ai_edit_test.json").read_text(encoding="utf-8")) == sample_workflow()


def test_edit_workflow_copy_refuses_original_by_default(tmp_path):
    write_workflow(tmp_path, "voice")
    manager = FakeWorkflowManager(tmp_path)

    with pytest.raises(WorkflowEditError):
        edit_workflow_copy(
            manager,
            "voice",
            [{"operation": "set_node_title", "node_id": "2", "title": "Unsafe"}],
        )


def test_edit_workflow_copy_writes_copy_and_diff(tmp_path):
    write_workflow(tmp_path, "voice_ai_edit_test")
    manager = FakeWorkflowManager(tmp_path)

    result = edit_workflow_copy(
        manager,
        "voice_ai_edit_test",
        [
            {"operation": "set_node_position", "node_id": "2", "position": [420, 100]},
            {"operation": "set_node_input", "node_id": "1", "input_name": "audio", "value": "new.wav"},
        ],
    )

    edited = json.loads((tmp_path / "voice_ai_edit_test.json").read_text(encoding="utf-8"))
    assert result["status"] == "edited"
    assert edited["2"]["pos"] == [420, 100]
    assert edited["1"]["inputs"]["audio"] == "new.wav"
    paths = {change["path"] for change in result["diff"]}
    assert "pos" in paths
    assert "inputs.audio" in paths


def test_diff_saved_workflows_reports_node_changes(tmp_path):
    write_workflow(tmp_path, "voice")
    edited = sample_workflow()
    edited["2"]["_meta"]["title"] = "Preview Cloned Audio"
    write_workflow(tmp_path, "voice_ai_edit_test", edited)
    manager = FakeWorkflowManager(tmp_path)

    result = diff_saved_workflows(manager, "voice", "voice_ai_edit_test")

    assert result["diff"][0]["node_id"] == "2"
    assert result["diff"][0]["path"] == "_meta.title"
