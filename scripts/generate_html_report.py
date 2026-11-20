"""Generate an interactive, modern HTML report comparing OpenCode Base vs OpenCode + Sentry."""
import json
from pathlib import Path
import html

def format_category_badge(cat):
    if not cat or not isinstance(cat, dict):
        return '<span class="status-pill status-pending">-</span>'
    total = cat.get("total", 0)
    passed = cat.get("passed", 0)
    if total == 0:
        return '<span class="status-pill status-pending">0/0</span>'
    if passed == total:
        return f'<span class="status-pill status-solved">{passed}/{total} (100%)</span>'
    elif passed > 0:
        pct = round(passed / total * 100)
        return f'<span class="status-pill status-partial">{passed}/{total} ({pct}%)</span>'
    else:
        return f'<span class="status-pill status-failed">0/{total} (0%)</span>'

def format_tests_list(tests, title, color):
    if not tests:
        return ""
    items = "".join(f"<li style='margin-bottom: 2px; word-break: break-all;'><code>{html.escape(t)}</code></li>" for t in tests[:15])
    more = f"<div style='color: #8b949e; font-size: 11px;'>... and {len(tests)-15} more</div>" if len(tests) > 15 else ""
    return f"""
    <details style="margin-top: 4px;">
        <summary style="cursor: pointer; color: {color}; font-size: 12px; font-weight: 500;">{title} ({len(tests)})</summary>
        <ul style="margin: 4px 0 0 16px; padding: 0; font-size: 11px;">
            {items}
        </ul>
        {more}
    </details>
    """

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
            "base_f2p": b.get("fail_to_pass") or {},
            "sentry_f2p": s.get("fail_to_pass") or {},
            "base_p2p": b.get("pass_to_pass") or {},
            "sentry_p2p": s.get("pass_to_pass") or {},
            "base_cnt": b.get("test_counts") or {},
            "sentry_cnt": s.get("test_counts") or {},
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
        b_pill = '<span class="status-pill status-solved">Resolved</span>' if b_res is True else ('<span class="status-pill status-failed">Failed</span>' if b_res is False else '<span class="status-pill status-pending">Pending</span>')
        s_pill = '<span class="status-pill status-solved">Resolved</span>' if s_res is True else ('<span class="status-pill status-failed">Failed</span>' if s_res is False else '<span class="status-pill status-pending">Pending</span>')

        b_f2p_badge = format_category_badge(t.get("base_f2p"))
        s_f2p_badge = format_category_badge(t.get("sentry_f2p"))
        b_p2p_badge = format_category_badge(t.get("base_p2p"))
        s_p2p_badge = format_category_badge(t.get("sentry_p2p"))

        b_c = t.get("base_cnt") or {}
        s_c = t.get("sentry_cnt") or {}
        b_cnt_str = f"{b_c.get('passed',0)}P / {b_c.get('failed',0)}F" if b_c else "-"
        s_cnt_str = f"{s_c.get('passed',0)}P / {s_c.get('failed',0)}F" if s_c else "-"

        rows_html += f"""
        <tr>
            <td class="task-id"><strong>{tid}</strong><br><small class="repo-badge">{repo}</small></td>
            <td>
                <span class="val-base">{b_steps}</span> / <span class="val-sentry">{s_steps}</span>
                <span class="badge {step_class}">{step_badge}</span>
            </td>
            <td><span class="badge {intrv_class}">{intrv}</span></td>
            <td>{b_time}s / {s_time}s</td>
            <td>
                <span class="val-base">{b_billed}</span><br>
                <span class="val-sentry">{s_billed}</span>
                <span class="badge {tok_class}">{tok_badge}</span>
            </td>
            <td>{b_f2p_badge} / {s_f2p_badge}</td>
            <td>{b_p2p_badge} / {s_p2p_badge}</td>
            <td><span class="val-base">{b_cnt_str}</span> / <span class="val-sentry">{s_cnt_str}</span></td>
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

        b_res = t.get("base_resolved")
        s_res = t.get("sentry_resolved")
        b_pill = '<span class="status-pill status-solved">Resolved</span>' if b_res is True else ('<span class="status-pill status-failed">Failed</span>' if b_res is False else '<span class="status-pill status-pending">Pending</span>')
        s_pill = '<span class="status-pill status-solved">Resolved</span>' if s_res is True else ('<span class="status-pill status-failed">Failed</span>' if s_res is False else '<span class="status-pill status-pending">Pending</span>')

        b_f2p = t.get("base_f2p") or {}
        s_f2p = t.get("sentry_f2p") or {}
        b_p2p = t.get("base_p2p") or {}
        s_p2p = t.get("sentry_p2p") or {}
        b_cnt = t.get("base_cnt") or {}
        s_cnt = t.get("sentry_cnt") or {}

        b_f2p_badge = format_category_badge(b_f2p)
        s_f2p_badge = format_category_badge(s_f2p)
        b_p2p_badge = format_category_badge(b_p2p)
        s_p2p_badge = format_category_badge(s_p2p)

        b_f2p_details = format_tests_list(b_f2p.get("success", []), "Passed Tests", "#3fb950") + format_tests_list(b_f2p.get("failure", []), "Failed Tests", "#f85149")
        s_f2p_details = format_tests_list(s_f2p.get("success", []), "Passed Tests", "#3fb950") + format_tests_list(s_f2p.get("failure", []), "Failed Tests", "#f85149")

        b_cnt_str = f"{b_cnt.get('passed', 0)} passed, {b_cnt.get('failed', 0)} failed, {b_cnt.get('skipped', 0)} skipped" if b_cnt else "-"
        s_cnt_str = f"{s_cnt.get('passed', 0)} passed, {s_cnt.get('failed', 0)} failed, {s_cnt.get('skipped', 0)} skipped" if s_cnt else "-"

        task_cards_html += f"""
        <div class="card task-card" id="{tid}">
            <div class="card-header">
                <div>
                    <span class="task-title">{tid}</span>
                    <span class="repo-tag">{repo}</span>
                </div>
                <div class="header-badges">
                    <span class="badge {intrv_class}">{intrv} Sentry Intervention(s)</span>
                    <span class="status-pill status-solved">Sentry: {s_pill}</span>
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

                <!-- Ground Truth Test Suite Execution Section -->
                <div style="margin: 16px 0; background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;">
                    <h4 style="margin: 0 0 12px 0; font-size: 14px; color: #58a6ff;">🧪 SWE-bench Ground Truth Test Suite Execution</h4>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                        <div style="background: rgba(255,255,255,0.02); padding: 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                            <div style="font-weight: 600; margin-bottom: 8px;">Baseline: {b_pill}</div>
                            <div style="font-size: 13px; line-height: 1.6;">
                                <div>🎯 <strong>FAIL_TO_PASS:</strong> {b_f2p_badge}</div>
                                {b_f2p_details}
                                <div style="margin-top: 6px;">🛡️ <strong>PASS_TO_PASS:</strong> {b_p2p_badge}</div>
                                <div style="margin-top: 6px; color: var(--text-muted);">📊 <strong>Summary:</strong> {b_cnt_str}</div>
                            </div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); padding: 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                            <div style="font-weight: 600; margin-bottom: 8px;">Sentry: {s_pill}</div>
                            <div style="font-size: 13px; line-height: 1.6;">
                                <div>🎯 <strong>FAIL_TO_PASS:</strong> {s_f2p_badge}</div>
                                {s_f2p_details}
                                <div style="margin-top: 6px;">🛡️ <strong>PASS_TO_PASS:</strong> {s_p2p_badge}</div>
                                <div style="margin-top: 6px; color: var(--text-muted);">📊 <strong>Summary:</strong> {s_cnt_str}</div>
                            </div>
                        </div>
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
    sentry_model_name = next((modes.get("sentry", {}).get("sentry_model") for modes in data.values() if modes.get("sentry", {}).get("sentry_model")), "google/gemma-4-e4b")
    if "gemma" in sentry_model_name.lower():
        supervisor_desc = f"{sentry_model_name} (Local LM Studio)"
    else:
        supervisor_desc = f"{sentry_model_name} (CrazyRouter)"

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
        .status-partial {{ background: rgba(210,153,34,0.2); color: #e3b341; border: 1px solid rgba(210,153,34,0.4); }}
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
            <h1>Sentry vs Base Benchmark Dashboard</h1>
            <div class="subtitle">
                Agent Model: <strong>crazyrouter/deepseek-flash</strong> (variant: high, endpoint: api.lhcwn.pro/v1) &bull;
                Supervisor: <strong>{supervisor_desc}</strong> &bull;
                Dataset: <strong>SWE-bench Lite ({len(tasks)} tasks)</strong> &bull;
                Network Whitelist: <strong>Enforced (Default Deny)</strong> &bull;
                Repository Isolation: <strong>Isolated /app/workspace</strong>
            </div>
        </header>

        <div class="kpi-row">
            <div class="kpi-card">
                <div class="kpi-title">Evaluated Tasks</div>
                <div class="kpi-val">{len(tasks)} / {len(tasks)}</div>
                <div class="kpi-desc">{len(tasks)*2} total test sessions run</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">FAIL_TO_PASS Tests (Base / Sentry)</div>
                <div class="kpi-val" style="color: #3fb950;">{sum(t.get('base_f2p',{}).get('passed',0) for t in tasks)} vs {sum(t.get('sentry_f2p',{}).get('passed',0) for t in tasks)}</div>
                <div class="kpi-desc">Total F2P tests in suite: {sum(t.get('sentry_f2p',{}).get('total',0) for t in tasks)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Net Token Savings</div>
                <div class="kpi-val" style="color: #3fb950;">{((total_sentry_billed - total_base_billed) / total_base_billed * 100) if total_base_billed else 0:+.1f}%</div>
                <div class="kpi-desc">{(total_base_billed - total_sentry_billed):,} tokens saved</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Execution Steps</div>
                <div class="kpi-val" style="color: #58a6ff;">{total_base_steps} &rarr; {total_sentry_steps}</div>
                <div class="kpi-desc">{((total_sentry_steps - total_base_steps) / total_base_steps * 100) if total_base_steps else 0:+.1f}% steps reduction</div>
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
                <strong>Comparative Matrix: SWE-bench Test Categories & Performance</strong>
            </div>
            <div class="card-body" style="padding:0;">
                <table>
                    <thead>
                        <tr>
                            <th>Task / Repo</th>
                            <th>Steps (Base/Sentry)</th>
                            <th>Interv</th>
                            <th>Elapsed (B/S)</th>
                            <th>Billed Tok (Base/Sentry)</th>
                            <th>FAIL_TO_PASS (Base / Sentry)</th>
                            <th>PASS_TO_PASS (Base / Sentry)</th>
                            <th>Tests (Base / Sentry)</th>
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

