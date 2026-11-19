"""SWE-bench Lite runner evaluating OpenCode with or without Sentry failure recovery."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from typing import Any

from Sentry.config import PlaybookConfig, SentryConfig
from Sentry.integration import SentryRunner
from Sentry.models import AgentStep
from benchmarks.opencode_adapter import (
    OPENCODE_ACTION_SCHEMA,
    OpenCodeExecutionError,
    OpenCodeRunner,
)


def fetch_swebench_instance(instance_id: str | None = None, index: int = 0) -> dict[str, Any]:
    """Fetch instance from HuggingFace SWE-bench_Lite dataset."""
    from datasets import load_dataset
    print("Loading SWE-bench Lite dataset split...")
    dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    if instance_id:
        for row in dataset:
            if row["instance_id"] == instance_id:
                return dict(row)
        raise ValueError(f"Instance ID {instance_id} not found in SWE-bench Lite")
    return dict(dataset[index])


def prepare_repo_workspace(instance: dict[str, Any], base_dir: Path) -> Path:
    """Clones the target repo and checks out the base commit."""
    repo_name = instance["repo"]  # e.g., "django/django", "sympy/sympy"
    instance_id = instance["instance_id"]
    work_dir = base_dir / instance_id
    work_dir.mkdir(parents=True, exist_ok=True)

    git_url = f"https://github.com/{repo_name}.git"
    if not (work_dir / ".git").is_dir():
        print(f"Cloning {git_url} into {work_dir}...")
        subprocess.run(["git", "clone", git_url, str(work_dir)], check=True)
    else:
        print(f"Repo already exists in {work_dir}")

    # Remove stale git index lock if present from previous interrupted runs
    index_lock = work_dir / ".git" / "index.lock"
    if index_lock.exists():
        index_lock.unlink(missing_ok=True)

    # Reset and checkout base_commit cleanly (both tracked dirty modifications and untracked files)
    base_commit = instance["base_commit"]
    print(f"Checking out base commit {base_commit}...")
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=str(work_dir), check=False)
    subprocess.run(["git", "clean", "-fdx"], cwd=str(work_dir), check=True)
    subprocess.run(["git", "fetch"], cwd=str(work_dir), check=False)
    subprocess.run(["git", "checkout", "-f", base_commit], cwd=str(work_dir), check=True)
    subprocess.run(["git", "reset", "--hard", base_commit], cwd=str(work_dir), check=True)

    # Exclude opencode configuration, logs, and venvs from git diff tracking
    exclude_file = work_dir / ".git" / "info" / "exclude"
    exclude_patterns = "opencode.json\n.venv\n*.log\n"
    if exclude_file.exists():
        existing = exclude_file.read_text(encoding="utf-8")
        if "opencode.json" not in existing:
            exclude_file.write_text(existing.rstrip() + "\n" + exclude_patterns, encoding="utf-8")
    else:
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        exclude_file.write_text(exclude_patterns, encoding="utf-8")

    # Disable websearch, webfetch, and external directory access so the agent cannot escape workspace
    opencode_cfg = work_dir / "opencode.json"
    opencode_cfg.write_text(json.dumps({
        "permission": {
            "websearch": "deny",
            "webfetch": "deny",
            "external_directory": "deny"
        }
    }, indent=2), encoding="utf-8")
    print(f"Secured workspace permissions (blocked websearch, webfetch, external_directory) via {opencode_cfg}")

    return work_dir


def run_instance(
    instance: dict[str, Any],
    *,
    use_sentry: bool = True,
    sentry_config_path: str | Path = "configs/providers/lmstudio.yaml",
    opencode_model: str | None = "openrouter/nvidia/nemotron-3.5-lightning:free",
    opencode_variant: str | None = None,
    openrouter_key: str | None = None,
    opencode_bin: str | None = None,
    workspaces_dir: Path = Path("workspaces"),
    output_dir: Path = Path("outputs/swebench"),
    max_interventions: int = 5,
    max_total_steps: int = 30,
    check_interval: int = 5,
    check_on_error: bool = True,
) -> dict[str, Any]:
    """Runs a single SWE-bench task using OpenCode, optionally guided by Sentry."""
    instance_id = instance["instance_id"]
    problem_statement = instance["problem_statement"]
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ") + ("_sentry" if use_sentry else "_base")

    instance_output = output_dir / run_id / instance_id
    instance_output.mkdir(parents=True, exist_ok=True)

    # 1. Prepare Workspace
    workspace_path = prepare_repo_workspace(instance, workspaces_dir)

    # 2. Setup OpenCode with hardened sandbox environment
    shims_dir = workspaces_dir / ".shims"
    shims_dir.mkdir(parents=True, exist_ok=True)
    python_shim = shims_dir / "python"
    if not python_shim.exists():
        python_shim.write_text('#!/bin/sh\nexec python3 "$@"\n')
        python_shim.chmod(0o755)

    env = {
        # Strict protection: prevent modifying global/system Python & host environments
        "PIP_REQUIRE_VIRTUALENV": "true",
        "PIP_NO_INDEX": "true",
        "PYTHONNOUSERSITE": "1",
        "NPM_CONFIG_GLOBAL": "false",
        "PATH": f"{shims_dir}:{os.environ.get('PATH', '')}",
    }
    if os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY"):
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = os.environ["GOOGLE_GENERATIVE_AI_API_KEY"]
    if openrouter_key:
        env["OPENROUTER_API_KEY"] = openrouter_key
    elif os.environ.get("OPENROUTER_API_KEY"):
        env["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    if os.environ.get("CLOUDFLARE_API_KEY"):
        env["CLOUDFLARE_API_KEY"] = os.environ["CLOUDFLARE_API_KEY"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        env["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]

    opencode = OpenCodeRunner(
        workspace_path,
        model=opencode_model,
        variant=opencode_variant,
        opencode_bin=opencode_bin,
        env=env,
    )

    # 3. Setup Sentry if enabled
    runner = None
    sentry_cfg = None
    if use_sentry:
        sentry_cfg = SentryConfig.from_yaml(sentry_config_path)
        playbook_path = instance_output / "playbook.json"
        sentry_cfg = sentry_cfg.__class__(
            trace=sentry_cfg.trace,
            retrieval=sentry_cfg.retrieval,
            model=sentry_cfg.model,
            task_agent=sentry_cfg.task_agent,
            playbook=PlaybookConfig(persist_path=str(playbook_path)),
            logging=sentry_cfg.logging,
            api=sentry_cfg.api,
        )
        runner = SentryRunner(config=sentry_cfg, capture_runtime_events=True)
        runner.start_task(
            objective=f"Resolve GitHub issue in {instance['repo']}:\n{problem_statement}",
            action_schema=OPENCODE_ACTION_SCHEMA,
        )

    # 4. Formulate Prompt
    initial_prompt = (
        f"You are resolving an issue in {instance['repo']}.\n\n"
        f"Issue description:\n{problem_statement}\n\n"
        "Instructions:\n"
        "1. Locate and inspect the relevant files.\n"
        "2. Identify the root cause and make the minimal necessary fix.\n"
        "3. Verify your fix if possible (e.g. via code inspection, syntax check, or unit tests). Do not install packages globally.\n"
        "When finished, summarize your changes."
    )

    all_steps: list[AgentStep] = []
    interventions = 0
    start_time = time.time()
    current_prompt = initial_prompt
    is_continuation = False

    print(f"\n=== Starting run for {instance_id} (use_sentry={use_sentry}) ===")

    while len(all_steps) < max_total_steps and interventions < max_interventions:
        pending_repair = None

        def on_step(step: AgentStep) -> bool:
            nonlocal pending_repair
            all_steps.append(step)
            print(f"[{instance_id}] Step {step.step_id}: {step.action.tool_name} ok={step.action.accepted_by_environment}")

            if len(all_steps) >= max_total_steps:
                print(f"[{instance_id}] ⚠️ Reached maximum total steps ({max_total_steps}). Ending turn.")
                return False

            if runner is not None:
                is_error = (
                    not step.action.accepted_by_environment
                    or (isinstance(step.metadata, dict) and step.metadata.get("exit_code", 0) != 0)
                    or (isinstance(step.metadata, dict) and step.metadata.get("tool_status") == "error")
                )
                should_check = (check_on_error and is_error) or (len(all_steps) % check_interval == 0)

                if not should_check:
                    runner.guard.observe_step(step)
                    return True

                print(f"[{instance_id}] 🔍 Triggering Sentry evaluation at step {step.step_id} (error={is_error}, step_count={len(all_steps)})...")
                try:
                    repair = runner.step(step, terminal=False)
                    if repair is not None:
                        pending_repair = repair
                        return False  # Abort current turn so we can inject guidance
                except Exception as e:
                    print(f"Warning: Sentry runner step error: {e}")
            return True

        try:
            opencode.run_prompt(current_prompt, is_continuation=is_continuation, on_step=on_step)
        except OpenCodeExecutionError as e:
            print(f"[{instance_id}] ❌ OpenCode Execution Error: {e}")
            raise
        is_continuation = True

        if pending_repair is not None:
            interventions += 1
            print(f"\n⚡ [SENTRY INTERVENTION #{interventions}] Type: {pending_repair.failure_type}")
            print(f"⚡ [GUIDANCE]: {pending_repair.prompt_text}\n")
            current_prompt = (
                f"[SENTRY GUIDANCE]:\n{pending_repair.prompt_text}\n\n"
                "Please adjust your approach accordingly and continue to implement the fix."
            )
        else:
            # Turn ended without any new intervention needed
            patch = opencode.get_git_diff()
            if not patch.strip() and len(all_steps) < max_total_steps:
                print(f"[{instance_id}] Turn ended without code changes. Prompting agent to implement fix...")
                current_prompt = (
                    "You have inspected the codebase, but have not made any file changes yet to resolve the issue. "
                    "Please locate the specific file, use the edit or write tool to apply the minimal fix, "
                    "and verify your solution."
                )
            else:
                print(f"[{instance_id}] Turn concluded with patch length={len(patch)} bytes.")
                break

    if runner is not None:
        runner.finalize()

    elapsed = time.time() - start_time
    patch = opencode.get_git_diff()

    # Save patch
    patch_file = instance_output / "model_patch.diff"
    patch_file.write_text(patch, encoding="utf-8")

    # Save all steps for observability across both Base and Sentry runs
    steps_file = instance_output / "steps.jsonl"
    with steps_file.open("w", encoding="utf-8") as f:
        for st in all_steps:
            st_dict = {
                "step_id": st.step_id,
                "timestamp": st.timestamp.isoformat() if hasattr(st, "timestamp") and st.timestamp else None,
                "tool_name": st.action.tool_name if hasattr(st, "action") and st.action else None,
                "raw_action": st.action.raw if hasattr(st, "action") and st.action else None,
                "tool_args": st.action.tool_args if hasattr(st, "action") and st.action else {},
                "accepted_by_environment": st.action.accepted_by_environment if hasattr(st, "action") and st.action else None,
                "observation": (st.observation[:2000] if st.observation else "") if hasattr(st, "observation") else "",
                "metadata": st.metadata if hasattr(st, "metadata") else {},
            }
            f.write(json.dumps(st_dict, ensure_ascii=False) + "\n")

    # Save events if Sentry was used
    events = runner.guard.drain_runtime_events() if runner else []
    with (instance_output / "sentry_events.jsonl").open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    sentry_tokens = runner.model.accumulated_usage if runner and hasattr(runner, "model") and hasattr(runner.model, "accumulated_usage") else {}
    summary = {
        "instance_id": instance_id,
        "repo": instance["repo"],
        "use_sentry": use_sentry,
        "opencode_model": opencode_model or "default",
        "sentry_model": sentry_cfg.model.model if (use_sentry and sentry_cfg) else None,
        "elapsed_seconds": elapsed,
        "total_steps": len(all_steps),
        "interventions": interventions,
        "patch_length": len(patch),
        "patch_file": str(patch_file),
        "opencode_tokens": opencode.token_usage,
        "sentry_tokens": sentry_tokens,
        "cumulative_tokens": opencode.token_usage.get("cumulative_total", 0) + sentry_tokens.get("total_tokens", 0),
        "session_net_tokens": opencode.token_usage.get("net_session_tokens", 0) + sentry_tokens.get("total_tokens", 0),
        "total_tokens": opencode.token_usage.get("cumulative_total", 0) + sentry_tokens.get("total_tokens", 0),
    }

    summary_file = instance_output / "summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n=== Finished {instance_id} in {elapsed:.1f}s | Steps: {len(all_steps)} | Interventions: {interventions} | Patch: {len(patch)} bytes ===")
    print(f"OpenCode Context Window: {opencode.token_usage.get('max_context_window', 0)} | Net Session Tokens: {opencode.token_usage.get('net_session_tokens', 0)}")
    print(f"Cumulative API Tokens (Billed): {opencode.token_usage.get('cumulative_total', 0)} | Sentry Tokens: {sentry_tokens}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run OpenCode + Sentry on SWE-bench Lite")
    parser.add_argument("--instance-id", type=str, default=None, help="Specific SWE-bench instance ID")
    parser.add_argument("--index", type=int, default=0, help="Index of task in SWE-bench Lite")
    parser.add_argument("--no-sentry", action="store_true", help="Run baseline without Sentry")
    parser.add_argument("--provider", type=str, choices=["opencode", "lmstudio"], default="lmstudio", help="LLM backend for Sentry")
    parser.add_argument("--config", type=str, default=None, help="Explicit Sentry config YAML file")
    parser.add_argument("--opencode-model", type=str, default="google/gemini-3.5-flash-lite", help="Model for OpenCode CLI")
    parser.add_argument("--opencode-variant", type=str, default=None, help="Reasoning effort variant for OpenCode (e.g. low, high, max)")
    parser.add_argument("--openrouter-key", type=str, default=None, help="OpenRouter API key")
    parser.add_argument("--check-interval", type=int, default=5, help="Steps between Sentry evaluations")
    parser.add_argument("--check-on-error", action="store_true", default=True, help="Evaluate Sentry immediately on tool errors")
    parser.add_argument("--opencode-bin", type=str, default=None, help="Explicit path to opencode binary")
    parser.add_argument("--workspaces", type=Path, default=Path("workspaces"), help="Workspaces directory")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/swebench"), help="Outputs directory")
    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        config_path = f"configs/providers/{args.provider}.yaml"

    instance = fetch_swebench_instance(args.instance_id, args.index)
    result = run_instance(
        instance,
        use_sentry=not args.no_sentry,
        sentry_config_path=config_path,
        opencode_model=args.opencode_model,
        opencode_variant=args.opencode_variant,
        openrouter_key=args.openrouter_key,
        opencode_bin=args.opencode_bin,
        check_interval=args.check_interval,
        check_on_error=args.check_on_error,
        workspaces_dir=args.workspaces,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
