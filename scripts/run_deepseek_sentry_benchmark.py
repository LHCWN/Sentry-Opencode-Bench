#!/usr/bin/env python3
"""Benchmark runner for DeepSeek Flash (Agent) + DeepSeek Flash (Sentry Supervisor):
Executes 4 iterations across the 20 SWE-bench Lite tasks (Seed 42) with concurrency = 10.
For each iteration:
  - Runs isolated batch (10 parallel workers in Docker, anonymous /app/workspace, default-deny network)
  - Uses CrazyRouter DeepSeek Flash for both OpenCode agent and Sentry supervisor
  - Re-evaluates ground-truth tests in Docker with full category metrics (FAIL_TO_PASS, PASS_TO_PASS)
  - Generates separate HTML reports:
      * reports/benchmark_report_deepseek_sentry_iter{it}.html
      * reports/benchmark_report_deepseek_sentry.html (live latest)
      * reports/multi_iteration_report_deepseek_sentry.html (multi-run aggregate)
  - Automatically commits and pushes progress to GitHub
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
    start_iter = 1
    end_iter = 4
    concurrency = 10
    if len(sys.argv) > 1:
        start_iter = int(sys.argv[1])
    if len(sys.argv) > 2:
        end_iter = int(sys.argv[2])
    if len(sys.argv) > 3:
        concurrency = int(sys.argv[3])

    sentry_config = "configs/providers/crazyrouter_deepseek.yaml"

    print("=" * 80)
    print(f"🚀 OpenCode + Sentry (DeepSeek Flash Supervisor) Benchmark Runner")
    print(f"   Target: 20 tasks SWE-bench Lite (Seed 42)")
    print(f"   Iterations: {start_iter} through {end_iter} (Total: {end_iter - start_iter + 1} runs)")
    print(f"   Concurrency: {concurrency} parallel workers")
    print(f"   Agent Model: crazyrouter/deepseek-flash (variant: high)")
    print(f"   Sentry Model: deepseek-flash (via CrazyRouter API)")
    print(f"   Sentry Config: {sentry_config}")
    print(f"   Time start: {datetime.datetime.now().isoformat()}")
    print("=" * 80)

    overall_start = time.time()

    for it in range(start_iter, end_iter + 1):
        iter_start = time.time()
        iter_dir = PROJECT_ROOT / f"outputs/batch_20tasks_deepseek_sentry_iter{it}"
        results_file = iter_dir / "results.json"

        print(f"\n{'#'*80}")
        print(f"### STARTING DEEPSEEK-SENTRY ITERATION {it} / {end_iter} [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
        print(f"### Output Directory: {iter_dir}")
        print(f"{'#'*80}\n")

        # 1. Run isolated batch of 20 tasks (concurrency 10, max-steps 60)
        run_batch_cmd = [
            sys.executable,
            "scripts/run_isolated_batch.py",
            "--concurrency", str(concurrency),
            "--max-steps", "60",
            "--sentry-config", sentry_config,
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
                "--concurrency", str(concurrency),
            ]
            run_cmd(run_eval_cmd, check=False)

        # 3. Save results to reports directory
        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        iter_results_copy = reports_dir / f"results_deepseek_sentry_iter{it}.json"
        live_results_copy = reports_dir / "results_deepseek_sentry.json"
        if results_file.exists():
            data_text = results_file.read_text(encoding="utf-8")
            iter_results_copy.write_text(data_text, encoding="utf-8")
            live_results_copy.write_text(data_text, encoding="utf-8")

        # 4. Generate HTML reports (iteration-specific + live dashboard)
        iter_html = reports_dir / f"benchmark_report_deepseek_sentry_iter{it}.html"
        live_html = reports_dir / "benchmark_report_deepseek_sentry.html"

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

        # 5. Generate / Update Multi-Iteration aggregate summary
        multi_json = reports_dir / "multi_iteration_summary_deepseek_sentry.json"
        multi_html = reports_dir / "multi_iteration_report_deepseek_sentry.html"
        print(f"\n📈 Updating Multi-Iteration Summary (Iterations 1..{it})...")
        run_cmd([
            sys.executable, "scripts/generate_multi_iteration_summary.py",
            "--outputs-dir", str(PROJECT_ROOT / "outputs"),
            "--pattern", "batch_20tasks_deepseek_sentry_iter{i}",
            "--max-iters", str(end_iter),
            "--output-json", str(multi_json),
            "--output-html", str(multi_html),
        ], check=False)

        # 6. Commit and push progress to GitHub
        print(f"\n💾 Committing and pushing results for Iteration {it} to GitHub...")
        run_cmd(["git", "add", "reports/", str(iter_dir)], check=False)
        run_cmd(["git", "commit", "-m", f"feat(benchmark): add DeepSeek Sentry iteration {it}/{end_iter} results and reports"], check=False)
        run_cmd(["git", "push", "origin", "main"], check=False)

        iter_elapsed = time.time() - iter_start
        print(f"\n✅ Iteration {it} finished in {iter_elapsed / 60:.1f} minutes ({iter_elapsed:.1f}s)")

    total_elapsed = time.time() - overall_start
    print(f"\n🎉 All {end_iter - start_iter + 1} iterations completed in {total_elapsed / 60:.1f} minutes!")

if __name__ == "__main__":
    main()
