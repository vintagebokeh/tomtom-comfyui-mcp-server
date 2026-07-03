import { app } from "/scripts/app.js";

const BRIDGE_ENDPOINT = "/tomtom_canvas_bridge/state";
const PUBLISH_INTERVAL_MS = 1500;

let revision = 0;
let lastSignature = "";
let publishTimer = null;
let intervalStarted = false;

function selectedNodes() {
  const selected = app.canvas?.selected_nodes;
  if (!selected) {
    return [];
  }

  if (Array.isArray(selected)) {
    return selected.filter(Boolean);
  }

  return Object.values(selected).filter(Boolean);
}

function compactSelectedNode(node) {
  if (!node) {
    return null;
  }

  return {
    id: String(node.id),
    type: node.type ?? null,
    title: node.title ?? node.type ?? null,
    pos: Array.isArray(node.pos) ? [node.pos[0], node.pos[1]] : null,
    size: Array.isArray(node.size) ? [node.size[0], node.size[1]] : null,
  };
}

function canvasViewport() {
  const ds = app.canvas?.ds;
  return {
    scale: ds?.scale ?? null,
    offset: Array.isArray(ds?.offset) ? [ds.offset[0], ds.offset[1]] : null,
  };
}

function graphStats(workflow) {
  const nodes = workflow && typeof workflow === "object" ? Object.values(workflow) : [];
  let edgeCount = 0;

  for (const node of nodes) {
    const inputs = node && typeof node === "object" ? node.inputs : null;
    if (!inputs || typeof inputs !== "object") {
      continue;
    }
    for (const value of Object.values(inputs)) {
      if (Array.isArray(value) && value.length >= 2) {
        edgeCount += 1;
      }
    }
  }

  return {
    node_count: nodes.length,
    edge_count: edgeCount,
  };
}

async function graphToPrompt() {
  if (typeof app.graphToPrompt !== "function") {
    return { workflow: {}, ui_workflow: app.graph?.serialize?.() ?? null };
  }

  const prompt = await app.graphToPrompt();
  return {
    workflow: prompt?.output ?? prompt?.prompt ?? {},
    ui_workflow: prompt?.workflow ?? app.graph?.serialize?.() ?? null,
  };
}

function currentWorkflowName() {
  const manager = app.workflowManager;
  return (
    manager?.activeWorkflow?.name ??
    manager?.activeWorkflow?.filename ??
    app.graph?._filename ??
    document.title ??
    "ComfyUI Canvas"
  );
}

async function buildPayload(reason) {
  const { workflow, ui_workflow } = await graphToPrompt();
  const selected = selectedNodes();
  const selectedNode = compactSelectedNode(selected[0]);
  const name = currentWorkflowName();
  const stats = graphStats(workflow);

  return {
    bridge_version: "0.1",
    revision: revision + 1,
    updated_at: new Date().toISOString(),
    reason,
    workflow_id: String(name || "current_workflow").replace(/\.[^.]+$/, ""),
    workflow_name: name,
    saved: null,
    modified: null,
    selected_node_id: selectedNode?.id ?? null,
    selected_node: selectedNode,
    selected_node_ids: selected.map((node) => String(node.id)),
    viewport: canvasViewport(),
    graph_stats: stats,
    workflow,
    ui_workflow,
  };
}

function payloadSignature(payload) {
  return JSON.stringify({
    selected_node_ids: payload.selected_node_ids,
    viewport: payload.viewport,
    graph_stats: payload.graph_stats,
    workflow: payload.workflow,
  });
}

async function publish(reason = "poll") {
  try {
    const payload = await buildPayload(reason);
    const signature = payloadSignature(payload);
    if (signature === lastSignature) {
      return;
    }

    payload.revision = ++revision;
    lastSignature = signature;

    await fetch(BRIDGE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    console.debug("[TomTomCanvasBridge] publish failed", error);
  }
}

function schedulePublish(reason) {
  if (publishTimer) {
    clearTimeout(publishTimer);
  }
  publishTimer = setTimeout(() => publish(reason), 150);
}

function startPolling() {
  if (intervalStarted) {
    return;
  }

  intervalStarted = true;
  publish("startup");
  setInterval(() => publish("interval"), PUBLISH_INTERVAL_MS);

  window.addEventListener("mouseup", () => schedulePublish("mouseup"), true);
  window.addEventListener("keyup", () => schedulePublish("keyup"), true);
  window.addEventListener("visibilitychange", () => schedulePublish("visibilitychange"), true);
}

app.registerExtension({
  name: "TomTom.CanvasBridge",
  async setup() {
    startPolling();
    window.tomtomCanvasBridge = {
      publish,
      endpoint: BRIDGE_ENDPOINT,
    };
    console.info("[TomTomCanvasBridge] ready");
  },
});
