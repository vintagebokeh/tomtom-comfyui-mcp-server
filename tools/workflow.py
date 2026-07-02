"""Workflow management tools for ComfyUI MCP Server"""

import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from managers.live_canvas import (
    canvas_event_subscription_info,
    current_canvas_state,
    execution_state,
    selected_node_state,
)
from managers.node_schema import (
    normalize_node_schema,
    normalize_workflow_schemas,
    validate_workflow_against_schemas,
)
from managers.workflow_edit import (
    WorkflowEditError,
    copy_workflow,
    diff_saved_workflows,
    edit_workflow_copy,
    plan_edits,
)
from managers.workflow_graph import WorkflowGraphInspector
from tools.helpers import register_and_build_response

logger = logging.getLogger("MCP_Server")


def register_workflow_tools(
    mcp: FastMCP,
    workflow_manager,
    comfyui_client,
    defaults_manager,
    asset_registry
):
    """Register workflow tools with the MCP server"""
    
    @mcp.tool()
    def list_workflows() -> dict:
        """List all available workflows in the workflow directory.
        
        Returns a catalog of workflows with their IDs, names, descriptions,
        available inputs, and optional metadata.
        """
        catalog = workflow_manager.get_workflow_catalog()
        return {
            "workflows": catalog,
            "count": len(catalog),
            "workflow_dir": str(workflow_manager.workflows_dir)
        }

    @mcp.tool()
    def get_live_canvas_state(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Read the current ComfyUI-visible canvas graph state.

        This is read-only. If ComfyUI is running or queueing a prompt, the tool
        returns graph data from the live queue payload. ComfyUI does not expose
        the currently open editor DOM/canvas through its normal HTTP API, so
        when the queue is idle this falls back to the most recently saved
        workflow and marks the source clearly.

        Args:
            include_nodes: Include compact node briefs in the graph payload.
            fallback_to_latest_saved: Return the latest saved workflow graph
                when no running/queued prompt graph is available.
        """
        return current_canvas_state(
            workflow_manager,
            comfyui_client,
            include_nodes=include_nodes,
            fallback_to_latest_saved=fallback_to_latest_saved,
        )

    @mcp.tool()
    def get_current_canvas(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Get the best available current canvas state.

        Priority order is canvas bridge state, ComfyUI queue execution graph,
        then latest saved workflow fallback. The response marks whether the
        data is a true live editor canvas or a saved/queue fallback.
        """
        return current_canvas_state(
            workflow_manager,
            comfyui_client,
            include_nodes=include_nodes,
            fallback_to_latest_saved=fallback_to_latest_saved,
        )

    @mcp.tool()
    def get_canvas_graph(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Return the current canvas graph from bridge/queue/saved fallback."""
        return get_current_canvas(include_nodes=include_nodes, fallback_to_latest_saved=fallback_to_latest_saved)

    @mcp.tool()
    def refresh_canvas(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Refresh and return the best available canvas state.

        Use this after saving in ComfyUI or after a future bridge reports a
        canvas update.
        """
        return get_current_canvas(include_nodes=include_nodes, fallback_to_latest_saved=fallback_to_latest_saved)

    @mcp.tool()
    def get_selected_node() -> dict:
        """Read the currently selected ComfyUI editor node from bridge state.

        This requires the optional TomTom canvas bridge. Without the bridge,
        ComfyUI's normal HTTP API does not expose editor selection state.
        """
        return selected_node_state(workflow_manager)

    @mcp.tool()
    def get_execution_state() -> dict:
        """Read ComfyUI queue execution state: idle, queued, or running."""
        try:
            return execution_state(comfyui_client)
        except Exception as e:
            logger.exception("Failed to get ComfyUI execution state")
            return {"status": "error", "source": "comfyui_queue", "error": str(e)}

    @mcp.tool()
    def subscribe_canvas_events() -> dict:
        """Return canvas bridge event subscription status.

        This request/response MCP server cannot hold a streaming event channel
        yet, so this returns bridge revision info and polling guidance.
        """
        return canvas_event_subscription_info(workflow_manager)

    @mcp.tool()
    def get_current_canvas_graph(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Alias for get_live_canvas_state."""
        return get_live_canvas_state(include_nodes=include_nodes, fallback_to_latest_saved=fallback_to_latest_saved)

    @mcp.tool()
    def read_live_canvas(include_nodes: bool = True, fallback_to_latest_saved: bool = True) -> dict:
        """Alias for get_live_canvas_state."""
        return get_live_canvas_state(include_nodes=include_nodes, fallback_to_latest_saved=fallback_to_latest_saved)

    @mcp.tool()
    def inspect_workflow_graph(workflow_id: str, include_nodes: bool = True) -> dict:
        """Inspect the full node graph for a saved ComfyUI workflow.

        Use this before editing or running unfamiliar workflows. It returns a
        compact graph summary, edges, output nodes, validation warnings, and
        optionally a list of node briefs.

        Args:
            workflow_id: The workflow ID (filename stem, e.g., "generate_image").
            include_nodes: Include a compact list of all nodes when True.

        Returns:
            Dict with graph summary, edges, validation, editable parameters,
            and optional node list.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        result = {
            "workflow_id": workflow_id,
            "summary": inspector.summary(),
            "edges": inspector.edges,
            "validation": inspector.validation(),
            "editable_parameters": inspector.editable_parameters(),
        }
        if include_nodes:
            result["nodes"] = inspector.node_list()
        return result

    @mcp.tool()
    def get_workflow_graph(workflow_id: str, include_nodes: bool = True) -> dict:
        """Alias for inspect_workflow_graph.

        This name is intentionally short and discoverable for clients that ask
        to get or read the graph for a saved ComfyUI workflow.
        """
        return inspect_workflow_graph(workflow_id, include_nodes=include_nodes)

    @mcp.tool()
    def inspect_workflow(workflow_id: str, include_nodes: bool = True) -> dict:
        """Alias for inspect_workflow_graph."""
        return inspect_workflow_graph(workflow_id, include_nodes=include_nodes)

    @mcp.tool()
    def read_workflow_graph(workflow_id: str, include_nodes: bool = True) -> dict:
        """Alias for inspect_workflow_graph."""
        return inspect_workflow_graph(workflow_id, include_nodes=include_nodes)

    @mcp.tool()
    def list_workflow_nodes(workflow_id: str, class_type: Optional[str] = None) -> dict:
        """List nodes in a saved ComfyUI workflow.

        Args:
            workflow_id: The workflow ID (filename stem).
            class_type: Optional case-insensitive class filter, such as
                "KSampler", "CLIPTextEncode", or "Checkpoint".

        Returns:
            Dict with matching node briefs.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        nodes = inspector.node_list(class_type=class_type)
        return {
            "workflow_id": workflow_id,
            "class_type_filter": class_type,
            "nodes": nodes,
            "count": len(nodes),
        }

    @mcp.tool()
    def get_workflow_nodes(workflow_id: str, class_type: Optional[str] = None) -> dict:
        """Alias for list_workflow_nodes."""
        return list_workflow_nodes(workflow_id, class_type=class_type)

    @mcp.tool()
    def get_node_details(workflow_id: str, node_id: str, include_neighbors: bool = True) -> dict:
        """Get detailed information for one workflow node.

        Args:
            workflow_id: The workflow ID (filename stem).
            node_id: ComfyUI node ID as a string or number.
            include_neighbors: Include incoming/outgoing edges and neighbor IDs.

        Returns:
            Dict with literal inputs, linked inputs, and optional graph neighbors.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        details = inspector.node_details(str(node_id), include_neighbors=include_neighbors)
        if not details:
            return {"error": f"Node '{node_id}' not found in workflow '{workflow_id}'"}
        details["workflow_id"] = workflow_id
        return details

    @mcp.tool()
    def get_node_schema(class_type: str) -> dict:
        """Get ComfyUI input/output schema for one node class.

        Returns normalized input sections, types, defaults, min/max, enum
        previews, output types, category, and python module from ComfyUI's
        /object_info endpoint.
        """
        try:
            object_info = comfyui_client.get_object_info(class_type)
            if class_type not in object_info:
                return {"class_type": class_type, "available": False, "error": "Node class not found in ComfyUI object_info"}
            return normalize_node_schema(class_type, object_info[class_type])
        except Exception as e:
            logger.exception("Failed to get node schema for %s", class_type)
            return {"class_type": class_type, "available": False, "error": str(e)}

    @mcp.tool()
    def inspect_workflow_schemas(workflow_id: str) -> dict:
        """Inspect input/output schemas for every node class used by a workflow."""
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}
        try:
            object_info = comfyui_client.get_object_info()
            result = normalize_workflow_schemas(workflow, object_info)
            result["workflow_id"] = workflow_id
            return result
        except Exception as e:
            logger.exception("Failed to inspect workflow schemas for %s", workflow_id)
            return {"workflow_id": workflow_id, "error": str(e)}

    @mcp.tool()
    def validate_workflow_schema(workflow_id: str) -> dict:
        """Validate a workflow against ComfyUI node class schemas.

        This catches missing node classes, missing required inputs, undeclared
        inputs, and basic literal value range/enum issues. It complements
        validate_workflow_graph, which validates graph connectivity.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}
        try:
            object_info = comfyui_client.get_object_info()
            result = validate_workflow_against_schemas(workflow, object_info)
            result["workflow_id"] = workflow_id
            return result
        except Exception as e:
            logger.exception("Failed to validate workflow schema for %s", workflow_id)
            return {"workflow_id": workflow_id, "valid": False, "error": str(e)}

    @mcp.tool()
    def plan_workflow_edit(workflow_id: str, edits: List[Dict[str, Any]]) -> dict:
        """Dry-run workflow JSON edits and return a diff without writing files.

        Supported operations:
        - set_node_position: {node_id, position: [x, y]}
        - set_node_title: {node_id, title}
        - set_node_input: {node_id, input_name, value}
        - set_node_ui_field: {node_id, field, value} for allowlisted UI fields
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"workflow_id": workflow_id, "error": f"Workflow '{workflow_id}' not found"}
        try:
            result = plan_edits(workflow, edits)
            result["workflow_id"] = workflow_id
            return result
        except WorkflowEditError as e:
            return {"workflow_id": workflow_id, "status": "rejected", "error": str(e)}

    @mcp.tool()
    def copy_workflow_for_edit(workflow_id: str, new_workflow_id: Optional[str] = None) -> dict:
        """Copy a workflow to a new *_ai_edit* JSON file before editing."""
        try:
            return copy_workflow(workflow_manager, workflow_id, new_workflow_id=new_workflow_id)
        except WorkflowEditError as e:
            return {"workflow_id": workflow_id, "status": "rejected", "error": str(e)}
        except Exception as e:
            logger.exception("Failed to copy workflow %s", workflow_id)
            return {"workflow_id": workflow_id, "status": "error", "error": str(e)}

    @mcp.tool()
    def edit_workflow_json(
        workflow_id: str,
        edits: List[Dict[str, Any]],
        require_ai_edit_copy: bool = True,
        validate_after: bool = True,
    ) -> dict:
        """Apply edits to a saved workflow copy and optionally validate it.

        By default this refuses to edit workflows whose ID does not include
        '_ai_edit', so agents practice on a copied workflow first.
        """
        try:
            result = edit_workflow_copy(
                workflow_manager,
                workflow_id,
                edits,
                require_ai_edit_copy=require_ai_edit_copy,
            )
            if validate_after:
                result["post_validation"] = _validate_graph_and_schema(workflow_id)
            return result
        except WorkflowEditError as e:
            return {"workflow_id": workflow_id, "status": "rejected", "error": str(e)}
        except Exception as e:
            logger.exception("Failed to edit workflow %s", workflow_id)
            return {"workflow_id": workflow_id, "status": "error", "error": str(e)}

    @mcp.tool()
    def diff_workflows(base_workflow_id: str, edited_workflow_id: str) -> dict:
        """Compare two saved workflows and return compact node-level changes."""
        try:
            return diff_saved_workflows(workflow_manager, base_workflow_id, edited_workflow_id)
        except WorkflowEditError as e:
            return {"status": "rejected", "error": str(e)}
        except Exception as e:
            logger.exception("Failed to diff workflows %s and %s", base_workflow_id, edited_workflow_id)
            return {"status": "error", "error": str(e)}

    @mcp.tool()
    def validate_workflow_edit(workflow_id: str) -> dict:
        """Run graph and schema validation for an edited workflow."""
        return _validate_graph_and_schema(workflow_id)

    @mcp.tool()
    def trace_node_inputs(workflow_id: str, node_id: str, max_depth: int = 3) -> dict:
        """Trace upstream nodes that feed into a workflow node.

        Args:
            workflow_id: The workflow ID (filename stem).
            node_id: ComfyUI node ID as a string or number.
            max_depth: Maximum upstream depth to traverse, capped at 10.

        Returns:
            Dict with upstream nodes and edges.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        result = inspector.trace_inputs(str(node_id), max_depth=max_depth)
        result["workflow_id"] = workflow_id
        return result

    @mcp.tool()
    def trace_node_outputs(workflow_id: str, node_id: str, max_depth: int = 3) -> dict:
        """Trace downstream nodes that consume a workflow node's output.

        Args:
            workflow_id: The workflow ID (filename stem).
            node_id: ComfyUI node ID as a string or number.
            max_depth: Maximum downstream depth to traverse, capped at 10.

        Returns:
            Dict with downstream nodes and edges.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        result = inspector.trace_outputs(str(node_id), max_depth=max_depth)
        result["workflow_id"] = workflow_id
        return result

    @mcp.tool()
    def suggest_editable_parameters(workflow_id: str) -> dict:
        """Suggest workflow parameters that are safe for AI edits.

        This detects explicit PARAM_* placeholders and reports their node/input
        bindings. It is safer than guessing arbitrary node inputs.

        Args:
            workflow_id: The workflow ID (filename stem).

        Returns:
            Dict with editable parameter bindings.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        parameters = inspector.editable_parameters()
        return {
            "workflow_id": workflow_id,
            "editable_parameters": parameters,
            "count": len(parameters),
        }

    @mcp.tool()
    def validate_workflow_graph(workflow_id: str) -> dict:
        """Validate basic graph integrity for a saved ComfyUI workflow.

        Checks whether linked inputs point to existing source nodes and reports
        isolated nodes and obvious missing output nodes.

        Args:
            workflow_id: The workflow ID (filename stem).

        Returns:
            Dict with validity, warnings, and graph summary.
        """
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        return {
            "workflow_id": workflow_id,
            "summary": inspector.summary(),
            "validation": inspector.validation(),
        }

    def _validate_graph_and_schema(workflow_id: str) -> dict:
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"workflow_id": workflow_id, "valid": False, "error": f"Workflow '{workflow_id}' not found"}

        inspector = WorkflowGraphInspector(workflow)
        graph_validation = inspector.validation()
        try:
            object_info = comfyui_client.get_object_info()
            schema_validation = validate_workflow_against_schemas(workflow, object_info)
        except Exception as e:
            logger.warning("Schema validation failed for %s: %s", workflow_id, e)
            schema_validation = {"valid": False, "error": str(e)}

        return {
            "workflow_id": workflow_id,
            "valid": bool(graph_validation.get("valid")) and bool(schema_validation.get("valid")),
            "graph_validation": graph_validation,
            "schema_validation": schema_validation,
        }

    @mcp.tool()
    def run_workflow(
        workflow_id: str,
        overrides: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
        return_inline_preview: bool = False
    ) -> dict:
        """Run a saved ComfyUI workflow with constrained parameter overrides.
        
        Args:
            workflow_id: The workflow ID (filename stem, e.g., "generate_image")
            overrides: Optional dict of parameter overrides (e.g., {"prompt": "a cat", "width": 1024})
            options: Optional dict of execution options (reserved for future use)
            return_inline_preview: If True, include a small thumbnail base64 in response (256px, ~100KB)
        
        Returns:
            Result with asset_url, workflow_id, and execution metadata. If return_inline_preview=True,
            also includes inline_preview_base64 for immediate viewing.
        """
        if overrides is None:
            overrides = {}
        
        # Load workflow
        workflow = workflow_manager.load_workflow(workflow_id)
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}
        
        try:
            # Apply overrides with constraints
            workflow = workflow_manager.apply_workflow_overrides(
                workflow, workflow_id, overrides, defaults_manager
            )

            # Extract and remove override report before submitting to ComfyUI
            override_report = workflow.pop("__override_report__", None)

            # Determine output preferences
            output_preferences = workflow_manager._guess_output_preferences(workflow)

            # Execute workflow
            result = comfyui_client.run_custom_workflow(
                workflow,
                preferred_output_keys=output_preferences,
            )

            # Register asset and build response
            response = register_and_build_response(
                result,
                workflow_id,
                asset_registry,
                tool_name=None,
                return_inline_preview=return_inline_preview,
                session_id=None
            )

            # Include override report so the agent can see what was applied/dropped
            if override_report and override_report.get("overrides_dropped"):
                response["overrides_applied"] = override_report["overrides_applied"]
                response["overrides_dropped"] = override_report["overrides_dropped"]

            return response
        except Exception as exc:
            logger.exception("Workflow '%s' failed", workflow_id)
            return {"error": str(exc)}
