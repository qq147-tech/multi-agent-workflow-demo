from __future__ import annotations

from io import BytesIO
import itertools
import json
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from agents import DesignAgent, DesignReviewAgent, DevelopAgent, ReviewAgent
from notifications import NotificationService
from workflow_models import Artifact, WorkflowState, WorkflowStatus


class WorkflowEngine:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.states: dict[str, WorkflowState] = {}
        self.notifications = NotificationService()
        self.design = DesignAgent()
        self.design_review = DesignReviewAgent()
        self.develop = DevelopAgent()
        self.review = ReviewAgent()

    def create(
        self,
        repo_url: str,
        requirement: str,
        agent_config: dict[str, dict] | None = None,
        llm_config: dict[str, str] | None = None,
    ) -> WorkflowState:
        workflow_id = str(next(self._ids))
        state = WorkflowState(
            workflow_id,
            repo_url.strip(),
            requirement.strip(),
            agent_config or default_agent_config(),
            _clean_llm_config(llm_config or {}),
        )
        self.states[workflow_id] = state
        state.log("workflow", "created")
        self.design.start_requirement_analysis(state)
        state.status = WorkflowStatus.CLARIFICATION_REQUIRED
        self.notifications.notify_human_review(
            state,
            "需要需求澄清",
            f"工作流 {state.id} 等待你回答一个澄清问题。",
        )
        return state

    def get(self, workflow_id: str) -> WorkflowState:
        if workflow_id not in self.states:
            raise KeyError(f"workflow {workflow_id} not found")
        return self.states[workflow_id]

    def update_artifact(self, workflow_id: str, artifact: Artifact, content: str, actor: str = "human") -> WorkflowState:
        state = self.get(workflow_id)
        state.artifacts[artifact.value] = content.strip()
        state.log(actor, f"updated {artifact.value}")
        return state

    def answer_clarification(self, workflow_id: str, answer: str) -> WorkflowState:
        state = self.get(workflow_id)
        if state.status != WorkflowStatus.CLARIFICATION_REQUIRED:
            raise ValueError(f"cannot answer clarification from {state.status.value}")
        clear_enough = self.design.record_clarification_answer(state, answer)
        if clear_enough:
            state.status = WorkflowStatus.DESIGN_HUMAN_REVIEW
            self.notifications.notify_human_review(
                state,
                "设计文档待审核",
                f"工作流 {state.id} 已生成设计文档，请审核。",
            )
        else:
            self.notifications.notify_human_review(
                state,
                "继续需求澄清",
                f"工作流 {state.id} 还有一个澄清问题待回答。",
            )
        return state

    def approve_design(self, workflow_id: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.DESIGN_HUMAN_REVIEW)
        state.log("human", "approved design document")
        self.design_review.run(state)
        state.status = WorkflowStatus.DESIGN_REVIEW_HUMAN_REVIEW
        self.notifications.notify_human_review(
            state,
            "设计审核报告待处理",
            f"工作流 {state.id} 已生成设计审核报告，请选择接受或拒绝修改建议。",
        )
        return state

    def reject_design(self, workflow_id: str, feedback: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.DESIGN_HUMAN_REVIEW)
        state.log("human", f"rejected design: {feedback}")
        self.design.create_design_doc(state, feedback)
        self.notifications.notify_human_review(
            state,
            "设计文档已重新生成",
            f"工作流 {state.id} 根据驳回意见重新生成了设计文档。",
        )
        return state

    def submit_design_review_decisions(self, workflow_id: str, decisions: str, no_changes: bool = False) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.DESIGN_REVIEW_HUMAN_REVIEW)
        state.log("human", f"submitted design review decisions; no_changes={no_changes}")
        if no_changes:
            self.develop.create_development_plan(state)
            state.status = WorkflowStatus.DEVELOPMENT_PLAN_HUMAN_REVIEW
            self.notifications.notify_human_review(
                state,
                "开发方案待审核",
                f"工作流 {state.id} 已进入开发方案阶段，请审核。",
            )
            return state

        self.design.apply_design_review_decisions(state, decisions)
        self.design_review.run(state)
        self.notifications.notify_human_review(
            state,
            "设计审核报告已重新生成",
            f"工作流 {state.id} 已根据人工选择修订设计文档并重新审核。",
        )
        return state

    def approve_development_plan(self, workflow_id: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.DEVELOPMENT_PLAN_HUMAN_REVIEW)
        state.log("human", "approved development plan")
        self.develop.implement_and_self_test(state)
        state.status = WorkflowStatus.IMPLEMENTATION_HUMAN_REVIEW
        self.notifications.notify_human_review(
            state,
            "代码和 DT 待审核",
            f"工作流 {state.id} 已生成代码和 DT 用例，请审核。",
        )
        return state

    def reject_development_plan(self, workflow_id: str, feedback: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.DEVELOPMENT_PLAN_HUMAN_REVIEW)
        state.log("human", f"rejected development plan: {feedback}")
        self.develop.create_development_plan(state, feedback)
        return state

    def approve_implementation(self, workflow_id: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.IMPLEMENTATION_HUMAN_REVIEW)
        state.log("human", "approved implementation and DT")
        self.review.run(state)
        state.status = WorkflowStatus.REVIEW_HUMAN_REVIEW
        self.notifications.notify_human_review(
            state,
            "审核报告待处理",
            f"工作流 {state.id} 已生成审核报告，请选择接受或拒绝修改建议。",
        )
        return state

    def reject_implementation(self, workflow_id: str, feedback: str) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.IMPLEMENTATION_HUMAN_REVIEW)
        state.log("human", f"rejected implementation: {feedback}")
        self.develop.implement_and_self_test(state, feedback)
        return state

    def submit_review_decisions(self, workflow_id: str, decisions: str, no_changes: bool = False) -> WorkflowState:
        state = self.get(workflow_id)
        self._require_status(state, WorkflowStatus.REVIEW_HUMAN_REVIEW)
        state.log("human", f"submitted review decisions; no_changes={no_changes}")
        if no_changes:
            state.status = WorkflowStatus.DONE
            state.log("workflow", "finished without applying review suggestions")
            return state

        self.develop.apply_review_decisions(state, decisions)
        self.review.run(state)
        self.notifications.notify_human_review(
            state,
            "审核报告已重新生成",
            f"工作流 {state.id} 已根据人工选择修复并重新审核。",
        )
        return state

    def rollback(self, workflow_id: str, target_status: WorkflowStatus, reason: str = "") -> WorkflowState:
        state = self.get(workflow_id)
        allowed_targets = {
            WorkflowStatus.CLARIFICATION_REQUIRED,
            WorkflowStatus.DESIGN_HUMAN_REVIEW,
            WorkflowStatus.DESIGN_REVIEW_HUMAN_REVIEW,
            WorkflowStatus.DEVELOPMENT_PLAN_HUMAN_REVIEW,
            WorkflowStatus.IMPLEMENTATION_HUMAN_REVIEW,
            WorkflowStatus.REVIEW_HUMAN_REVIEW,
        }
        if target_status not in allowed_targets:
            raise ValueError(f"cannot rollback to {target_status.value}")

        state.status = target_status
        state.log("human", f"rolled back workflow to {target_status.value}: {reason or 'no reason provided'}")

        if target_status == WorkflowStatus.CLARIFICATION_REQUIRED:
            self.design.ask_next_question(state)
        elif target_status == WorkflowStatus.DESIGN_HUMAN_REVIEW and not state.artifacts.get(Artifact.DESIGN_DOC.value):
            self.design.create_requirement_analysis(state)
            self.design.create_design_doc(state, reason)
        elif target_status == WorkflowStatus.DESIGN_REVIEW_HUMAN_REVIEW and not state.artifacts.get(Artifact.DESIGN_REVIEW_REPORT.value):
            self.design_review.run(state)
        elif target_status == WorkflowStatus.DEVELOPMENT_PLAN_HUMAN_REVIEW and not state.artifacts.get(Artifact.DEVELOPMENT_PLAN.value):
            self.develop.create_development_plan(state, reason)
        elif target_status == WorkflowStatus.IMPLEMENTATION_HUMAN_REVIEW and not state.artifacts.get(Artifact.GENERATED_FILES.value):
            self.develop.implement_and_self_test(state, reason)
        elif target_status == WorkflowStatus.REVIEW_HUMAN_REVIEW and not state.artifacts.get(Artifact.REVIEW_REPORT.value):
            self.review.run(state)

        self.notifications.notify_human_review(
            state,
            "流程已撤回",
            f"工作流 {state.id} 已撤回到 {target_status.value}。",
        )
        return state

    def download_artifact(self, workflow_id: str, artifact: Artifact) -> tuple[str, bytes, str]:
        state = self.get(workflow_id)
        content = state.artifacts.get(artifact.value, "")
        if artifact == Artifact.GENERATED_FILES:
            return (
                f"workflow-{workflow_id}-generated-code.zip",
                self._generated_files_zip(content),
                "application/zip",
            )

        filename = f"workflow-{workflow_id}-{artifact.value}.md"
        return filename, content.encode("utf-8"), "text/markdown; charset=utf-8"

    def _generated_files_zip(self, content: str) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            try:
                files = json.loads(content) if content.strip() else {}
            except json.JSONDecodeError:
                files = {"MODEL_OUTPUT.md": content}

            if not isinstance(files, dict) or not files:
                files = {"README.md": "No generated files were available."}

            for path, file_content in files.items():
                safe_path = str(path).replace("\\", "/").lstrip("/")
                if not safe_path or ".." in safe_path.split("/"):
                    safe_path = "generated_file.txt"
                archive.writestr(safe_path, str(file_content))

        return buffer.getvalue()

    def to_dict(self, state: WorkflowState) -> dict[str, Any]:
        return {
            "id": state.id,
            "repo_url": state.repo_url,
            "requirement": state.requirement,
            "agent_config": state.agent_config,
            "llm_config": _safe_llm_config(state.llm_config),
            "status": state.status.value,
            "artifacts": state.artifacts,
            "events": [event.__dict__ for event in state.events],
            "clarification_round": state.clarification_round,
            "design_revision": state.design_revision,
            "development_revision": state.development_revision,
            "implementation_revision": state.implementation_revision,
            "review_revision": state.review_revision,
        }

    def _require_status(self, state: WorkflowState, expected: WorkflowStatus) -> None:
        if state.status != expected:
            raise ValueError(f"expected {expected.value}, got {state.status.value}")


def default_agent_config() -> dict[str, dict]:
    return {
        "DesignAgent": {
            "prompt": "DesignAgent.md",
            "skills": ["design-principles", "design-template"],
            "clarification_skills": ["design-principles"],
            "design_skills": ["design-principles", "design-template"],
        },
        "DesignReviewAgent": {
            "prompt": "DesignReviewAgent.md",
            "skills": ["design-principles", "design-template"],
        },
        "DevelopAgent": {
            "prompt": "DevelopAgent.md",
            "skills": ["code-style", "dt-guidelines"],
        },
        "ReviewAgent": {
            "prompt": "ReviewAgent.md",
            "skills": ["code-review-rules", "code-style", "dt-guidelines"],
        },
    }


def _clean_llm_config(config: dict[str, str]) -> dict[str, str]:
    return {str(key): str(value).strip() for key, value in config.items() if str(value).strip()}


def _safe_llm_config(config: dict[str, str]) -> dict[str, str]:
    safe = dict(config)
    if "api_key" in safe:
        key = safe["api_key"]
        safe["api_key"] = f"{key[:8]}..." if key else ""
    return safe
