"""OpenCode CLI adapter for Sentry runtime failure management."""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generator

from Sentry.models import AgentStep, agent_step_from_parts

OPENCODE_ACTION_SCHEMA = """Available tools:
- bash: Execute shell commands in the repository (e.g., pytest, git diff, python script.py).
- read: Read contents of a file given filePath and optional line ranges.
- edit: Modify a file by replacing oldString with newString.
- write: Create or overwrite a file with given content.
- search: Search for patterns in files.
Actions should be purposeful, incremental, and verify hypotheses through tests or output observation.
"""


@dataclass
class OpenCodeEvent:
    event_type: str
    session_id: str
    part: dict[str, Any]
    timestamp: int


class OpenCodeRunner:
    """Manages execution of OpenCode CLI sessions with step-by-step Sentry monitoring."""

    def __init__(
        self,
        workspace_dir: Path | str,
        *,
        model: str | None = None,
        opencode_bin: str = "/opt/homebrew/bin/opencode",
        timeout_seconds: int = 300,
        env: dict[str, str] | None = None,
    ):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.model = model
        self.opencode_bin = opencode_bin
        self.timeout_seconds = timeout_seconds
        self.env = env or {}
        self.session_id: str | None = None
        self._step_counter = 0
        self.token_usage = {
            # Cumulative sums across all LLM API calls in the session (Billing / Provider Quota view)
            "cumulative_input": 0,
            "cumulative_output": 0,
            "cumulative_reasoning": 0,
            "cumulative_total": 0,
            # Session snapshot (Context window / Unique token view)
            "max_context_window": 0,
            "last_step_input": 0,
            "total_generated": 0,  # generated output + reasoning
            "net_session_tokens": 0,  # last_step_input + total_generated
            # Backward compatibility fields
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "total": 0,
        }

    def run_prompt(
        self,
        prompt: str,
        *,
        is_continuation: bool = False,
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> list[AgentStep]:
        """Runs OpenCode with a prompt, streaming steps and optionally notifying on_step."""
        cmd = [self.opencode_bin, "run", prompt, "--pure", "--format", "json", "--dir", str(self.workspace_dir)]
        if self.model:
            cmd.extend(["--model", self.model])
        if is_continuation and self.session_id:
            cmd.extend(["--session", self.session_id, "--continue"])

        run_env = os.environ.copy()
        run_env.update(self.env)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(self.workspace_dir),
            env=run_env,
        )

        steps: list[AgentStep] = []
        current_reasoning = ""

        try:
            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    event_data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event_data.get("type")
                part = event_data.get("part", {})
                sid = event_data.get("sessionID")
                if sid:
                    self.session_id = sid

                if event_type == "text":
                    text_content = part.get("text", "")
                    if text_content:
                        current_reasoning += text_content + "\n"

                elif event_type == "tool_use":
                    tool_name = part.get("tool", "unknown")
                    state = part.get("state", {})
                    tool_input = state.get("input", {})
                    tool_output = state.get("output", "")
                    metadata = state.get("metadata", {})
                    status = state.get("status", "completed")

                    # Check exit code or error for bash/tools
                    exit_code = metadata.get("exit", 0) if isinstance(metadata, dict) else 0
                    accepted = (exit_code == 0) and (status != "error")
                    raw_action = f"{tool_name}({json.dumps(tool_input, ensure_ascii=False)})"

                    step = agent_step_from_parts(
                        step_id=self._step_counter,
                        reasoning=current_reasoning.strip(),
                        raw_action=raw_action,
                        tool_name=tool_name,
                        tool_args=tool_input if isinstance(tool_input, dict) else {"input": tool_input},
                        observation=str(tool_output) if tool_output is not None else "",
                        parsed_ok=True,
                        schema_valid=True,
                        accepted_by_environment=accepted,
                        metadata={
                            "session_id": self.session_id,
                            "exit_code": exit_code,
                            "tool_status": status,
                        },
                    )
                    self._step_counter += 1
                    current_reasoning = ""
                    steps.append(step)
                    if on_step is not None:
                        should_continue = on_step(step)
                        if should_continue is False:
                            process.terminate()
                            break

                elif event_type == "step_finish":
                    reason = part.get("reason")
                    tokens = part.get("tokens", {})
                    if isinstance(tokens, dict):
                        inp = int(tokens.get("input", 0))
                        out = int(tokens.get("output", 0))
                        rsn = int(tokens.get("reasoning", 0))
                        tot = int(tokens.get("total", 0))

                        # Cumulative across all turns (API billing / quota view)
                        self.token_usage["cumulative_input"] += inp
                        self.token_usage["cumulative_output"] += out
                        self.token_usage["cumulative_reasoning"] += rsn
                        self.token_usage["cumulative_total"] += tot

                        # Session context view (net unique tokens in conversation)
                        self.token_usage["last_step_input"] = inp
                        if inp > self.token_usage["max_context_window"]:
                            self.token_usage["max_context_window"] = inp
                        self.token_usage["total_generated"] += (out + rsn)
                        self.token_usage["net_session_tokens"] = inp + self.token_usage["total_generated"]

                        # Backward compatibility
                        self.token_usage["input"] = self.token_usage["cumulative_input"]
                        self.token_usage["output"] = self.token_usage["cumulative_output"]
                        self.token_usage["reasoning"] = self.token_usage["cumulative_reasoning"]
                        self.token_usage["total"] = self.token_usage["cumulative_total"]
                    # If stopped without tool calls and there was pending reasoning/text, record as final step
                    if reason == "stop" and current_reasoning.strip() and not steps:
                        step = agent_step_from_parts(
                            step_id=self._step_counter,
                            reasoning=current_reasoning.strip(),
                            raw_action="finish()",
                            tool_name="finish",
                            tool_args={},
                            observation="Task ended with text response.",
                            parsed_ok=True,
                            schema_valid=True,
                            accepted_by_environment=True,
                        )
                        self._step_counter += 1
                        current_reasoning = ""
                        steps.append(step)
                        if on_step is not None:
                            on_step(step)

            process.wait(timeout=self.timeout_seconds)
        finally:
            if process.poll() is None:
                process.terminate()

        return steps

    def get_git_diff(self) -> str:
        """Returns the current git diff of the workspace."""
        res = subprocess.run(
            ["git", "diff"],
            cwd=str(self.workspace_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout
