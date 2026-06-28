# Multi-Agent Workflow Demo

This is a standalone prototype inspired by DeerFlow-style orchestration:

- Web UI for repository URL and requirement input.
- Repository input supports either a remote URL or a local path. Local paths are checked first.
- Design agent understands the repository, runs multi-round clarification, and creates the design.
- Human can edit/pass/reject the design. Rejection returns to the design agent.
- Develop agent creates a development plan/pseudocode from the approved design.
- Human can edit/pass/reject the development plan. Rejection returns to the develop agent.
- Develop agent generates code files, DT tests, and a self-test report.
- Human can edit/pass/reject generated code and DT tests. Rejection returns to the develop agent.
- Review agent reviews code and DT tests with review skills.
- Human accepts/rejects/edits review suggestions. Accepted suggestions return to the develop agent,
  then review runs again until the report is accepted or all suggestions are rejected.
- Role permissions are enforced by the workflow engine.

The current version uses deterministic local agent logic so you can inspect and extend the
workflow without needing model credentials. Replace each agent's `run()` implementation with
an LLM call when you are ready.

## Run

```powershell
pip install -U openai
python multi_agent_workflow_demo/server.py
```

LLM configuration is loaded from `multi_agent_workflow_demo/.env`:

```text
OPENAI_API_KEY=your-key-here
OPENAI_BASE_URL=https://codex.dakeai.cc/v1
OPENAI_MODEL=gpt-5.4-mini
OPENAI_TIMEOUT_SECONDS=180
OPENAI_MAX_RETRIES=3
```

Open:

```text
http://127.0.0.1:8787
```

The repository field accepts either:

```text
D:\git_projects\nanobot
https://github.com/bytedance/deer-flow
git@github.com:bytedance/deer-flow.git
```

If the input resolves to an existing local path, the PM agent uses local directory metadata first.
If it is not a local path, the PM agent classifies it as GitHub, GitLab, Gitee, SSH Git, generic
remote Git, or unknown. Remote cloning is intentionally left as the next integration step.

## Permission Model

Each agent receives a scoped `AgentContext`:

- `pm_agent`: can read repository summary and create task plan.
- `design_agent`: can read PM plan and write design document.
- `design_review_agent`: can read design document and write design review only.
- `code_agent`: can read approved design and write pseudocode, tests, implementation, and DT report.
- `code_review_agent`: can read generated artifacts and write review report only.

The workflow validates every artifact write against the agent's permission set.

## Code Layout

```text
server.py             HTTP API and static web UI serving
engine.py             Workflow state machine and human approval gates
agents.py             Compatibility re-export for core.agents
permissions.py        AgentContext plus read/write permission maps
notifications.py      Human notification abstraction
workflow_models.py    WorkflowStatus, Artifact, Event, WorkflowState
workflow.py           Compatibility re-export for simple imports
static/index.html     Chinese web UI

core/
  agents/             Agent implementations, middleware, prompts, and thread state
  runtime/            Runtime adapters, including the future LangGraph runtime
  tools/              Built-in tool, MCP tool, and skill-management tool registry
                      includes repository input inspection
  skills/             Skill system and SKILL.md loader
  memory/             Long-term memory, facts, and future memory injection
  mcp/                Model Context Protocol integration points
  subagents/          Sub-agent delegation primitives
```

## LLM, Prompt, And Skill Loading

Agent outputs are generated through the OpenAI-compatible Chat Completions API.

- Agent prompts are loaded from `core/agents/prompts/*.md`.
- Skills are loaded from `core/skills/*/SKILL.md`.
- `DesignAgent` uses `DesignAgent.md`, `design-principles`, and `design-template`.
- `DevelopAgent` uses `DevelopAgent.md`, `code-style`, and `dt-guidelines`.
- `ReviewAgent` uses `ReviewAgent.md`, `code-review-rules`, `code-style`, and `dt-guidelines`.

If `OPENAI_API_KEY` is not set, artifacts will explicitly show an LLM configuration error instead
of generating fake deterministic content.

## Notification Hooks

Human approval points call `NotificationService.notify_human_review()`.

Today it logs notifications into the workflow event stream. On Windows it also attempts a simple
PowerShell popup. You can replace this class with WeChat, Slack, Feishu, email, or webhook delivery.
