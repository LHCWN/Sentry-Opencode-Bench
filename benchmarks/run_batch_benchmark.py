"""Batch benchmark runner comparing OpenCode Base vs OpenCode + Sentry across 10 SWE-bench Lite tasks."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from benchmarks.swebench_runner import fetch_swebench_instance, run_instance

CANDIDATE_TASKS = [
    "psf__requests-2317",
    "pallets__flask-4045",
    "pallets__flask-4992",
    "pallets__flask-5063",
    "psf__requests-1963",
    "psf__requests-2148",
    "psf__requests-2674",
    "psf__requests-3362",
    "psf__requests-863",
    "pytest-dev__pytest-11143",
]


def run_batch(
    task_ids: list[str],
    *,
    opencode_model: str = "openrouter/nvidia/nemotron-3.5-lightning:free",
    openrouter_key: str | None = None,
    sentry_config_path: str = "configs/providers/lmstudio.yaml",
    output_dir: Path = Path("outputs/batch_benchmark"),
    max_steps_per_task: int = 25,
    check_interval: int = 5,
    check_on_error: bool = True,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "results.json"

    results: dict[str, dict] = {}
    if results_file.exists():
        try:
            results = json.loads(results_file.read_text(encoding="utf-8"))
            print(f"Loaded existing results for {len(results)} tasks.")
        except Exception:
            results = {}

    print(f"\n=======================================================")
    print(f"🚀 Starting Batch Evaluation across {len(task_ids)} tasks")
    print(f"OpenCode Model: {opencode_model}")
    print(f"Sentry Config: {sentry_config_path}")
    print(f"Sentry Check Policy: every {check_interval} steps and on error")
    print(f"=======================================================\n")

    for idx, instance_id in enumerate(task_ids, start=1):
        print(f"\n[{idx}/{len(task_ids)}] >>> Task: {instance_id} <<<")
        if instance_id not in results:
            results[instance_id] = {}

        task_data = results[instance_id]

        try:
            instance = fetch_swebench_instance(instance_id)
        except Exception as e:
            print(f"Error fetching instance {instance_id}: {e}")
            continue

        # 1. Run Base (without Sentry) if not already done
        if "base" not in task_data:
            print(f"\n--- Running BASE (no Sentry) for {instance_id} ---")
            t0 = time.time()
            try:
                base_res = run_instance(
                    instance,
                    use_sentry=False,
                    opencode_model=opencode_model,
                    openrouter_key=openrouter_key,
                    max_total_steps=max_steps_per_task,
                    output_dir=output_dir / "runs",
                )
                task_data["base"] = base_res
            except Exception as e:
                print(f"Error in BASE run for {instance_id}: {e}")
                task_data["base"] = {"error": str(e), "elapsed_seconds": time.time() - t0}
            results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
        else:
            print(f"BASE run already completed for {instance_id}.")

        # 2. Run Sentry if not already done
        if "sentry" not in task_data:
            print(f"\n--- Running SENTRY for {instance_id} ---")
            t0 = time.time()
            try:
                sentry_res = run_instance(
                    instance,
                    use_sentry=True,
                    sentry_config_path=sentry_config_path,
                    opencode_model=opencode_model,
                    openrouter_key=openrouter_key,
                    max_total_steps=max_steps_per_task,
                    check_interval=check_interval,
                    check_on_error=check_on_error,
                    output_dir=output_dir / "runs",
                )
                task_data["sentry"] = sentry_res
            except Exception as e:
                print(f"Error in SENTRY run for {instance_id}: {e}")
                task_data["sentry"] = {"error": str(e), "elapsed_seconds": time.time() - t0}
            results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
        else:
            print(f"SENTRY run already completed for {instance_id}.")

    # Generate Markdown Summary Table
    print_comparative_table(results)
    return results


def print_comparative_table(results: dict):
    print("\n" + "=" * 90)
    print("🎯 BATCH EVALUATION COMPARATIVE SUMMARY")
    print("=" * 90)
    header = f"{'Task ID':<24} | {'Mode':<7} | {'Steps':<5} | {'Intrv':<5} | {'Time (s)':<8} | {'Net Tok':<10} | {'Billed Tok':<11} | {'Sentry Tok':<10} | {'Patch (B)':<9}"
    print(header)
    print("-" * len(header))

    for task_id, modes in results.items():
        base = modes.get("base", {})
        sentry = modes.get("sentry", {})

        b_steps = str(base.get("total_steps", "ERR"))
        b_time = f"{base.get('elapsed_seconds', 0):.1f}"
        b_net = str(base.get("session_net_tokens", base.get("opencode_tokens", {}).get("net_session_tokens", "-")))
        b_cumul = str(base.get("cumulative_tokens", base.get("opencode_tokens", {}).get("total", base.get("total_tokens", 0))))
        b_patch = str(base.get("patch_length", 0))

        s_steps = str(sentry.get("total_steps", "ERR"))
        s_interv = str(sentry.get("interventions", 0))
        s_time = f"{sentry.get('elapsed_seconds', 0):.1f}"
        s_net = str(sentry.get("session_net_tokens", sentry.get("opencode_tokens", {}).get("net_session_tokens", "-")))
        s_cumul = str(sentry.get("cumulative_tokens", sentry.get("total_tokens", 0)))
        s_sent_tok = str(sentry.get("sentry_tokens", {}).get("total_tokens", 0))
        s_patch = str(sentry.get("patch_length", 0))

        print(f"{task_id:<24} | {'Base':<7} | {b_steps:<5} | {'-':<5} | {b_time:<8} | {b_net:<10} | {b_cumul:<11} | {'-':<10} | {b_patch:<9}")
        print(f"{'':<24} | {'Sentry':<7} | {s_steps:<5} | {s_interv:<5} | {s_time:<8} | {s_net:<10} | {s_cumul:<11} | {s_sent_tok:<10} | {s_patch:<9}")
        print("-" * len(header))


def main():
    parser = argparse.ArgumentParser(description="Run 10-task SWE-bench Lite comparison")
    parser.add_argument("--tasks", nargs="+", default=CANDIDATE_TASKS, help="Task IDs to evaluate")
    parser.add_argument("--model", type=str, default="google/gemini-3.5-flash-lite", help="OpenCode model")
    parser.add_argument("--key", type=str, default=None, help="OpenRouter Key")
    parser.add_argument("--sentry-config", type=str, default="configs/providers/lmstudio.yaml", help="Sentry config")
    parser.add_argument("--max-steps", type=int, default=25, help="Max steps per task")
    args = parser.parse_args()

    run_batch(
        args.tasks,
        opencode_model=args.model,
        openrouter_key=args.key,
        sentry_config_path=args.sentry_config,
        max_steps_per_task=args.max_steps,
    )


if __name__ == "__main__":
    main()
