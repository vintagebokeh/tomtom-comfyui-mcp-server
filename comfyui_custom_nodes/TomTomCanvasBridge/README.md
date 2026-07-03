# TomTom Canvas Bridge

Read-only ComfyUI frontend bridge for TomTom ComfyUI MCP Server.

The extension loads in the ComfyUI browser UI, reads the open canvas through
ComfyUI's frontend APIs, and posts snapshots to:

```text
/tomtom_canvas_bridge/state
```

The Python route writes the snapshot to:

```text
%USERPROFILE%\Documents\ComfyUI\user\default\workflows\.tomtom_canvas_bridge.json
```

Set `COMFY_MCP_CANVAS_BRIDGE_STATE` to override the output file path.

## Snapshot Fields

- `workflow`: API prompt graph used by MCP graph/schema tools.
- `ui_workflow`: ComfyUI UI workflow serialization for later canvas features.
- `selected_node_id` and `selected_node`: current frontend selection.
- `viewport`: canvas scale and offset.
- `revision` and `updated_at`: polling/event cursor for MCP clients.

This bridge is intentionally read-only. It does not click, drag, edit, queue,
or run workflows.
