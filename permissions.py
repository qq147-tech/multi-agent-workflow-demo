from __future__ import annotations

from dataclasses import dataclass

from workflow_models import Artifact, WorkflowState


WRITE_PERMISSIONS: dict[str, set[Artifact]] = {
    "design_agent": {
        Artifact.REPO_SUMMARY,
        Artifact.CLARIFICATION_QUESTION,
        Artifact.CLARIFICATION_HISTORY,
        Artifact.REQUIREMENT_ANALYSIS,
        Artifact.DESIGN_DOC,
        Artifact.DESIGN_REVIEW_DECISIONS,
    },
    "design_review_agent": {Artifact.DESIGN_REVIEW_REPORT},
    "develop_agent": {
        Artifact.DEVELOPMENT_PLAN,
        Artifact.GENERATED_FILES,
        Artifact.DT_TESTS,
        Artifact.SELF_TEST_REPORT,
        Artifact.REVIEW_DECISIONS,
    },
    "review_agent": {Artifact.REVIEW_REPORT},
}


READ_PERMISSIONS: dict[str, set[Artifact]] = {
    "design_agent": set(Artifact),
    "develop_agent": {
        Artifact.REPO_SUMMARY,
        Artifact.CLARIFICATION_HISTORY,
        Artifact.REQUIREMENT_ANALYSIS,
        Artifact.DESIGN_DOC,
        Artifact.DESIGN_REVIEW_REPORT,
        Artifact.DESIGN_REVIEW_DECISIONS,
        Artifact.DEVELOPMENT_PLAN,
        Artifact.GENERATED_FILES,
        Artifact.DT_TESTS,
        Artifact.SELF_TEST_REPORT,
        Artifact.REVIEW_REPORT,
        Artifact.REVIEW_DECISIONS,
    },
    "design_review_agent": {
        Artifact.REPO_SUMMARY,
        Artifact.CLARIFICATION_HISTORY,
        Artifact.REQUIREMENT_ANALYSIS,
        Artifact.DESIGN_DOC,
        Artifact.DESIGN_REVIEW_REPORT,
    },
    "review_agent": {
        Artifact.REQUIREMENT_ANALYSIS,
        Artifact.DESIGN_DOC,
        Artifact.DEVELOPMENT_PLAN,
        Artifact.GENERATED_FILES,
        Artifact.DT_TESTS,
        Artifact.SELF_TEST_REPORT,
        Artifact.REVIEW_REPORT,
    },
}


@dataclass(frozen=True)
class AgentContext:
    state: WorkflowState
    actor: str

    def read(self, artifact: Artifact) -> str:
        if artifact not in READ_PERMISSIONS[self.actor]:
            raise PermissionError(f"{self.actor} cannot read {artifact.value}")
        return self.state.artifacts.get(artifact.value, "")

    def write(self, artifact: Artifact, content: str) -> None:
        if artifact not in WRITE_PERMISSIONS[self.actor]:
            raise PermissionError(f"{self.actor} cannot write {artifact.value}")
        self.state.artifacts[artifact.value] = content.strip()
        self.state.log(self.actor, f"wrote {artifact.value}")
