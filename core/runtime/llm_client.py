from __future__ import annotations

import os
import time

from openai import OpenAI
from openai import APIConnectionError, APIStatusError, OpenAIError


class LLMClient:
    def __init__(self, config: dict[str, str] | None = None) -> None:
        config = config or {}
        self.model = config.get("model") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.base_url = config.get("base_url") or os.getenv("OPENAI_BASE_URL")
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
        self.timeout = float(config.get("timeout_seconds") or os.getenv("OPENAI_TIMEOUT_SECONDS", "180"))
        self.max_retries = int(config.get("max_retries") or os.getenv("OPENAI_MAX_RETRIES", "3"))

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            return (
                "# LLM API not configured\n\n"
                "The workflow is configured to use real LLM generation, but `OPENAI_API_KEY` is not set.\n\n"
                "Set these environment variables before starting the server:\n\n"
                "```powershell\n"
                "$env:OPENAI_API_KEY=\"your-key\"\n"
                "$env:OPENAI_BASE_URL=\"https://codex.dakeai.cc/v1\"  # optional\n"
                "$env:OPENAI_MODEL=\"your-model\"\n"
                "python multi_agent_workflow_demo/server.py\n"
                "```\n"
            )

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        ) if self.base_url else OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                print(
                    f"LLM request attempt={attempt}/{self.max_retries} "
                    f"model={self.model} base_url={self.base_url or 'default'} "
                    f"system_chars={len(system_prompt)} user_chars={len(user_prompt)}",
                    flush=True,
                )
                response = client.chat.completions.create(
                    model=self.model,
                    temperature=0.2,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                return response.choices[0].message.content or ""
            except APIConnectionError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 * attempt, 6))
                    continue
                return self._error_document(
                    "LLM API connection failed",
                    (
                        "The server could not complete the request to the configured "
                        "OpenAI-compatible API after retries. Small clarification calls may "
                        "succeed while larger design-generation calls fail if the proxy drops "
                        "longer requests."
                    ),
                    exc,
                )
            except APIStatusError as exc:
                return self._error_document(
                    f"LLM API returned HTTP {exc.status_code}",
                    "The API endpoint responded with an error status.",
                    exc,
                )
            except OpenAIError as exc:
                last_exc = exc
                return self._error_document("LLM API error", "The OpenAI SDK raised an API error.", exc)

        return self._error_document("LLM API error", "The LLM request failed.", last_exc or RuntimeError("unknown error"))

    def _error_document(self, title: str, detail: str, exc: Exception) -> str:
        base_url = self.base_url or "OpenAI default"
        masked_key = f"{self.api_key[:8]}..." if self.api_key else "(not set)"
        return (
            f"# {title}\n\n"
            f"{detail}\n\n"
            "## Current LLM configuration\n\n"
            f"- OPENAI_MODEL: `{self.model}`\n"
            f"- OPENAI_BASE_URL: `{base_url}`\n"
            f"- OPENAI_API_KEY: `{masked_key}`\n\n"
            f"- OPENAI_TIMEOUT_SECONDS: `{self.timeout}`\n"
            f"- OPENAI_MAX_RETRIES: `{self.max_retries}`\n\n"
            "## Error\n\n"
            f"```text\n{type(exc).__name__}: {exc}\n```\n\n"
            "## How to fix\n\n"
            "Restart the server from a PowerShell window where these variables are set:\n\n"
            "```powershell\n"
            "$env:OPENAI_API_KEY=\"your-key\"\n"
            "$env:OPENAI_BASE_URL=\"https://codex.dakeai.cc/v1\"\n"
            "$env:OPENAI_MODEL=\"your-model\"\n"
            "python multi_agent_workflow_demo/server.py\n"
            "```\n"
        )
