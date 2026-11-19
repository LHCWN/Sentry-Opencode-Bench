from __future__ import annotations

from collections.abc import Callable

from ._structured import json_object, nonempty_text, string_list
from .config import SentryConfig
from .models import DetectionResult, LocalTraceWindow, TaskContext
from .taxonomy import (
    PROGRESS_LABEL_DEFINITIONS,
    REASONING_LABEL_DEFINITIONS,
    FailureType,
    labels_for_failure_type,
)


class SentryDetector:
    """Schema-first detector from Section 3.1."""

    def __init__(
        self,
        judge_callback: Callable[[str], str] | None,
        config: SentryConfig | None = None,
    ):
        self.judge_callback = judge_callback
        self.config = config or SentryConfig()

    def detect(self, window: LocalTraceWindow, task: TaskContext) -> DetectionResult:
        if not window.steps:
            return _no_failure("No trajectory cycles are available.")
        hard = detect_action_validity(window.steps[-1])
        if hard is not None:
            return hard
        if self.judge_callback is None:
            raise RuntimeError("Soft-failure detection requires the Sentry model callback")
        prompt = build_detector_prompt(window, task, self.config)
        return parse_detector_response(self.judge_callback(prompt))


def detect_action_validity(step) -> DetectionResult | None:
    """Check executability flags supplied by the environment adapter.

    An execution rejection alone can reflect task semantics or a tool error; it
    is not proof of a malformed or unavailable action. Adapters must mark such
    validity errors explicitly via parsed_ok/schema_valid.
    """
    step.validate()
    action = step.action
    if action.parsed_ok and action.schema_valid:
        return None
    error = (
        action.parser_error
        or action.schema_error
        or "The proposed action is not executable under the required schema."
    )
    return DetectionResult(
        should_rescue=True,
        failure_type=FailureType.ACTION_VALIDITY_FAILURE,
        rationale="The current action is not executable under the environment schema.",
        source="schema_check",
        local_evidence=[error],
        retrieval_labels=[],
    )


def build_detector_prompt(
    window: LocalTraceWindow,
    task: TaskContext,
    config: SentryConfig | None = None,
) -> str:
    cfg = config or SentryConfig()
    trajectory = render_trajectory(window.steps[-cfg.trace.window_size :])
    progress_labels = "\n".join(
        f"- {name}: {definition}" for name, definition in PROGRESS_LABEL_DEFINITIONS.items()
    )
    reasoning_labels = "\n".join(
        f"- {name}: {definition}" for name, definition in REASONING_LABEL_DEFINITIONS.items()
    )
    return f"""[SENTRY DETECTOR]
Role.
You are Sentry, an external runtime failure manager for an LLM task agent. Inspect the recent trajectory and decide whether the agent needs intervention. Do not judge final task success; judge whether the current local trajectory contains an execution-time failure.

Task objective.
{task.objective}

Recent trajectory window.
{trajectory}

Required action schema.
{task.action_schema}

Failure taxonomy.
Action Validity: the proposed action is not executable under the environment schema. This case is handled by the deterministic check before this model call.

Progress Failure: the recent trajectory repeats, stalls, over-explores, or terminates at the wrong time.
Retrieval labels:
{progress_labels}

Reasoning & Grounding Failure: the agent introduces unsupported assumptions, drifts from the objective, or takes an action that does not follow from the reasoning or observation.
Retrieval labels:
{reasoning_labels}

Software Engineering & Coding Task Rules:
- Initial exploration (searching files with grep/find, reading relevant source files for context, or inspecting commit log) is EXPECTED and is NOT a failure. Do NOT intervene during initial exploration.
- Running tests or commands to inspect behavior or reproduce an issue is NORMAL, even if tests fail.
- Intervene ONLY when there is genuine failure:
  * Repeated identical actions or commands producing the same failure in a loop.
  * Complete stall where the agent repeats unhelpful exploration without refining hypotheses after gathering ample evidence.
  * Clear hallucination or ungrounded assumptions contradicting direct observations.
- If the agent is reading relevant code, investigating the issue, or progressing through a multi-step debugging plan, return "intervention_needed": false and "failure_type": "no_failure".

The action has already passed the deterministic schema check. Do not return action_validity_failure.

Output format.
Return only this JSON object with fixed fields:
{{
  "intervention_needed": true,
  "failure_type": "progress_failure | reasoning_grounding_failure | no_failure",
  "retrieval_labels": ["zero_or_more_labels_from_the_taxonomy"],
  "local_evidence": ["short evidence grounded in the recent trajectory"],
  "diagnosis": "concise diagnosis"
}}
"""


