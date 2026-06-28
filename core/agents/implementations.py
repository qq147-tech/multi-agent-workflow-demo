from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from core.agents.prompt_loader import AgentPromptLoader
from core.runtime import LLMClient
from core.skills import SkillLoader
from core.tools import inspect_repository
from permissions import AgentContext
from workflow_models import Artifact, WorkflowState


CORE_ROOT = Path(__file__).resolve().parents[1]


class AgentBase:
    prompt_loader = AgentPromptLoader()
    skill_loader = SkillLoader(CORE_ROOT / "skills")

    def prompt(self, name: str) -> str:
        return self.prompt_loader.load(name)

    def skills(self, names: list[str]) -> str:
        return self.skill_loader.load_many(names)

    def complete(
        self,
        state: WorkflowState,
        agent_name: str,
        skill_names: list[str],
        task: str,
        skill_config_key: str = "skills",
    ) -> str:
        config = state.agent_config.get(agent_name, {})
        prompt_name = config.get("prompt", f"{agent_name}.md")
        selected_skills = config.get(skill_config_key) or config.get("skills", skill_names)
        system_prompt = (
            f"{self.prompt(prompt_name)}\n\n"
            "## Loaded Skills\n\n"
            f"{self.skills(selected_skills)}"
        )
        recovery_retries = int(os.getenv("OPENAI_RECOVERY_RETRIES", "1"))
        client = LLMClient(state.llm_config)
        for attempt in range(recovery_retries + 1):
            result = client.complete(system_prompt, task)
            if not _is_retryable_llm_failure(result) or attempt >= recovery_retries:
                return result
            delay = 8 * (attempt + 1)
            state.log(
                agent_name,
                f"LLM connection failed; automatic recovery retry {attempt + 1}/{recovery_retries} after {delay}s",
            )
            time.sleep(delay)
        return result


class DesignAgent(AgentBase):
    actor = "design_agent"

    def start_requirement_analysis(self, state: WorkflowState) -> None:
        ctx = AgentContext(state, self.actor)
        repo = inspect_repository(state.repo_url, query=state.requirement)
        ctx.write(
            Artifact.REPO_SUMMARY,
            (
                f"Repository input: {repo.input}\n"
                f"Repository kind: {repo.kind}\n"
                f"Inferred project name: {repo.display_name}\n\n"
                f"Repository analysis:\n{repo.summary}"
            ),
        )
        self.ask_next_question(state)

    def ask_next_question(self, state: WorkflowState) -> None:
        ctx = AgentContext(state, self.actor)
        question = self.complete(
            state,
            "DesignAgent",
            ["design-principles", "design-template"],
            (
                "Ask exactly one requirement clarification question in Chinese.\n"
                "Do not include explanations or multiple questions.\n\n"
                f"Original requirement:\n{state.requirement}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Clarification history:\n{ctx.read(Artifact.CLARIFICATION_HISTORY) or '(none)'}\n\n"
                f"Current round: {state.clarification_round + 1}"
            ),
            skill_config_key="clarification_skills",
        ).strip()
        ctx.write(Artifact.CLARIFICATION_QUESTION, question)
        state.log(self.actor, f"asked clarification question {state.clarification_round + 1}")

    def record_clarification_answer(self, state: WorkflowState, answer: str) -> bool:
        ctx = AgentContext(state, self.actor)
        history = ctx.read(Artifact.CLARIFICATION_HISTORY)
        updated = (
            f"{history}\n\n"
            f"Q{state.clarification_round + 1}: {ctx.read(Artifact.CLARIFICATION_QUESTION)}\n"
            f"A{state.clarification_round + 1}: {answer.strip()}"
        ).strip()
        ctx.write(Artifact.CLARIFICATION_HISTORY, updated)
        state.clarification_round += 1
        clear_enough = state.clarification_round >= 3
        if not clear_enough:
            self.ask_next_question(state)
            return False

        self.create_requirement_analysis_and_design_doc(state)
        return True

    def create_requirement_analysis_and_design_doc(self, state: WorkflowState, feedback: str = "") -> None:
        ctx = AgentContext(state, self.actor)
        state.design_revision += 1
        output = self.complete(
            state,
            "DesignAgent",
            ["design-principles", "design-template"],
            (
                "Generate both requirement analysis and design document in Chinese.\n"
                "Return only a JSON object with exactly these keys:\n"
                "- requirement_analysis: markdown string\n"
                "- design_doc: markdown string\n\n"
                "If the repository summary says 'Directory scan completed: yes', do not claim that "
                "the actual directory scan was not completed. Use the provided directory tree and "
                "key file excerpts as repository context.\n\n"
                "If the repository summary includes 'C/C++ project analysis', use that section to "
                "identify modules, build files, headers, macros, and relevant implementation areas. "
                "Do not treat a detected C/C++ repository as a generic web or Python demo.\n\n"
                "Do not wrap the JSON in markdown fences.\n\n"
                f"Design revision: {state.design_revision}\n\n"
                f"Original requirement:\n{state.requirement}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Clarification history:\n{ctx.read(Artifact.CLARIFICATION_HISTORY)}\n\n"
                f"Human feedback:\n{feedback or '(none)'}"
            ),
            skill_config_key="design_skills",
        )
        parsed = _parse_json_object(output)
        ctx.write(Artifact.REQUIREMENT_ANALYSIS, parsed.get("requirement_analysis", output))
        ctx.write(Artifact.DESIGN_DOC, parsed.get("design_doc", output))

    def create_requirement_analysis(self, state: WorkflowState) -> None:
        ctx = AgentContext(state, self.actor)
        analysis = self.complete(
            state,
            "DesignAgent",
            ["design-principles"],
            (
                "Generate a Chinese requirement analysis document. Be specific and structured.\n\n"
                f"Original requirement:\n{state.requirement}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Clarification history:\n{ctx.read(Artifact.CLARIFICATION_HISTORY)}"
            ),
        )
        ctx.write(Artifact.REQUIREMENT_ANALYSIS, analysis)

    def create_design_doc(self, state: WorkflowState, feedback: str = "") -> None:
        self.create_requirement_analysis_and_design_doc(state, feedback)

    def apply_design_review_decisions(self, state: WorkflowState, decisions: str) -> None:
        ctx = AgentContext(state, self.actor)
        ctx.write(Artifact.DESIGN_REVIEW_DECISIONS, decisions)
        self.create_requirement_analysis_and_design_doc(
            state,
            (
                "Apply only the design review suggestions accepted or customized by the human. "
                "Do not apply rejected suggestions.\n\n"
                f"{_summarize_review_decisions(decisions)}"
            ),
        )


