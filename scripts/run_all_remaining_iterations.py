#!/usr/bin/env python3
"""Master benchmark orchestrator:
Executes remaining iterations (default: 2, 3, 4, 5) of the 20-task SWE-bench Lite benchmark.
For each iteration:
  - Runs isolated batch (5 parallel workers, anonymous /app/workspace, default-deny network)
  - Performs ground-truth test evaluation in Docker with full category metrics
  - Generates HTML reports and updates live dashboard
  - Updates multi-iteration summary report
  - Commits and pushes results to remote GitHub repository
"""
import datetime
from pathlib import Path
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def run_cmd(cmd: list[str], check: bool = True) -> int:
    cmd_str = " ".join(str(c) for c in cmd)
    print(f"\n[RUN] {cmd_str}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if check and proc.returncode != 0:
        print(f"⚠️ Command returned non-zero exit code: {proc.returncode}")
    return proc.returncode

def main():
    start_iter = 2
    end_iter = 5
    if len(sys.argv) > 1:
        start_iter = int(sys.argv[1])
    if len(sys.argv) > 2:
        end_iter = int(sys.argv[2])

    print("=" * 80)
    print(f"🚀 OpenCode + Sentry Automated Benchmark Runner")
    print(f"   Target: 20 tasks SWE-bench Lite (Seed 42)")
    print(f"   Iterations to run: {start_iter} through {end_iter}")
    print(f"   Time start: {datetime.datetime.now().isoformat()}")
    print("=" * 80)

    overall_start = time.time()

    for it in range(start_iter, end_iter + 1):
        iter_start = time.time()
        iter_dir = PROJECT_ROOT / f"outputs/batch_20tasks_iter{it}"
        results_file = iter_dir / "results.json"

        print(f"\n{'#'*80}")
        print(f"### STARTING ITERATION {it} / {end_iter} [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
        print(f"### Output Directory: {iter_dir}")
        print(f"{'#'*80}\n")

        # 1. Run isolated batch of 20 tasks (concurrency 5, max-steps 60)
        run_batch_cmd = [
            sys.executable,
            "scripts/run_isolated_batch.py",
            "--concurrency", "5",
            "--max-steps", "60",
            "--output-dir", str(iter_dir),
        ]
        ret = run_cmd(run_batch_cmd, check=False)
        print(f"Batch execution for iteration {it} returned code {ret}")

        # 2. Re-evaluate results in Docker with exact SWE-bench categories
        if results_file.exists():
            print(f"\n🧪 Re-evaluating ground-truth test metrics for Iteration {it}...")
            run_eval_cmd = [
                sys.executable,
                "scripts/reevaluate_results_in_docker.py",
                "--results", str(results_file),
                "--concurrency", "5",
            ]
            run_cmd(run_eval_cmd, check=False)

        # 3. Copy results to reports
        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        iter_results_copy = reports_dir / f"results_iter{it}.json"
        live_results_copy = reports_dir / "results_deepseek_flash.json"
        if results_file.exists():
            iter_results_copy.write_text(results_file.read_text(encoding="utf-8"), encoding="utf-8")
            live_results_copy.write_text(results_file.read_text(encoding="utf-8"), encoding="utf-8")

        # 4. Generate HTML reports (iteration-specific + live dashboard)
        iter_html = reports_dir / f"benchmark_report_iter{it}.html"
        live_html = reports_dir / "benchmark_report_deepseek_flash.html"

        if results_file.exists():
            print(f"\n📊 Generating HTML reports for Iteration {it}...")
            run_cmd([
                sys.executable, "scripts/generate_html_report.py",
                "--results", str(results_file),
                "--output", str(iter_html),
            ], check=False)

            run_cmd([
                sys.executable, "scripts/generate_html_report.py",
                "--results", str(results_file),
                "--output", str(live_html),
            ], check=False)

        # 5. Generate / Update multi-iteration summary report
        print(f"\n📈 Updating multi-iteration summary report...")
        run_cmd([sys.executable, "scripts/generate_multi_iteration_summary.py"], check=False)

        # 6. Git add, commit, and push
        print(f"\n💾 Committing and pushing Iteration {it} results to GitHub...")
        run_cmd(["git", "add", f"outputs/batch_20tasks_iter{it}", "reports/"], check=False)
        run_cmd(["git", "commit", "-m", f"chore(bench): complete iteration {it}/{end_iter} results and category metrics"], check=False)
        run_cmd(["git", "push", "origin", "main"], check=False)

        iter_dur = time.time() - iter_start
        print(f"\n✅ ITERATION {it} / {end_iter} COMPLETED in {iter_dur / 60:.1f} minutes!")

    total_dur = time.time() - overall_start
    print(f"\n{'='*80}")
    print(f"🎉 ALL ITERATIONS ({start_iter}..{end_iter}) FINISHED in {total_dur / 3600:.2f} hours!")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
