from __future__ import annotations

from workflow_models import WorkflowState


class AgentMiddleware:
    """Hook point for logging, policy checks, tracing, and prompt enrichment."""

    def before_run(self, actor: str, state: WorkflowState) -> None:
        state.log("middleware", f"{actor} started")

    def after_run(self, actor: str, state: WorkflowState) -> None:
        state.log("middleware", f"{actor} finished")
