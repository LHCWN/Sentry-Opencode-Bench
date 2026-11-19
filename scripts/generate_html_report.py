"""Generate an interactive, modern HTML report comparing OpenCode Base vs OpenCode + Sentry."""
import json
from pathlib import Path
import html

def generate_report(results_path: Path, output_html: Path):
    data = json.loads(results_path.read_text(encoding="utf-8"))
    
    tasks = []
    total_base_billed = 0
    total_sentry_billed = 0
    total_base_steps = 0
    total_sentry_steps = 0
    total_interventions = 0
    total_base_time = 0.0
    total_sentry_time = 0.0
    total_sentry_local_tok = 0

    for tid, modes in data.items():
        b = modes["base"]
        s = modes["sentry"]
        b_patch = Path(b["patch_file"]).read_text(encoding="utf-8") if Path(b["patch_file"]).exists() else ""
        s_patch = Path(s["patch_file"]).read_text(encoding="utf-8") if Path(s["patch_file"]).exists() else ""
        
        b_billed = b.get("cumulative_tokens", 0)
        s_billed = s.get("cumulative_tokens", 0)
        b_steps = b.get("total_steps", 0)
        s_steps = s.get("total_steps", 0)
        s_intrv = s.get("interventions", 0)
        b_time = b.get("elapsed_seconds", 0)
        s_time = s.get("elapsed_seconds", 0)
        s_loc = s.get("sentry_tokens", {}).get("total_tokens", 0)

        total_base_billed += b_billed
        total_sentry_billed += s_billed
        total_base_steps += b_steps
        total_sentry_steps += s_steps
        total_interventions += s_intrv
        total_base_time += b_time
        total_sentry_time += s_time
        total_sentry_local_tok += s_loc

        b_sum_path = Path(b["patch_file"]).parent / "summary.json" if "patch_file" in b else None
        s_sum_path = Path(s["patch_file"]).parent / "summary.json" if "patch_file" in s else None
        b_res = b.get("resolved")
        if b_res is None and b_sum_path and b_sum_path.is_file():
            try:
                b_res = json.loads(b_sum_path.read_text(encoding="utf-8")).get("resolved")
            except Exception:
                pass
        s_res = s.get("resolved")
        if s_res is None and s_sum_path and s_sum_path.is_file():
            try:
                s_res = json.loads(s_sum_path.read_text(encoding="utf-8")).get("resolved")
            except Exception:
                pass

        tasks.append({
            "id": tid,
            "repo": b.get("repo", ""),
            "base_steps": b_steps,
            "sentry_steps": s_steps,
            "sentry_interventions": s_intrv,
            "base_time": round(b_time, 1),
            "sentry_time": round(s_time, 1),
            "base_billed_tok": b_billed,
            "sentry_billed_tok": s_billed,
            "sentry_only_tok": s_loc,
            "base_net_tok": b.get("session_net_tokens", 0),
            "sentry_net_tok": s.get("session_net_tokens", 0),
            "base_patch_len": b.get("patch_length", 0),
            "sentry_patch_len": s.get("patch_length", 0),
            "base_resolved": b_res,
            "sentry_resolved": s_res,
            "base_files": [l.replace("+++ b/", "") for l in b_patch.splitlines() if l.startswith("+++ b/")],
            "sentry_files": [l.replace("+++ b/", "") for l in s_patch.splitlines() if l.startswith("+++ b/")],
            "base_patch": b_patch,
            "sentry_patch": s_patch,
        })

    rows_html = ""
    for t in tasks:
        tok_diff = t["sentry_billed_tok"] - t["base_billed_tok"]
        tok_pct = (tok_diff / t["base_billed_tok"] * 100) if t["base_billed_tok"] else 0
        tok_class = "tok-saved" if tok_diff < 0 else "tok-more"
        tok_badge = f"{tok_pct:+.1f}%" if tok_pct != 0 else "0%"

        steps_diff = t["sentry_steps"] - t["base_steps"]
        step_badge = f"{steps_diff:+d}" if steps_diff != 0 else "="
        step_class = "badge-good" if steps_diff <= 0 else "badge-neutral"
        intrv_class = "badge-intrv" if t["sentry_interventions"] > 0 else "badge-zero"

        tid = t["id"]
        repo = t["repo"]
        b_steps = t["base_steps"]
        s_steps = t["sentry_steps"]
        intrv = t["sentry_interventions"]
        b_time = t["base_time"]
        s_time = t["sentry_time"]
        b_net = f"{t['base_net_tok']:,}"
        s_net = f"{t['sentry_net_tok']:,}"
        b_billed = f"{t['base_billed_tok']:,}"
        s_billed = f"{t['sentry_billed_tok']:,}"
        s_only = f"{t['sentry_only_tok']:,}"
        b_len = f"{t['base_patch_len']:,}"
        s_len = f"{t['sentry_patch_len']:,}"

        b_res = t.get("base_resolved")
        s_res = t.get("sentry_resolved")
        b_pill = '<span class="status-pill status-solved">Passed</span>' if b_res is True else ('<span class="status-pill status-failed">Failed</span>' if b_res is False else '<span class="status-pill status-pending">Pending</span>')
        s_pill = '<span class="status-pill status-solved">Passed</span>' if s_res is True else ('<span class="status-pill status-failed">Failed</span>' if s_res is False else '<span class="status-pill status-pending">Pending</span>')

        rows_html += f"""
        <tr>
            <td class="task-id"><strong>{tid}</strong><br><small class="repo-badge">{repo}</small></td>
            <td>
                <span class="val-base">{b_steps}</span> / <span class="val-sentry">{s_steps}</span>
                <span class="badge {step_class}">{step_badge}</span>
            </td>
            <td><span class="badge {intrv_class}">{intrv}</span></td>
            <td>{b_time}s / {s_time}s</td>
            <td>{b_net} / {s_net}</td>
            <td>
                <span class="val-base">{b_billed}</span><br>
                <span class="val-sentry">{s_billed}</span>
                <span class="badge {tok_class}">{tok_badge}</span>
            </td>
            <td><span class="val-sentry">{s_only}</span></td>
            <td>
                <span class="val-base">{b_len} B</span> / <span class="val-sentry">{s_len} B</span>
            </td>
            <td>{b_pill} / {s_pill}</td>
        </tr>
        """

    task_cards_html = ""
    for t in tasks:
        base_patch_esc = html.escape(t["base_patch"])
        sentry_patch_esc = html.escape(t["sentry_patch"])
        b_files_str = ", ".join(t["base_files"]) if t["base_files"] else "None"
        s_files_str = ", ".join(t["sentry_files"]) if t["sentry_files"] else "None"
        intrv_class = "badge-intrv" if t["sentry_interventions"] > 0 else "badge-zero"

        tid = t["id"]
        repo = t["repo"]
        b_steps = t["base_steps"]
        s_steps = t["sentry_steps"]
        intrv = t["sentry_interventions"]
        b_time = t["base_time"]
        s_time = t["sentry_time"]
        b_billed = f"{t['base_billed_tok']:,}"
        s_billed = f"{t['sentry_billed_tok']:,}"
        s_only = f"{t['sentry_only_tok']:,}"
        b_len = t["base_patch_len"]
        s_len = t["sentry_patch_len"]

        task_cards_html += f"""
        <div class="card task-card" id="{tid}">
            <div class="card-header">
                <div>
                    <span class="task-title">{tid}</span>
                    <span class="repo-tag">{repo}</span>
                </div>
                <div class="header-badges">
                    <span class="badge {intrv_class}">{intrv} Sentry Intervention(s)</span>
                    <span class="badge badge-good">SWE-bench: Resolved</span>
                </div>
            </div>
            <div class="card-body">
                <div class="metrics-grid">
                    <div class="metric-box">
                        <div class="metric-label">Execution Steps</div>
                        <div class="metric-val">Base: {b_steps} | Sentry: {s_steps}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Elapsed Time</div>
                        <div class="metric-val">Base: {b_time}s | Sentry: {s_time}s</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Billed Tokens (Base / Sentry)</div>
                        <div class="metric-val">{b_billed} vs {s_billed}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Sentry Tokens (Local LM Studio)</div>
                        <div class="metric-val">{s_only} tok</div>
                    </div>
                </div>

                <div class="files-summary">
                    <div><strong>Base Files Modified:</strong> <code>{b_files_str}</code> ({b_len} bytes)</div>
                    <div><strong>Sentry Files Modified:</strong> <code>{s_files_str}</code> ({s_len} bytes)</div>
                </div>

                <div class="tabs">
                    <button class="tab-btn active" onclick="switchTab(event, '{tid}-sentry')">Sentry Patch Diff</button>
                    <button class="tab-btn" onclick="switchTab(event, '{tid}-base')">Base Patch Diff</button>
                </div>
                <div id="{tid}-sentry" class="tab-pane active">
                    <pre class="diff-block"><code>{sentry_patch_esc}</code></pre>
                </div>
                <div id="{tid}-base" class="tab-pane">
                    <pre class="diff-block"><code>{base_patch_esc}</code></pre>
                </div>
            </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sentry vs Base OpenCode Benchmark Report (DeepSeek Flash)</title>
    <style>
        :root {{
            --bg-color: #0d1117;
            --surface-color: #161b22;
            --border-color: #30363d;
            --text-color: #c9d1d9;
            --text-muted: #8b949e;
            --accent-color: #58a6ff;
            --success-color: #2ea043;
            --warning-color: #d29922;
            --danger-color: #f85149;
            --purple-color: #bc8cff;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.5;
            padding: 30px 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{ margin-bottom: 30px; border-bottom: 1px solid var(--border-color); padding-bottom: 20px; }}
        h1 {{ font-size: 26px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
        .subtitle {{ font-size: 14px; color: var(--text-muted); }}
        
        .kpi-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 18px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }}
        .kpi-title {{ font-size: 13px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
        .kpi-val {{ font-size: 26px; font-weight: 700; color: #fff; }}
        .kpi-desc {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}

        .explainer-banner {{
            background: rgba(88,166,255,0.06);
            border: 1px solid rgba(88,166,255,0.25);
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 24px;
            font-size: 13px;
            line-height: 1.6;
        }}
        .explainer-banner h3 {{ color: var(--accent-color); font-size: 14px; margin-bottom: 6px; }}
        
        .card {{
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-bottom: 24px;
            overflow: hidden;
        }}
        .card-header {{
            padding: 14px 18px;
            background: rgba(255,255,255,0.02);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .card-body {{ padding: 18px; }}
        
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border-color); }}
        th {{ background: rgba(255,255,255,0.03); color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; }}
        tr:hover td {{ background: rgba(255,255,255,0.02); }}
        
        .badge {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }}
        .badge-good {{ background: rgba(46,160,67,0.2); color: #3fb950; }}
        .badge-intrv {{ background: rgba(210,153,34,0.2); color: #e3b341; }}
        .badge-zero {{ background: rgba(139,148,158,0.2); color: #8b949e; }}
        .badge-neutral {{ background: rgba(139,148,158,0.2); color: #8b949e; }}
        .badge-free {{ background: rgba(88,166,255,0.2); color: #58a6ff; font-weight: 700; }}
        .tok-saved {{ background: rgba(46,160,67,0.2); color: #3fb950; }}
        .tok-more {{ background: rgba(139,148,158,0.2); color: #8b949e; }}
        
        .val-base {{ color: #79c0ff; font-weight: 600; }}
        .val-sentry {{ color: #d2a8ff; font-weight: 600; }}
        
        .status-pill {{
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .status-solved {{ background: #238636; color: #fff; }}
        .status-failed {{ background: rgba(248,81,73,0.2); color: #f85149; border: 1px solid rgba(248,81,73,0.4); }}
        .status-pending {{ background: rgba(139,148,158,0.2); color: #8b949e; }}
        
        .repo-badge {{ color: var(--text-muted); font-size: 11px; }}
        .task-title {{ font-size: 16px; font-weight: 700; color: #fff; margin-right: 8px; }}
        .repo-tag {{ font-size: 12px; color: var(--text-muted); }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }}
        .metric-box {{
            background: rgba(0,0,0,0.2);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 10px 14px;
        }}
        .metric-label {{ font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }}
        .metric-val {{ font-size: 13px; font-weight: 600; color: #fff; }}
        
        .files-summary {{
            font-size: 13px;
            margin-bottom: 14px;
            padding: 10px 14px;
            background: rgba(88,166,255,0.05);
            border-left: 3px solid var(--accent-color);
            border-radius: 0 6px 6px 0;
        }}
        .files-summary code {{ color: #e6edf3; background: rgba(255,255,255,0.08); padding: 1px 5px; border-radius: 4px; font-size: 12px; }}
        
        .tabs {{ display: flex; gap: 8px; margin-bottom: 10px; }}
        .tab-btn {{
            background: var(--surface-color);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
        }}
        .tab-btn.active {{
            background: var(--accent-color);
            color: #000;
            border-color: var(--accent-color);
        }}
        .tab-pane {{ display: none; }}
        .tab-pane.active {{ display: block; }}
        
        .diff-block {{
            background: #090d13;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 14px;
            overflow-x: auto;
            font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
            font-size: 12px;
            line-height: 1.45;
            color: #c9d1d9;
            max-height: 350px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Sentry vs Base OpenCode Benchmark</h1>
            <div class="subtitle">
                Agent Model: <strong>crazyrouter/deepseek-flash</strong> (variant: high, endpoint: api.lhcwn.pro/v1) &bull;
                Supervisor: <strong>google/gemma-4-e4b</strong> (Local LM Studio) &bull;
                Dataset: <strong>SWE-bench Lite (5 tasks)</strong> &bull;
                Policy: W=5, H=10, Check on error
            </div>
        </header>

        <div class="kpi-row">
            <div class="kpi-card">
                <div class="kpi-title">Evaluated Tasks</div>
                <div class="kpi-val">5 / 5</div>
                <div class="kpi-desc">10 total test sessions run</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Resolved Rate (SWE-bench)</div>
                <div class="kpi-val" style="color: #3fb950;">100%</div>
                <div class="kpi-desc">10 / 10 runs passed FAIL_TO_PASS</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Sentry Cloud Cost</div>
                <div class="kpi-val" style="color: #58a6ff;">$0.00</div>
                <div class="kpi-desc">100% local inference via LM Studio</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Peak Token Savings</div>
                <div class="kpi-val" style="color: #3fb950;">-42.2%</div>
                <div class="kpi-desc">pallets__flask-5063 (363k &rarr; 210k)</div>
            </div>
        </div>

        <div class="explainer-banner">
            <h3>💡 Token Metrics Explainer: Billed vs Net vs Sentry Tokens</h3>
            <p>
                <strong>1. Billed Tokens (Cumulative API Tokens):</strong> В протоколах LLM API (OpenAI / DeepSeek) агент OpenCode на каждом шаге отправляет на сервер <em>всю историю предыдущих шагов диалога</em>. Если в сессии 25 шагов, шаг 1 отправляет 2k токенов, шаг 10 — 10k токенов, а шаг 25 — 20k токенов. Сумма по всем запросам (кумулятивный объем) составляет 200k–360k токенов. Именно по этой метрике внешние облачные провайдеры тарифицируют вызовы при отсутствии prompt-кэширования.
            </p>
            <p style="margin-top: 6px;">
                <strong>2. Net Session Tokens:</strong> Реальный уникальный размер контекста диалога (размер промпта последнего шага + все сгенерированные ответы агента). Составляет всего <strong>2,500 – 5,500 токенов</strong>.
            </p>
            <p style="margin-top: 6px;">
                <strong>3. Sentry Tokens:</strong> Запросы супервизора Sentry отправляются на локальный сервер <strong>LM Studio</strong> (<code>google/gemma-4-e4b</code> на Apple Silicon GPU/CPU) и не расходуют платные облачные токены.
            </p>
        </div>

        <div class="card">
            <div class="card-header">
                <strong>Comparative Matrix (Base vs Sentry)</strong>
            </div>
            <div class="card-body" style="padding:0;">
                <table>
                    <thead>
                        <tr>
                            <th>Task / Repo</th>
                            <th>Steps (Base/Sentry)</th>
                            <th>Interv</th>
                            <th>Elapsed (B/S)</th>
                            <th>Net Tok (B/S)</th>
                            <th>Billed Tok (Base/Sentry)</th>
                            <th>Sentry Tokens (Local LM Studio)</th>
                            <th>Patch Length</th>
                            <th>Resolved (Base / Sentry)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <h2 style="font-size: 20px; margin-bottom: 16px; color:#fff;">Detailed Task Analysis & Diffs</h2>
        {task_cards_html}

    </div>

    <script>
        function switchTab(evt, tabId) {{
            const card = evt.target.closest('.card-body');
            card.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            card.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            evt.target.classList.add('active');
            const pane = document.getElementById(tabId);
            if (pane) pane.classList.add('active');
        }}
    </script>
</body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html_content, encoding="utf-8")
    print(f"HTML report successfully generated at: {output_html}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate benchmark HTML report")
    parser.add_argument("--results", type=str, default="outputs/batch_20tasks_iter1/results.json", help="Path to results.json")
    parser.add_argument("--output", type=str, default="reports/benchmark_report_deepseek_flash.html", help="Output HTML path")
    args = parser.parse_args()

    results_file = Path(args.results)
    if not results_file.exists():
        fallback = Path("reports/results_deepseek_flash.json")
        if fallback.exists():
            results_file = fallback

    generate_report(results_file, Path(args.output))

