#!/usr/bin/env python3
"""Isolated concurrent batch benchmark runner: executes tasks in parallel (default 5 workers),
each in its own dedicated, isolated Docker container where the workspace is mounted as an
anonymous /app/workspace.
Guarantees zero leakage across tasks, zero hints in file paths, and default-deny networking.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

TARGET_20_TASKS = [
    "sympy__sympy-11870",
    "django__django-12308",
    "django__django-11099",
    "sympy__sympy-15308",
    "django__django-14667",
    "django__django-14017",
    "django__django-13768",
    "django__django-12747",
    "sympy__sympy-15011",
    "django__django-12284",
    "sympy__sympy-13177",
    "sympy__sympy-22005",
    "pytest-dev__pytest-7220",
    "django__django-11999",
    "sphinx-doc__sphinx-7975",
    "django__django-16816",
    "django__django-11179",
    "django__django-11133",
    "django__django-12113",
    "django__django-13710",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
results_lock = threading.Lock()


def find_latest_run_summary(runs_dir: Path, instance_id: str, suffix: str) -> dict | None:
    if not runs_dir.exists():
        return None
    matches = sorted(runs_dir.glob(f"*{suffix}/{instance_id}/summary.json"), key=os.path.getmtime, reverse=True)
    if matches and matches[0].exists():
        try:
            return json.loads(matches[0].read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def evaluate_task_patch(instance_id: str, patch_file: str) -> dict:
    if not patch_file or not Path(patch_file).exists() or os.path.getsize(patch_file) == 0:
        return {"resolved": False, "fail_to_pass_count": 0, "duration_seconds": 0.0, "exit_code": -1}
    cmd = [
        str(PROJECT_ROOT / "run_in_docker.sh"),
        "eval",
        instance_id,
        patch_file,
        "--reset-to-base",
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=300)
        out = proc.stdout
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        start_idx = out.find("{")
        end_idx = out.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(out[start_idx : end_idx + 1])
    except Exception as e:
        print(f"  ⚠️ Eval failed for {instance_id}: {e}")
    return {"resolved": False, "fail_to_pass_count": 0, "duration_seconds": 0.0, "exit_code": -1}


def process_single_task(
    instance_id: str,
    idx: int,
    total: int,
    *,
    runs_dir: Path,
    results_file: Path,
    max_steps: int,
    force: bool,
    rerun_failed: bool,
    evaluate: bool,
    sentry_config: str | None = None,
) -> None:
    print(f"\n[{idx}/{total}] 🟢 Starting task: {instance_id}")

    with results_lock:
        try:
            results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
        except Exception:
            results = {}
        if instance_id not in results:
            results[instance_id] = {}
        task_data = results[instance_id]

    # 1. Base Run (No Sentry)
    need_base = (
        force
        or "base" not in task_data
        or (rerun_failed and ("error" in task_data.get("base", {}) or task_data.get("base", {}).get("total_steps", 0) == 0))
    )
    if need_base:
        print(f"[{instance_id}] --- Running BASE (No Sentry) ---")
        t0 = time.time()
        base_cmd = [
            str(PROJECT_ROOT / "run_in_docker.sh"),
            "single",
            instance_id,
            "--no-sentry",
            "--max-steps", str(max_steps),
            "--output-dir", str(runs_dir),
        ]
        subprocess.run(base_cmd, cwd=str(PROJECT_ROOT), check=False)
        summary = find_latest_run_summary(runs_dir, instance_id, "_base")
        with results_lock:
            try:
                results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
            except Exception:
                results = {}
            if instance_id not in results:
                results[instance_id] = {}
            if summary:
                results[instance_id]["base"] = summary
            else:
                results[instance_id]["base"] = {"error": "No summary produced", "elapsed_seconds": time.time() - t0, "total_steps": 0}
            results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    else:
        print(f"[{instance_id}] BASE already completed.")

    # 2. Sentry Run
    with results_lock:
        try:
            results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
        except Exception:
            results = {}
        task_data = results.get(instance_id, {})

    need_sentry = (
        force
        or "sentry" not in task_data
        or (rerun_failed and ("error" in task_data.get("sentry", {}) or task_data.get("sentry", {}).get("total_steps", 0) == 0))
    )
    if need_sentry:
        print(f"[{instance_id}] --- Running SENTRY ---")
        t0 = time.time()
        sentry_cmd = [
            str(PROJECT_ROOT / "run_in_docker.sh"),
            "single",
            instance_id,
            "--max-steps", str(max_steps),
            "--output-dir", str(runs_dir),
        ]
        if sentry_config:
            sentry_cmd.extend(["--config", sentry_config])
        subprocess.run(sentry_cmd, cwd=str(PROJECT_ROOT), check=False)
        summary = find_latest_run_summary(runs_dir, instance_id, "_sentry")
        with results_lock:
            try:
                results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
            except Exception:
                results = {}
            if instance_id not in results:
                results[instance_id] = {}
            if summary:
                results[instance_id]["sentry"] = summary
            else:
                results[instance_id]["sentry"] = {"error": "No summary produced", "elapsed_seconds": time.time() - t0, "total_steps": 0}
            results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    else:
        print(f"[{instance_id}] SENTRY already completed.")

    # 3. Evaluation
    if evaluate:
        with results_lock:
            try:
                results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
            except Exception:
                results = {}
            task_data = results.get(instance_id, {})

        base_patch = task_data.get("base", {}).get("patch_file")
        if base_patch and "resolved" not in task_data.get("base", {}):
            print(f"[{instance_id}] 🧪 Evaluating BASE patch...")
            ev = evaluate_task_patch(instance_id, base_patch)
            with results_lock:
                try:
                    results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
                except Exception:
                    results = {}
                if instance_id in results and "base" in results[instance_id]:
                    results[instance_id]["base"]["resolved"] = ev.get("resolved", False)
                    results[instance_id]["base"]["fail_to_pass"] = ev.get("fail_to_pass")
                    results[instance_id]["base"]["pass_to_pass"] = ev.get("pass_to_pass")
                    results[instance_id]["base"]["test_counts"] = ev.get("test_counts")
                results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

        sentry_patch = task_data.get("sentry", {}).get("patch_file")
        if sentry_patch and "resolved" not in task_data.get("sentry", {}):
            print(f"[{instance_id}] 🧪 Evaluating SENTRY patch...")
            ev = evaluate_task_patch(instance_id, sentry_patch)
            with results_lock:
                try:
                    results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
                except Exception:
                    results = {}
                if instance_id in results and "sentry" in results[instance_id]:
                    results[instance_id]["sentry"]["resolved"] = ev.get("resolved", False)
                    results[instance_id]["sentry"]["fail_to_pass"] = ev.get("fail_to_pass")
                    results[instance_id]["sentry"]["pass_to_pass"] = ev.get("pass_to_pass")
                    results[instance_id]["sentry"]["test_counts"] = ev.get("test_counts")
                results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")


    # Generate updated HTML report
    with results_lock:
        report_cmd = [
            str(PROJECT_ROOT / "run_in_docker.sh"),
            "report",
            "--results", str(results_file),
            "--output", "reports/benchmark_report_deepseek_flash.html",
        ]
        subprocess.run(report_cmd, cwd=str(PROJECT_ROOT), capture_output=True, check=False)
        print(f"[{idx}/{total}] ✅ Finished task: {instance_id}")


def run_batch(
    task_ids: list[str],
    *,
    output_dir: Path,
    max_steps: int = 60,
    concurrency: int = 5,
    force: bool = False,
    rerun_failed: bool = False,
    evaluate: bool = True,
    sentry_config: str | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "runs"
    results_file = output_dir / "results.json"

    print("=" * 70)
    print(f"🚀 Running Isolated Benchmark across {len(task_ids)} tasks")
    print(f"Concurrency: {concurrency} parallel workers")
    print(f"Max steps: {max_steps} | Output directory: {output_dir}")
    if sentry_config:
        print(f"Sentry Config: {sentry_config}")
    print(f"Container Workspace: /app/workspace (anonymous, zero task hints)")
    print("=" * 70)

    total = len(task_ids)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                process_single_task,
                instance_id,
                idx,
                total,
                runs_dir=runs_dir,
                results_file=results_file,
                max_steps=max_steps,
                force=force,
                rerun_failed=rerun_failed,
                evaluate=evaluate,
                sentry_config=sentry_config,
            ): instance_id
            for idx, instance_id in enumerate(task_ids, 1)
        }
        for future in concurrent.futures.as_completed(futures):
            inst = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"❌ Error in worker for {inst}: {e}")

    print("\n🎉 All tasks in batch completed!")


def main():
    parser = argparse.ArgumentParser(description="Run isolated benchmark per task with concurrency")
    parser.add_argument("--tasks", nargs="+", default=TARGET_20_TASKS, help="Task IDs to evaluate")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/batch_deepseek_flash"), help="Output directory")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of parallel tasks (default: 5)")
    parser.add_argument("--max-steps", type=int, default=60, help="Max steps per task")
    parser.add_argument("--force", action="store_true", help="Force re-run all tasks")
    parser.add_argument("--rerun-failed", action="store_true", help="Rerun failed tasks")
    parser.add_argument("--sentry-config", type=str, default=None, help="Path to Sentry config YAML")
    args = parser.parse_args()

    run_batch(
        args.tasks,
        output_dir=args.output_dir,
        concurrency=args.concurrency,
        max_steps=args.max_steps,
        force=args.force,
        rerun_failed=args.rerun_failed,
        sentry_config=args.sentry_config,
    )


if __name__ == "__main__":
    main()
