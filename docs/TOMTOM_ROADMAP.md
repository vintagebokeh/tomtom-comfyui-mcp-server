# TomTom ComfyUI MCP Roadmap

This fork is evolving the original ComfyUI MCP server from an execution-only
tool into a workflow-engineering assistant for ChatGPT, Codex, and other MCP
clients.

## Current Capability Levels

1. Workflow catalog: done.
2. Model catalog: done.
3. Queue and job visibility: done.
4. Run saved workflows: done.
5. View generated images through MCP: done.
6. Regenerate and parameter overrides: partially done.
7. Read full workflow node graph: started in this fork.
8. See live ComfyUI canvas: planned.
9. Click, drag, and edit nodes in the UI: planned.

## Level 7: Workflow Graph Intelligence

Implemented tools:

- `inspect_workflow_graph`
- `list_workflow_nodes`
- `get_node_details`
- `trace_node_inputs`
- `trace_node_outputs`
- `suggest_editable_parameters`
- `validate_workflow_graph`

These tools inspect workflow JSON files and expose node classes, titles, input
links, literal parameters, graph edges, output nodes, editable `PARAM_*`
bindings, and graph integrity warnings.

## Level 8: Live Canvas Awareness

The saved workflow file is not the same as the currently open ComfyUI canvas.
To make the AI see the live canvas reliably, this fork should add a small
ComfyUI frontend or backend extension that exposes a safe local API:

- `GET /tomtom/canvas/current`
- `GET /tomtom/canvas/screenshot`
- `GET /tomtom/canvas/selection`
- `GET /tomtom/canvas/open-workflow`

The MCP server can then call that bridge and expose:

- `get_current_canvas_state`
- `capture_canvas_screenshot`
- `get_selected_canvas_nodes`
- `compare_canvas_to_workflow_file`

## Level 9: Safe Canvas Control

Direct desktop clicking is fragile. The preferred design is a ComfyUI bridge
that edits the graph model and lets ComfyUI update the UI. Every write action
should require a snapshot and return a diff.

Planned tools:

- `save_canvas_snapshot`
- `add_canvas_node`
- `move_canvas_node`
- `connect_canvas_nodes`
- `disconnect_canvas_input`
- `delete_canvas_node`
- `apply_canvas_patch`
- `undo_canvas_edit`

Safety requirements:

- Never edit the canvas without a snapshot.
- Validate graph links before applying changes.
- Return a before/after diff for every write.
- Separate read-only tools from write tools with scopes or API keys.
- Add confirmation gates for destructive edits.

## Product Direction

Long term, every TomTomLife app should expose both:

- a normal API for existing software integrations
- an MCP server for AI-native interaction

The API remains the system contract. MCP becomes the AI control and reasoning
contract.