def render_trajectory(steps, max_obs_chars: int = 1500) -> str:
    lines: list[str] = []
    for step in steps:
        obs = str(step.observation or "")
        if len(obs) > max_obs_chars:
            obs = obs[:max_obs_chars] + f"\n... [truncated {len(obs) - max_obs_chars} chars] ..."
        reasoning = str(step.reasoning or "")
        if len(reasoning) > 600:
            reasoning = reasoning[:600] + "... [truncated] ..."
        action_raw = str(step.action.raw if hasattr(step, "action") and hasattr(step.action, "raw") else "")
        if len(action_raw) > 600:
            action_raw = action_raw[:600] + "... [truncated] ..."
        lines.append(
            "\n".join(
                (
                    f"Cycle {step.step_id}:",
                    f"Reasoning: {reasoning}",
                    f"Action: {action_raw}",
                    f"Observation: {obs}",
                )
            )
        )
    return "\n\n".join(lines) or "(empty)"


def parse_detector_response(raw: str) -> DetectionResult:
    data = json_object(raw, {
        "intervention_needed", "failure_type", "retrieval_labels",
        "local_evidence", "diagnosis",
    })
    if data is None:
        return _invalid_output(raw, "Detector output must match the fixed JSON schema.")
    try:
        failure_type = FailureType(data["failure_type"])
    except (TypeError, ValueError):
        return _invalid_output(raw, "Detector failure_type is not a canonical failure type.")
    if failure_type == FailureType.ACTION_VALIDITY_FAILURE:
        return _invalid_output(raw, "The soft detector cannot route action-validity failures.")
    requested = data["intervention_needed"]
    if not isinstance(requested, bool):
        return _invalid_output(raw, "intervention_needed must be a boolean.")
    if not nonempty_text(data["diagnosis"]):
        return _invalid_output(raw, "diagnosis must be a nonempty string.")
    if not string_list(data["local_evidence"]) or not string_list(data["retrieval_labels"]):
        return _invalid_output(raw, "Evidence and retrieval labels must be arrays of strings.")
    labels = data["retrieval_labels"]
    evidence = data["local_evidence"]
    allowed = labels_for_failure_type(failure_type)
    if any(label not in allowed for label in labels) or len(set(labels)) != len(labels):
        return _invalid_output(raw, "Retrieval labels must be unique canonical labels of the failure type.")
    if requested:
        if failure_type == FailureType.NO_FAILURE or not labels or not evidence:
            return _invalid_output(raw, "An intervention requires a soft failure, labels, and local evidence.")
    elif failure_type != FailureType.NO_FAILURE or labels:
        return _invalid_output(raw, "No intervention requires no_failure and no retrieval labels.")
    return DetectionResult(
        should_rescue=requested,
        failure_type=failure_type,
        rationale=data["diagnosis"].strip(),
        source="model",
        local_evidence=[item.strip() for item in evidence],
        retrieval_labels=list(labels),
        raw_response=raw,
    )


def _no_failure(reason: str) -> DetectionResult:
    return DetectionResult(False, FailureType.NO_FAILURE, reason, "runtime")


def _invalid_output(raw: str, reason: str) -> DetectionResult:
    return DetectionResult(
        False,
        FailureType.NO_FAILURE,
        reason,
        "invalid_model_output",
        raw_response=raw,
    )
