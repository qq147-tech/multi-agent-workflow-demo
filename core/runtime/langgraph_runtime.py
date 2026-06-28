from __future__ import annotations

from workflow_models import WorkflowState


class LangGraphRuntimeAdapter:
    """Placeholder for a future LangGraph runtime.

    The current demo uses a direct Python state machine in `engine.py`. This adapter marks the
    seam where graph nodes, checkpoints, resumability, and interrupts should be introduced.
    """

    def run_node(self, node_name: str, state: WorkflowState) -> WorkflowState:
        state.log("runtime", f"LangGraph placeholder executed node {node_name}")
        return state
