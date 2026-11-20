#!/usr/bin/env python3
"""Multi-Iteration Benchmark Aggregator:
Compiles results across iterations 1 to 5, calculating:
- Pass@1 per iteration and Pass@k (any iteration resolved)
- Detailed FAIL_TO_PASS and PASS_TO_PASS progression
- Aggregate token savings and step reductions
- Generates reports/multi_iteration_summary.json and reports/multi_iteration_report.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_iteration_results(outputs_dir: Path, max_iters: int = 5, pattern: str = "batch_20tasks_iter{i}") -> dict[int, dict]:
    iterations = {}
    for i in range(1, max_iters + 1):
        res_file = outputs_dir / pattern.format(i=i) / "results.json"
        if res_file.is_file():
            try:
                data = json.loads(res_file.read_text(encoding="utf-8"))
                iterations[i] = data
            except Exception as e:
                print(f"⚠️ Could not load {res_file}: {e}")
    return iterations


def aggregate_metrics(iterations: dict[int, dict], outputs_dir: Path | None = None) -> dict:
    if not iterations:
        return {}

    all_tasks = set()
    for iter_data in iterations.values():
        all_tasks.update(iter_data.keys())
    task_list = sorted(all_tasks)

    summary_per_task = {}
    for tid in task_list:
        summary_per_task[tid] = {
            "base_resolved_iters": [],
            "sentry_resolved_iters": [],
            "base_f2p_rates": [],
            "sentry_f2p_rates": [],
            "base_steps": [],
            "sentry_steps": [],
            "base_tokens": [],
            "sentry_tokens": [],
            "sentry_evaluations": [],
            "sentry_interventions": [],
        }
        for it_num, it_data in sorted(iterations.items()):
            t_data = it_data.get(tid, {})
            b = t_data.get("base", {}) or {}
            s = t_data.get("sentry", {}) or {}

            b_res = bool(b.get("resolved", False))
            s_res = bool(s.get("resolved", False))

            if b_res:
                summary_per_task[tid]["base_resolved_iters"].append(it_num)
            if s_res:
                summary_per_task[tid]["sentry_resolved_iters"].append(it_num)

            bf = b.get("fail_to_pass") or {}
            sf = s.get("fail_to_pass") or {}
            summary_per_task[tid]["base_f2p_rates"].append(f"{bf.get('passed', 0)}/{bf.get('total', 0)}")
            summary_per_task[tid]["sentry_f2p_rates"].append(f"{sf.get('passed', 0)}/{sf.get('total', 0)}")

            summary_per_task[tid]["base_steps"].append(b.get("total_steps", 0))
            summary_per_task[tid]["sentry_steps"].append(s.get("total_steps", 0))

            b_tok = b.get("cumulative_tokens") or b.get("total_tokens") or b.get("billed_tokens") or 0
            s_tok = s.get("cumulative_tokens") or s.get("total_tokens") or s.get("billed_tokens") or 0
            s_sentry_only = (s.get("sentry_tokens") or {}).get("total_tokens", 0)
            if s.get("opencode_tokens", {}).get("cumulative_total") and s_tok == s.get("opencode_tokens", {}).get("cumulative_total"):
                s_tok += s_sentry_only
            summary_per_task[tid]["base_tokens"].append(b_tok)
            summary_per_task[tid]["sentry_tokens"].append(s_tok)

            s_intrv = s.get("interventions", s.get("interventions_count", 0))
            summary_per_task[tid]["sentry_interventions"].append(s_intrv)

            eval_count = 0
            pf = s.get("patch_file", "")
            if pf and outputs_dir:
                rel = pf.replace("/app/outputs/", "")
                ev_file = outputs_dir / rel
                ev_file = ev_file.parent / "sentry_events.jsonl"
                if ev_file.is_file():
                    try:
                        for l in ev_file.read_text(encoding="utf-8").splitlines():
                            if '"type": "sentry_diagnosis"' in l:
                                eval_count += 1
                    except Exception:
                        pass
            if eval_count == 0 and s_intrv > 0:
                eval_count = s_intrv
            summary_per_task[tid]["sentry_evaluations"].append(eval_count)

    # Overall stats
    iter_stats = {}
    for idx, (it_num, it_data) in enumerate(sorted(iterations.items())):
        b_res_count = sum(1 for d in it_data.values() if (d.get("base") or {}).get("resolved"))
        s_res_count = sum(1 for d in it_data.values() if (d.get("sentry") or {}).get("resolved"))
        b_steps = sum((d.get("base") or {}).get("total_steps", 0) for d in it_data.values())
        s_steps = sum((d.get("sentry") or {}).get("total_steps", 0) for d in it_data.values())
        b_toks = sum((d.get("base") or {}).get("total_tokens", 0) for d in it_data.values())
        s_toks = sum((d.get("sentry") or {}).get("total_tokens", 0) for d in it_data.values())
        s_intrv = sum((d.get("sentry") or {}).get("interventions", (d.get("sentry") or {}).get("interventions_count", 0)) for d in it_data.values())
        s_evals = sum(summary_per_task[tid]["sentry_evaluations"][idx] for tid in task_list if idx < len(summary_per_task[tid]["sentry_evaluations"]))

        iter_stats[it_num] = {
            "total_tasks": len(it_data),
            "base_resolved": b_res_count,
            "sentry_resolved": s_res_count,
            "base_steps": b_steps,
            "sentry_steps": s_steps,
            "step_reduction_pct": round(((s_steps - b_steps) / b_steps * 100), 1) if b_steps else 0.0,
            "base_tokens": b_toks,
            "sentry_tokens": s_toks,
            "token_savings_pct": round(((s_toks - b_toks) / b_toks * 100), 1) if b_toks else 0.0,
            "sentry_evaluations": s_evals,
            "sentry_interventions": s_intrv,
            "intervention_rate_pct": round(((s_intrv / s_evals) * 100), 1) if s_evals else 0.0,
        }

    # Best-of-K (Pass@k: at least one run resolved)
    b_any_resolved = [tid for tid, d in summary_per_task.items() if len(d["base_resolved_iters"]) > 0]
    s_any_resolved = [tid for tid, d in summary_per_task.items() if len(d["sentry_resolved_iters"]) > 0]

    tot_evals = sum(st["sentry_evaluations"] for st in iter_stats.values())
    tot_intrv = sum(st["sentry_interventions"] for st in iter_stats.values())
    overall_intrv_rate = round((tot_intrv / tot_evals * 100), 1) if tot_evals else 0.0

    return {
        "num_iterations": len(iterations),
        "iterations_present": list(iterations.keys()),
        "total_sentry_evaluations": tot_evals,
        "total_sentry_interventions": tot_intrv,
        "overall_intervention_rate_pct": overall_intrv_rate,
        "iteration_stats": iter_stats,
        "pass_at_k": {
            "base_resolved_count": len(b_any_resolved),
            "sentry_resolved_count": len(s_any_resolved),
            "base_resolved_tasks": b_any_resolved,
            "sentry_resolved_tasks": s_any_resolved,
            "total_tasks": len(task_list),
        },
        "tasks": summary_per_task,
    }


def generate_html_summary(agg: dict, output_path: Path):
    num_iters = agg.get("num_iterations", 0)
    iters = agg.get("iterations_present", [])
    iter_stats = agg.get("iteration_stats", {})
    pass_k = agg.get("pass_at_k", {})
    tasks = agg.get("tasks", {})

    table_rows = []
    for tid, tinfo in sorted(tasks.items()):
        b_res_str = f"{len(tinfo['base_resolved_iters'])}/{num_iters}"
        s_res_str = f"{len(tinfo['sentry_resolved_iters'])}/{num_iters}"

        b_badge = '<span class="status-solved">Resolved</span>' if len(tinfo['base_resolved_iters']) > 0 else '<span class="status-failed">Failed</span>'
        s_badge = '<span class="status-solved">Resolved</span>' if len(tinfo['sentry_resolved_iters']) > 0 else '<span class="status-failed">Failed</span>'

        avg_b_steps = round(sum(tinfo["base_steps"]) / len(tinfo["base_steps"]), 1) if tinfo["base_steps"] else 0
        avg_s_steps = round(sum(tinfo["sentry_steps"]) / len(tinfo["sentry_steps"]), 1) if tinfo["sentry_steps"] else 0

        avg_b_tok = int(sum(tinfo["base_tokens"]) / len(tinfo["base_tokens"])) if tinfo["base_tokens"] else 0
        avg_s_tok = int(sum(tinfo["sentry_tokens"]) / len(tinfo["sentry_tokens"])) if tinfo["sentry_tokens"] else 0
        tok_diff = round(((avg_s_tok - avg_b_tok) / avg_b_tok * 100), 1) if avg_b_tok else 0
        tok_color = "#3fb950" if tok_diff < 0 else "#f85149"

        avg_intrv = round(sum(tinfo["sentry_interventions"]) / len(tinfo["sentry_interventions"]), 1) if tinfo["sentry_interventions"] else 0
        avg_evals = round(sum(tinfo.get("sentry_evaluations", [])) / len(tinfo.get("sentry_evaluations", [1])), 1) if tinfo.get("sentry_evaluations") else 0

        table_rows.append(f"""
        <tr>
            <td style="font-weight: 600; color: #fff;">{tid}</td>
            <td>{b_badge} ({b_res_str})</td>
            <td>{s_badge} ({s_res_str})</td>
            <td>{avg_b_steps} / {avg_s_steps}</td>
            <td>{avg_b_tok:,} / {avg_s_tok:,} <span style="color: {tok_color}; font-weight: 600;">({tok_diff:+.1f}%)</span></td>
            <td><span class="badge">{avg_intrv} / {avg_evals}</span></td>
        </tr>
        """)

    iter_cards = []
    for it_num in iters:
        st = iter_stats.get(it_num, {})
        tok_diff = st.get('token_savings_pct', 0)
        tok_color = "#3fb950" if tok_diff < 0 else "#f85149"
        iter_cards.append(f"""
        <div class="kpi-card">
            <div class="kpi-title">Iteration {it_num}</div>
            <div class="kpi-val" style="font-size: 20px;">Resolved: {st.get('base_resolved', 0)} vs {st.get('sentry_resolved', 0)}</div>
            <div class="kpi-desc">
                Steps: {st.get('base_steps')} &rarr; {st.get('sentry_steps')} ({st.get('step_reduction_pct'):+.1f}%)<br>
                Tokens: <span style="color:{tok_color}; font-weight:600;">{tok_diff:+.1f}%</span><br>
                Interventions: <strong>{st.get('sentry_interventions', 0)} / {st.get('sentry_evaluations', 0)} checks</strong> ({st.get('intervention_rate_pct', 0.0):.1f}%)
            </div>
        </div>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SWE-bench Multi-Iteration Benchmark Summary ({num_iters} Iterations)</title>
    <style>
        :root {{
            --bg-dark: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-muted: #8b949e;
            --accent-blue: #58a6ff;
            --accent-green: #238636;
            --accent-red: #da3633;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            margin: 0; padding: 24px;
        }}
        .container {{ max-width: 1300px; margin: 0 auto; }}
        header {{ margin-bottom: 24px; border-bottom: 1px solid var(--border-color); padding-bottom: 16px; }}
        h1 {{ font-size: 26px; color: #fff; margin: 0 0 8px 0; }}
        .subtitle {{ font-size: 14px; color: var(--text-muted); }}
        .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .kpi-card {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; }}
        .kpi-title {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); }}
        .kpi-val {{ font-size: 24px; font-weight: 700; margin: 8px 0 4px 0; color: #fff; }}
        .kpi-desc {{ font-size: 12px; color: var(--text-muted); }}
        .card {{ background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 24px; overflow: hidden; }}
        .card-header {{ padding: 12px 16px; border-bottom: 1px solid var(--border-color); font-weight: 700; color: #fff; background: rgba(255,255,255,0.02); }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ background: rgba(0,0,0,0.2); font-weight: 600; color: var(--text-muted); }}
        .status-solved {{ background: #238636; color: #fff; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
        .status-failed {{ background: rgba(248,81,73,0.2); color: #f85149; border: 1px solid rgba(248,81,73,0.4); padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
        .badge {{ background: rgba(56,139,253,0.15); color: #58a6ff; border: 1px solid rgba(56,139,253,0.3); border-radius: 10px; padding: 2px 8px; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>SWE-bench Lite Multi-Iteration Benchmark Summary ({num_iters} Iterations)</h1>
            <div class="subtitle">
                Model: <strong>crazyrouter/deepseek-flash</strong> &bull;
                Supervisor: <strong>google/gemma-4-e4b</strong> (LM Studio) &bull;
                Dataset: <strong>SWE-bench Lite (20 tasks, Seed 42)</strong> &bull;
                Mounts: <strong>Isolated /app/workspace</strong> &bull;
                Network Whitelist: <strong>Enforced (Default Deny)</strong>
            </div>
        </header>

        <div class="kpi-row">
            <div class="kpi-card">
                <div class="kpi-title">Completed Iterations</div>
                <div class="kpi-val">{num_iters} / 5</div>
                <div class="kpi-desc">{num_iters * 20 * 2} task executions total</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Pass@k (Any Iteration Solved)</div>
                <div class="kpi-val" style="color: #3fb950;">Base: {pass_k.get('base_resolved_count',0)} | Sentry: {pass_k.get('sentry_resolved_count',0)}</div>
                <div class="kpi-desc">Out of {pass_k.get('total_tasks', 20)} distinct tasks</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Sentry Runtime Supervision</div>
                <div class="kpi-val" style="color: #e3b341;">{agg.get('total_sentry_interventions', 0)} / {agg.get('total_sentry_evaluations', 0)}</div>
                <div class="kpi-desc">Interventions across {agg.get('total_sentry_evaluations', 0)} checks ({agg.get('overall_intervention_rate_pct', 0.0):.1f}%)</div>
            </div>
        </div>

        <h3 style="color:#fff; margin-bottom: 12px;">Iteration-by-Iteration Performance</h3>
        <div class="kpi-row">
            {"".join(iter_cards)}
        </div>

        <div class="card">
            <div class="card-header">Per-Task Consistency Across Iterations</div>
            <table>
                <thead>
                    <tr>
                        <th>Task ID</th>
                        <th>Base (Resolved / Total Iters)</th>
                        <th>Sentry (Resolved / Total Iters)</th>
                        <th>Avg Steps (B / S)</th>
                        <th>Avg Billed Tokens (B / S)</th>
                        <th>Avg Interventions / Checks</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(table_rows)}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"📊 Multi-iteration HTML summary written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Multi-Iteration Aggregator")
    parser.add_argument("--outputs-dir", type=Path, default=PROJECT_ROOT / "outputs")
    parser.add_argument("--pattern", type=str, default="batch_20tasks_iter{i}", help="Directory pattern for iterations")
    parser.add_argument("--max-iters", type=int, default=5)
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "multi_iteration_summary.json")
    parser.add_argument("--output-html", type=Path, default=PROJECT_ROOT / "reports" / "multi_iteration_report.html")
    args = parser.parse_args()

    iters_data = load_iteration_results(args.outputs_dir, args.max_iters, pattern=args.pattern)
    if not iters_data:
        print("No iteration results found.")
        sys.exit(1)

    agg = aggregate_metrics(iters_data, outputs_dir=args.outputs_dir)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Aggregated stats saved to {args.output_json}")

    generate_html_summary(agg, args.output_html)


if __name__ == "__main__":
    main()
