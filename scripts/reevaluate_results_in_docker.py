#!/usr/bin/env python3
"""Re-evaluate benchmark results with detailed test category metrics (FAIL_TO_PASS, PASS_TO_PASS)."""

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def eval_patch(instance_id: str, patch_file: str) -> dict:
    if not patch_file or not Path(patch_file).exists() or os.path.getsize(patch_file) == 0:
        return {
            "resolved": False,
            "fail_to_pass": {"total": 0, "passed": 0, "failed": 0, "success": [], "failure": []},
            "pass_to_pass": {"total": 0, "passed": 0, "failed": 0, "success": [], "failure": []},
            "test_counts": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "duration_seconds": 0.0,
            "exit_code": -1,
        }

    cmd = [
        str(PROJECT_ROOT / "run_in_docker.sh"),
        "eval",
        instance_id,
        patch_file,
        "--reset-to-base",
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120)
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
        print(f"  ⚠️ Error evaluating {instance_id} ({patch_file}): {e}")

    return {
        "resolved": False,
        "fail_to_pass": {"total": 0, "passed": 0, "failed": 0, "success": [], "failure": []},
        "pass_to_pass": {"total": 0, "passed": 0, "failed": 0, "success": [], "failure": []},
        "test_counts": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "duration_seconds": 0.0,
        "exit_code": -1,
    }


def reevaluate_batch(results_path: Path, concurrency: int = 5):
    data = json.loads(results_path.read_text(encoding="utf-8"))
    total = len(data)
    print(f"🚀 Re-evaluating {total} tasks from {results_path} with concurrency {concurrency}...")

    def process_task(task_item):
        tid, modes = task_item
        b = modes.get("base", {})
        s = modes.get("sentry", {})
        b_patch = b.get("patch_file")
        s_patch = s.get("patch_file")

        print(f"[{tid}] 🧪 Evaluating Base...")
        b_res = eval_patch(tid, b_patch)

        print(f"[{tid}] 🧪 Evaluating Sentry...")
        s_res = eval_patch(tid, s_patch)

        return tid, b_res, s_res

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(process_task, item): item[0] for item in data.items()}
        for future in concurrent.futures.as_completed(futures):
            tid = futures[future]
            try:
                tid, b_ev, s_ev = future.result()
                if "base" in data[tid]:
                    data[tid]["base"]["resolved"] = b_ev.get("resolved", False)
                    data[tid]["base"]["fail_to_pass"] = b_ev.get("fail_to_pass")
                    data[tid]["base"]["pass_to_pass"] = b_ev.get("pass_to_pass")
                    data[tid]["base"]["test_counts"] = b_ev.get("test_counts")
                if "sentry" in data[tid]:
                    data[tid]["sentry"]["resolved"] = s_ev.get("resolved", False)
                    data[tid]["sentry"]["fail_to_pass"] = s_ev.get("fail_to_pass")
                    data[tid]["sentry"]["pass_to_pass"] = s_ev.get("pass_to_pass")
                    data[tid]["sentry"]["test_counts"] = s_ev.get("test_counts")

                b_f2p = b_ev.get("fail_to_pass", {})
                s_f2p = s_ev.get("fail_to_pass", {})
                bp = b_f2p.get('passed', 0); bt = b_f2p.get('total', 0); sp = s_f2p.get('passed', 0); st = s_f2p.get('total', 0); print(f"✅ [{tid}] Done! Base F2P: {bp}/{bt} | Sentry F2P: {sp}/{st}")
                
                results_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"❌ Error on {tid}: {e}")

    results_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"🎉 Completed all evaluations! Results saved to {results_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=str, default="outputs/batch_20tasks_iter1/results.json")
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    rpath = Path(args.results)
    reevaluate_batch(rpath, args.concurrency)