class DesignReviewAgent(AgentBase):
    actor = "design_review_agent"

    def run(self, state: WorkflowState) -> None:
        ctx = AgentContext(state, self.actor)
        report = self.complete(
            state,
            "DesignReviewAgent",
            ["design-principles", "design-template"],
            (
                "Generate a Chinese design review report. "
                "Provide numbered suggestions that a human can accept, reject, or edit.\n\n"
                f"Design revision: {state.design_revision}\n\n"
                f"Original requirement:\n{state.requirement}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Clarification history:\n{ctx.read(Artifact.CLARIFICATION_HISTORY)}\n\n"
                f"Requirement analysis:\n{ctx.read(Artifact.REQUIREMENT_ANALYSIS)}\n\n"
                f"Design document:\n{ctx.read(Artifact.DESIGN_DOC)}"
            ),
        )
        ctx.write(Artifact.DESIGN_REVIEW_REPORT, report)


class DevelopAgent(AgentBase):
    actor = "develop_agent"

    def create_development_plan(self, state: WorkflowState, feedback: str = "") -> None:
        ctx = AgentContext(state, self.actor)
        state.development_revision += 1
        plan = self.complete(
            state,
            "DevelopAgent",
            ["code-style", "dt-guidelines"],
            (
                "Generate a Chinese development plan and pseudocode from the approved design.\n"
                "Do not produce final code files yet. Address human feedback if any.\n\n"
                "If the repository summary includes C/C++ project analysis, ground the plan in "
                "the detected modules, build files, headers, macros, and source files.\n\n"
                f"Development revision: {state.development_revision}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Design document:\n{ctx.read(Artifact.DESIGN_DOC)}\n\n"
                f"Human feedback:\n{feedback or '(none)'}"
            ),
        )
        ctx.write(Artifact.DEVELOPMENT_PLAN, plan)

    def implement_and_self_test(self, state: WorkflowState, feedback: str = "") -> None:
        ctx = AgentContext(state, self.actor)
        state.implementation_revision += 1
        generated = self.complete(
            state,
            "DevelopAgent",
            ["code-style", "dt-guidelines"],
            (
                "Generate implementation files and DT test files.\n"
                "Return only a JSON object mapping file paths to file contents.\n"
                "Include both application code and DT tests.\n\n"
                "If this is a C/C++ project, generate plausible .c/.h/build/test changes that "
                "fit the detected repository structure instead of generic Python or web files.\n\n"
                f"Implementation revision: {state.implementation_revision}\n\n"
                f"Repository summary:\n{ctx.read(Artifact.REPO_SUMMARY)}\n\n"
                f"Design document:\n{ctx.read(Artifact.DESIGN_DOC)}\n\n"
                f"Development plan:\n{ctx.read(Artifact.DEVELOPMENT_PLAN)}\n\n"
                f"Human feedback or review decisions:\n{feedback or '(none)'}"
            ),
        )
        files = _parse_json_object(generated)
        ctx.write(Artifact.GENERATED_FILES, json.dumps(files, ensure_ascii=False, indent=2))

        test_files = {path: content for path, content in files.items() if "test" in path.lower() or "dt" in path.lower()}
        ctx.write(Artifact.DT_TESTS, json.dumps(test_files or {"NO_TEST_FILES_FOUND.md": generated}, ensure_ascii=False, indent=2))

        self_test = self.complete(
            state,
            "DevelopAgent",
            ["dt-guidelines"],
            (
                "Generate a Chinese self-test report for these generated files. "
                "If tests cannot actually be executed, say so explicitly and list the expected checks.\n\n"
                f"Generated files JSON:\n{json.dumps(files, ensure_ascii=False, indent=2)}"
            ),
        )
        ctx.write(Artifact.SELF_TEST_REPORT, self_test)

    def apply_review_decisions(self, state: WorkflowState, decisions: str) -> None:
        ctx = AgentContext(state, self.actor)
        ctx.write(Artifact.REVIEW_DECISIONS, decisions)
        self.implement_and_self_test(
            state,
            (
                "Apply only the review suggestions accepted or customized by the human. "
                "Do not apply rejected suggestions.\n\n"
                f"{_summarize_review_decisions(decisions)}"
            ),
        )


