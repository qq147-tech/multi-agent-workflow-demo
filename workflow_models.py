from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WorkflowStatus(str, Enum):
    CLARIFICATION_REQUIRED = "clarification_required"
    DESIGN_HUMAN_REVIEW = "design_human_review"
    DESIGN_REVIEW_HUMAN_REVIEW = "design_review_human_review"
    DEVELOPMENT_PLAN_HUMAN_REVIEW = "development_plan_human_review"
    IMPLEMENTATION_HUMAN_REVIEW = "implementation_human_review"
    REVIEW_HUMAN_REVIEW = "review_human_review"
    DONE = "done"
    FAILED = "failed"


class Artifact(str, Enum):
    REPO_SUMMARY = "repo_summary"
    CLARIFICATION_QUESTION = "clarification_question"
    CLARIFICATION_HISTORY = "clarification_history"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    DESIGN_DOC = "design_doc"
    DESIGN_REVIEW_REPORT = "design_review_report"
    DESIGN_REVIEW_DECISIONS = "design_review_decisions"
    DEVELOPMENT_PLAN = "development_plan"
    GENERATED_FILES = "generated_files"
    DT_TESTS = "dt_tests"
    SELF_TEST_REPORT = "self_test_report"
    REVIEW_REPORT = "review_report"
    REVIEW_DECISIONS = "review_decisions"


@dataclass
class Event:
    at: str
    actor: str
    message: str


@dataclass
class WorkflowState:
    id: str
    repo_url: str
    requirement: str
    agent_config: dict[str, dict] = field(default_factory=dict)
    llm_config: dict[str, str] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.CLARIFICATION_REQUIRED
    artifacts: dict[str, str] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    clarification_round: int = 0
    design_revision: int = 0
    development_revision: int = 0
    implementation_revision: int = 0
    review_revision: int = 0

    def log(self, actor: str, message: str) -> None:
        self.events.append(Event(datetime.now().isoformat(timespec="seconds"), actor, message))
