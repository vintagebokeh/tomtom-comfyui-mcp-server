"""Workflow management tools for ComfyUI MCP Server"""

import logging
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP
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