class ReviewAgent(AgentBase):
    actor = "review_agent"

    def run(self, state: WorkflowState) -> None:
        ctx = AgentContext(state, self.actor)
        state.review_revision += 1
        report = self.complete(
            state,
            "ReviewAgent",
            ["code-review-rules", "code-style", "dt-guidelines"],
            (
                "Generate a Chinese review report. Provide numbered suggestions that a human can accept, reject, or edit.\n\n"
                f"Review revision: {state.review_revision}\n\n"
                f"Design document:\n{ctx.read(Artifact.DESIGN_DOC)}\n\n"
                f"Development plan:\n{ctx.read(Artifact.DEVELOPMENT_PLAN)}\n\n"
                f"Generated files:\n{ctx.read(Artifact.GENERATED_FILES)}\n\n"
                f"DT tests:\n{ctx.read(Artifact.DT_TESTS)}\n\n"
                f"Self-test report:\n{ctx.read(Artifact.SELF_TEST_REPORT)}"
            ),
        )
        ctx.write(Artifact.REVIEW_REPORT, report)


def _parse_json_object(text: str) -> dict[str, str]:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if match:
        candidates.insert(0, match.group(1))
    brace = re.search(r"(\{.*\})", stripped, re.DOTALL)
    if brace:
        candidates.append(brace.group(1))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return {str(key): str(value) for key, value in parsed.items()}
        except json.JSONDecodeError:
            continue

    return {"MODEL_OUTPUT.md": text}


def _is_retryable_llm_failure(text: str) -> bool:
    return text.lstrip().startswith("# LLM API connection failed")


def _summarize_review_decisions(decisions: str) -> str:
    try:
        payload = json.loads(decisions)
    except json.JSONDecodeError:
        return f"Human review decisions:\n{decisions}"

    items = payload.get("decisions", [])
    if not isinstance(items, list):
        return f"Human review decisions:\n{decisions}"

    accepted: list[str] = []
    customized: list[str] = []
    rejected: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        suggestion_id = str(item.get("id", "?"))
        suggestion = str(item.get("suggestion", "")).strip()
        decision = str(item.get("decision", "")).strip()
        custom_instruction = str(item.get("custom_instruction", "")).strip()
        if decision == "accept":
            accepted.append(f"- 建议 {suggestion_id}: {suggestion}")
        elif decision == "modify":
            customized.append(
                f"- 建议 {suggestion_id}: {custom_instruction}\n  原始建议: {suggestion}"
            )
        else:
            rejected.append(f"- 建议 {suggestion_id}: {suggestion}")

    return (
        "Human-selected review decisions:\n\n"
        "Accepted suggestions to apply:\n"
        f"{chr(10).join(accepted) if accepted else '- None'}\n\n"
        "Customized suggestions to apply:\n"
        f"{chr(10).join(customized) if customized else '- None'}\n\n"
        "Rejected suggestions to ignore:\n"
        f"{chr(10).join(rejected) if rejected else '- None'}"
    )


# Backward-compatible aliases for older imports.
CodeAgent = DevelopAgent
CodeReviewAgent = ReviewAgent
PMAgent = DesignAgent
