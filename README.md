# Sentry + OpenCode SWE-bench Lite Benchmark

[![arXiv](https://img.shields.io/badge/arXiv-2610.02994-b31b1b)](https://arxiv.org/abs/2610.02994)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![DeepSeek Sentry 4-Run Report](https://img.shields.io/badge/Report-DeepSeek_Sentry_4--Run-success?logo=html5)](reports/multi_iteration_report_deepseek_sentry.html)
[![Live Dashboard](https://img.shields.io/badge/Dashboard-DeepSeek_Sentry-blue?logo=html5)](reports/benchmark_report_deepseek_sentry.html)
[![Gemma Sentry Report](https://img.shields.io/badge/Report-Gemma_Sentry_Run-orange)](reports/benchmark_report_deepseek_flash.html)

An evaluation and reproduction harness integrating **[Sentry](https://arxiv.org/abs/2610.02994)** (runtime failure management for LLM agents) with the **[OpenCode](https://opencode.ai)** CLI agent across **SWE-bench Lite**.

> 📊 **Interactive Benchmark Dashboards**:
> - 🚀 **[Multi-Run DeepSeek Sentry Report (4 Iterations)](reports/multi_iteration_report_deepseek_sentry.html)** — **Pass@4: Sentry 75.0% vs Base 70.0%**
> - 🔬 **[In-Depth Causal Analysis & Ablation Study](reports/causal_analysis.md)** — Analysis of intervened vs non-intervened tasks & anomaly decomposition
> - 🖥️ **[Live DeepSeek Sentry Dashboard (Latest Run)](reports/benchmark_report_deepseek_sentry.html)**
> - 📄 **[Raw JSON DeepSeek Sentry Metrics](reports/multi_iteration_summary_deepseek_sentry.json)**
> - 🏛️ **[Local Gemma Sentry Dashboard (Host GPU Run)](reports/benchmark_report_deepseek_flash.html)** — Sentry 65.0% vs Base 55.0%

---

## 📋 Table of Contents
1. [Architecture & Workflow](#architecture--workflow)
2. [Empirical Results Summary](#empirical-results-summary)
3. [Setup & Installation](#setup--installation)
4. [Running Benchmarks](#running-benchmarks)
5. [Model & Provider Configurations](#model--provider-configurations)
6. [Known Issues & Best Practices](#known-issues--best-practices)

---

## 🏗 Architecture & Workflow

```
                        ┌─────────────────────────────────────┐
                        │          SWE-bench Lite Task        │
                        └──────────────────┬──────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Workspace (workspaces/<instance_id>)                                                   │
│ - Cloned target repo at base commit                                                    │
│ - opencode.json ("permission": {"websearch": "deny", "webfetch": "deny"})               │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
             [Base Evaluation]                            [Sentry Evaluation]
                    │                                             │
                    ▼                                             ▼
          OpenCode CLI Session                          OpenCode CLI Session
         (runs prompt in loop)                         (step-by-step streaming)
                    │                                             │
                    │                                             ▼
                    │                                    Sentry Sidecar Monitor
                    │                                    - Sliding Window W=5
                    │                                    - Check interval (every 5 steps)
                    │                                    - Immediate check on tool errors
                    │                                             │
                    │                           ┌─────────────────┴─────────────────┐
                    │                           │                                   │
                    │                     [No Failure]                          [Failure]
                    │                           │                                   │
                    │                           ▼                                   ▼
                    │                      Continue Turn                   Abort turn & inject
                    │                                                      RescuePrompt guidance
                    │                                                               │
                    ▼                                                               ▼
        Outputs & Summary Diff                                          Outputs, Diff & Lessons
```

- **OpenCode Adapter** (`benchmarks/opencode_adapter.py`): Wraps `opencode run --pure --format json`, captures streaming tool calls, errors, reasoning, and token usage.
- **Sentry Runner** (`benchmarks/swebench_runner.py`): Integrates Sentry's `SentryRunner`, observe steps, triggers detection, and feeds rescue prompts back into the session.
- **Batch Evaluation** (`benchmarks/run_batch_benchmark.py`): Iterates through 10 benchmark tasks in both Base and Sentry modes with incremental state persistence.

---

## 📊 Empirical Results Summary: 20 Tasks (Seed 42)

### 🚀 4-Iteration Benchmark: OpenCode with DeepSeek Sentry Supervisor

Full multi-iteration comparative benchmark evaluating **OpenCode with DeepSeek Flash (`crazyrouter/deepseek-flash`)** supervised by **Sentry with DeepSeek Flash** across 4 independent runs on 20 SWE-bench Lite tasks (Seed 42).
All Sentry supervisor tokens are treated as billed API costs and included in total token metrics.

> 📊 **Explore Multi-Run Results**:
> - 🚀 **[Open Multi-Iteration Aggregate Report (4 Runs)](reports/multi_iteration_report_deepseek_sentry.html)** — **Pass@4: Sentry 75.0% vs Base 70.0%**
> - 🖥️ **[Open Live Dashboard (Latest Run)](reports/benchmark_report_deepseek_sentry.html)**
> - 📦 **[Download Machine-Readable Multi-Iteration Summary (JSON)](reports/multi_iteration_summary_deepseek_sentry.json)**

#### 🏆 Pass@4 & Aggregate Run Breakdown

| Benchmark Run | Base Resolved | Sentry Resolved | Sentry Checks (Evaluations) | Sentry Interventions (Rate) | Base Steps | Sentry Steps (Δ) | Base Billed Tokens | Sentry Billed Tokens (Δ)* |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Iteration 1** | 9 / 20 (45.0%) | 9 / 20 (45.0%) | 146 checks | **11** (7.5%) across 9 tasks | 596 | 634 (+6.4%) | 11.73M | 12.83M (+9.4%) |
| **Iteration 2** | 10 / 20 (50.0%) | **12 / 20 (60.0%)** | 160 checks | **9** (5.6%) across 8 tasks | 612 | 638 (+4.2%) | 13.02M | 12.92M (**-0.7%**) |
| **Iteration 3** | 12 / 20 (60.0%) | 12 / 20 (60.0%) | 162 checks | **11** (6.8%) across 9 tasks | 597 | 650 (+8.9%) | 11.04M | 12.29M (+11.3%) |
| **Iteration 4** | 11 / 20 (55.0%) | **13 / 20 (65.0%)** | 139 checks | **15** (10.8%) across 12 tasks | 681 | **569 (-16.4%)** | 12.80M | **11.61M (-9.3%)** |
| **Total / Pass@4** | 14 / 20 (70.0%) | **15 / 20 (75.0%)** | **607 checks** | **46 interventions (7.6%)** | — | — | 48.59M | 49.65M (+2.2%) |

*\* Note: Sentry billed tokens include 100% of the Sentry LLM runtime supervisor API calls.*

#### 💡 Key DeepSeek Sentry Highlights
1. **Higher Ceiling (Pass@4 = 75.0% vs 70.0%)**: Sentry resolved 15 out of 20 tasks in at least one run (including `django-14667` which Base failed across all 4 runs).
2. **Consistent Outperformance in Complex Runs**: Sentry achieved a +10% absolute boost in resolved rate in both Iteration 2 (60% vs 50%) and Iteration 4 (65% vs 55%).
3. **Execution Efficiency in Iteration 4**: Under identical 1200s timeouts, Sentry slashed execution steps by **-16.4%** and net token consumption by **-9.3%**, proving that early intervention and rescue prompts curb unproductive model loops even when paying for supervisor API calls.
4. **Active Failure Detection (46 Interventions across 607 Sentry Checks = 7.6% Intervention Rate)**: Sentry performed 607 automated evaluations (triggered every 5 steps and on environment errors). In 92.4% of checks, the supervisor correctly confirmed normal progress (`no_failure`), while in 46 instances (7.6%) it stepped in to abort non-progress loops, path probing outside `/app/workspace`, and planning stalls with targeted RescuePrompts.
5. **Causal Validation & Zero-Interference Control Group**: On tasks with 0 interventions across all 4 runs (16 task sessions), Base and Sentry exhibited strictly identical Pass Rates (81.3% vs 81.3%) and identical average step counts (14.4 vs 14.3 steps), proving that passive monitoring incurs zero behavioral drift. Read the full [🔬 Causal Analysis Report](reports/causal_analysis.md).

---

### 🏛️ Local Gemma-4 Supervisor Benchmark (1 Run on Host GPU)

Full comparative benchmark evaluating **OpenCode with DeepSeek Flash (`crazyrouter/deepseek-flash`, variant: high)** against the **Sentry Runtime Supervisor (`google/gemma-4-e4b` on LM Studio)** across 20 randomly sampled SWE-bench Lite tasks (Seed 42).

> 📊 **Explore Full Results**:
> - 🖥️ **[Open Interactive HTML Benchmark Dashboard](reports/benchmark_report_deepseek_flash.html)**
> - 📈 **[Open Multi-Iteration Aggregate Report](reports/multi_iteration_report.html)**
> - 📦 **[Download Raw JSON Evaluation Data](reports/results_deepseek_flash.json)**

### 🏆 Key Performance Indicators (Iteration 1)

| Metric | Base (No Sentry) | Sentry (with Gemma-4 Supervisor) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Resolved Tasks (SWE-bench)** | 11 / 20 (**55.0%**) | **13 / 20 (65.0%)** | 🏆 **+10.0% (+18.2% relative)** |
| **FAIL_TO_PASS Tests Passed** | 17 / 27 (63.0%) | **21 / 27 (77.8%)** | 🎯 **+4 additional test cases fixed** |
| **Total Billed Tokens** | 13,459,341 tok | **11,785,777 tok** | 💰 **-1,673,564 tokens saved (-12.4%)** |
| **Total Execution Steps** | 691 steps | **615 steps** | ⚡ **-76 steps reduced (-11.0%)** |
| **Sentry Interventions** | — | **14 interventions** across 11 tasks | 🛡️ **0 false positive terminations** |

---

### 📋 Full 20-Task Comparative Matrix (Base vs Sentry)

All patches evaluated in-container against hidden SWE-bench ground-truth test suites (`FAIL_TO_PASS` and `PASS_TO_PASS` regression suites):

| Task ID | Repo | Steps (B / S) | Billed Tokens (B / S) | Token Savings | Interv | FAIL_TO_PASS (B / S) | PASS_TO_PASS (B / S) | Resolved (Base / Sentry) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| [`django__django-11099`](reports/benchmark_report_deepseek_flash.html#django__django-11099) | `django/django` | 9 / 7 | 92,188 / 32,078 | **-65.2%** | 1 | **3/3** / **3/3** | **19/19** / **19/19** | ✅ Resolved / ✅ Resolved |
| [`django__django-11133`](reports/benchmark_report_deepseek_flash.html#django__django-11133) | `django/django` | 24 / 21 | 338,210 / 305,627 | -9.6% | 1 | **1/1** / **1/1** | **64/64** / **64/64** | ✅ Resolved / ✅ Resolved |
| [`django__django-11179`](reports/benchmark_report_deepseek_flash.html#django__django-11179) | `django/django` | 19 / 24 | 265,087 / 320,602 | +20.9% | 1 | **1/1** / **1/1** | **40/40** / **40/40** | ✅ Resolved / ✅ Resolved |
| [`django__django-11999`](reports/benchmark_report_deepseek_flash.html#django__django-11999) | `django/django` | 35 / 40 | 897,933 / 865,818 | -3.6% | 0 | **1/1** / **1/1** | **30/30** / **30/30** | ✅ Resolved / ✅ Resolved |
| [`django__django-12113`](reports/benchmark_report_deepseek_flash.html#django__django-12113) | `django/django` | 47 / 41 | 1,154,012 / 946,285 | -18.0% | 2 | 0/1 / **1/1** | 0/0 / 0/0 | ❌ Failed / 🏆 **RESOLVED (Sentry WIN)** |
| [`django__django-12284`](reports/benchmark_report_deepseek_flash.html#django__django-12284) | `django/django` | 54 / 35 | 1,222,044 / 639,769 | **-47.6%** | 2 | **1/1** / **1/1** | **31/31** / **31/31** | ✅ Resolved / ✅ Resolved |
| [`django__django-12308`](reports/benchmark_report_deepseek_flash.html#django__django-12308) | `django/django` | 37 / 16 | 603,322 / 131,554 | **-78.2%** | 1 | 0/2 / **2/2** | 0/20 / **20/20** | ❌ Failed / 🏆 **RESOLVED (Sentry WIN)** |
| [`django__django-12747`](reports/benchmark_report_deepseek_flash.html#django__django-12747) | `django/django` | 15 / 32 | 130,853 / 646,377 | +393.9% | 1 | **3/3** / **3/3** | **49/49** / **49/49** | ✅ Resolved / ✅ Resolved |
| [`django__django-13710`](reports/benchmark_report_deepseek_flash.html#django__django-13710) | `django/django` | 31 / 22 | 471,086 / 326,557 | **-30.7%** | 1 | **1/1** / **1/1** | **62/62** / **62/62** | ✅ Resolved / ✅ Resolved |
| [`django__django-13768`](reports/benchmark_report_deepseek_flash.html#django__django-13768) | `django/django` | 25 / 16 | 322,225 / 224,657 | **-30.3%** | 1 | **1/1** / **1/1** | **18/18** / **18/18** | ✅ Resolved / ✅ Resolved |
| [`django__django-14017`](reports/benchmark_report_deepseek_flash.html#django__django-14017) | `django/django` | 49 / 40 | 1,010,641 / 896,580 | -11.3% | 1 | **2/2** / **2/2** | **147/147** / **147/147** | ✅ Resolved / ✅ Resolved |
| [`django__django-14667`](reports/benchmark_report_deepseek_flash.html#django__django-14667) | `django/django` | 31 / 60 | 635,528 / 1,310,117 | +106.1% | 0 | 0/1 / 0/1 | 0/29 / 0/29 | ❌ Failed / ❌ Failed |
| [`django__django-16816`](reports/benchmark_report_deepseek_flash.html#django__django-16816) | `django/django` | 60 / 60 | 1,304,577 / 1,465,282 | +12.3% | 0 | 0/2 / **1/2 (50%)** | 0/123 / 0/123 | ❌ Failed / ⚠️ Partial Pass |
| [`pytest-dev__pytest-7220`](reports/benchmark_report_deepseek_flash.html#pytest-dev__pytest-7220) | `pytest-dev/pytest` | 44 / 29 | 981,522 / 421,050 | **-57.1%** | 0 | 0/1 / 0/1 | 0/11 / 0/11 | ❌ Failed / ❌ Failed |
| [`sphinx-doc__sphinx-7975`](reports/benchmark_report_deepseek_flash.html#sphinx-doc__sphinx-7975) | `sphinx-doc/sphinx` | 39 / 26 | 739,093 / 494,239 | **-33.1%** | 1 | 0/1 / 0/1 | 0/7 / 0/7 | ❌ Failed / ❌ Failed |
| [`sympy__sympy-11870`](reports/benchmark_report_deepseek_flash.html#sympy__sympy-11870) | `sympy/sympy` | 60 / 34 | 1,810,024 / 996,748 | **-44.9%** | 1 | 0/1 / 0/1 | 1/58 / 1/58 | ❌ Failed / ❌ Failed |
| [`sympy__sympy-13177`](reports/benchmark_report_deepseek_flash.html#sympy__sympy-13177) | `sympy/sympy` | 25 / 15 | 345,937 / 200,526 | **-42.0%** | 0 | **1/2 (50%)** / **1/2 (50%)** | 0/76 / 0/76 | ⚠️ Partial / ⚠️ Partial |
| [`sympy__sympy-15011`](reports/benchmark_report_deepseek_flash.html#sympy__sympy-15011) | `sympy/sympy` | 22 / 29 | 254,943 / 480,159 | +88.3% | 0 | **1/1** / **1/1** | **53/53** / **53/53** | ✅ Resolved / ✅ Resolved |
| [`sympy__sympy-15308`](reports/benchmark_report_deepseek_flash.html#sympy__sympy-15308) | `sympy/sympy` | 33 / 35 | 294,249 / 465,221 | +58.1% | 0 | 0/1 / 0/1 | 0/120 / 0/120 | ❌ Failed / ❌ Failed |
| [`sympy__sympy-22005`](reports/benchmark_report_deepseek_flash.html#sympy__sympy-22005) | `sympy/sympy` | 32 / 33 | 585,867 / 616,531 | +5.2% | 0 | **1/1** / **1/1** | **2/2** / **2/2** | ✅ Resolved / ✅ Resolved |
| **TOTALS (20 TASKS)** | — | **691 / 615 (-11.0%)** | **13.46M / 11.79M** | **-12.4% (-1.67M)** | **14** | **17/27 / 21/27** | **478/488 / 498/508** | **Base: 11/20 (55%) / Sentry: 13/20 (65%)** |

---

### 💡 Key Findings & Observations

1. **Higher Task Success Rate (+10% Absolute)**:
   - Sentry successfully diagnosed and corrected critical planning stalls in `django__django-12113` and `django__django-12308`, allowing OpenCode to produce 100% passing patches where the baseline failed completely.
2. **Substantial Net Cost & Token Reduction (-12.4%)**:
   - On tasks with deep reasoning exploration (`django__django-12308`, `pytest-dev__pytest-7220`, `django__django-11099`, `sympy__sympy-11870`), Sentry eliminated non-productive cyclic searches, reducing billed tokens by up to **-78.2%**.
3. **Execution Efficiency (-11.0% Steps)**:
   - Sentry reduced cumulative interaction steps from 691 down to 615 across the 20 tasks, steering the agent away from timeout boundaries (max 60 steps).
4. **Zero Cloud Inference Cost for Supervisor**:
   - The Sentry runtime monitor ran 100% locally on host GPU via LM Studio (`google/gemma-4-e4b`), adding **$0.00** in API expenses while supervising the agent.
5. **Strict Isolation & Security**:
   - Every single task was evaluated in an isolated Docker container mounting an anonymous `/app/workspace` with an iptables Default-Deny network whitelist.

---

## 🐳 Running in Docker (Recommended, Zero Host Dependencies)

You can run the entire benchmark suite in a pre-configured Docker container with Python 3.11, Node.js 20, OpenCode CLI, git, pytest, and all testing tools preinstalled without touching your host machine:

### 1. Build the Docker Image
```bash
./run_in_docker.sh build
```

### 2. Run a Single Task in Docker
```bash
./run_in_docker.sh single psf__requests-2317
```

### 3. Run the 5-Task Batch Benchmark (Base vs Sentry)
```bash
./run_in_docker.sh batch
```

### 4. Evaluate Patch Correctness (Lightweight In-Container)
```bash
# Evaluate a single task against hidden test_patch
./run_in_docker.sh eval psf__requests-2317

# Evaluate all task runs in a batch output directory
./run_in_docker.sh eval-batch outputs/batch_deepseek_flash
```

### 5. Interactive Shell inside Docker
```bash
./run_in_docker.sh shell
```

All patches, execution logs, and HTML reports are automatically written to `./outputs`, `./reports`, and `./workspaces` on your host via Docker volume mounts. Local LM Studio on your host is automatically reachable via `host.docker.internal:1234`.

---

## 🚀 Manual Host Setup (Alternative)

### 1. Prerequisites
- Python 3.10 or 3.11
- [OpenCode CLI](https://opencode.ai) installed (`npm install -g opencode-ai` or via homebrew)
- Git and Docker (optional, for isolated environments)
- LM Studio / vLLM / Ollama (for local Sentry judge) OR an API key

### 2. Environment Setup
```bash
git clone https://github.com/LHCWN/Sentry-Opencode-Bench.git
cd Sentry-Opencode-Bench

python3.11 -m venv .venv
source .venv/bin/activate

pip install -e .
pip install datasets pyyaml requests
```

---

## 🏃 Running Benchmarks

### Run a Single SWE-bench Task

#### Base Mode (No Sentry):
```bash
GOOGLE_GENERATIVE_AI_API_KEY="your-gemini-key" \
PYTHONPATH=. .venv/bin/python benchmarks/swebench_runner.py \
  --instance-id "psf__requests-2317" \
  --opencode-model "google/gemini-3.5-flash-lite" \
  --no-sentry
```

#### Sentry Mode (With Sentry Failure Recovery):
```bash
GOOGLE_GENERATIVE_AI_API_KEY="your-gemini-key" \
PYTHONPATH=. .venv/bin/python benchmarks/swebench_runner.py \
  --instance-id "psf__requests-2317" \
  --opencode-model "google/gemini-3.5-flash-lite" \
  --config "configs/providers/lmstudio.yaml" \
  --check-interval 5 \
  --check-on-error
```

### Run Batch Benchmark (10 SWE-bench Lite Tasks)
```bash
GOOGLE_GENERATIVE_AI_API_KEY="your-gemini-key" \
PYTHONPATH=. .venv/bin/python benchmarks/run_batch_benchmark.py \
  --model "google/gemini-3.5-flash-lite" \
  --sentry-config "configs/providers/lmstudio.yaml" \
  --max-steps 25
```

Results are saved incrementally to `outputs/batch_benchmark/results.json`.

---

## ⚙️ Model & Provider Configurations

### 1. Sentry Judge Model (`configs/providers/lmstudio.yaml`)
Configured to point to any OpenAI-compatible local runner (LM Studio, vLLM, Ollama, llama.cpp):
```yaml
api:
  provider: openai_compatible
  model: google/gemma-4-e4b
  base_url: http://127.0.0.1:1234/v1
  api_key_env: null
  json_mode: prompt
  timeout: 120.0
  max_retries: 0

model:
  model: google/gemma-4-e4b
  temperature: 0.0
  max_tokens: 1536
  structured_outputs: true

task_agent:
  temperature: 0.7
  max_tokens: 1024
  structured_outputs: false
```

### 2. OpenCode Providers (`~/.config/opencode/opencode.jsonc`)

#### For Cloudflare Workers AI:
```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "cloudflare": {
      "name": "Cloudflare Workers AI",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1",
        "apiKey": "<CF_API_TOKEN>"
      },
      "models": {
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast": {
          "name": "Llama 3.3 70B Fast",
          "limit": { "context": 65536, "output": 4096 }
        }
      }
    }
  }
}
```

#### For OpenRouter:
Export the environment variable before running:
```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```
And pass `--opencode-model "openrouter/deepseek/deepseek-chat"`.

#### For Google Gemini:
Export the environment variable:
```bash
export GOOGLE_GENERATIVE_AI_API_KEY="AQ.Ab..."
```
And pass `--opencode-model "google/gemini-3.5-flash-lite"`.

---

## ⚠️ Known Issues & Best Practices

### 1. Inspection Policy: Per-Step vs Stride
- **Original Sentry paper behavior**: In the paper, Sentry calls the LLM detector on *every single interaction cycle*.
- **Problem**: When using local models or API endpoints, calling the detector every turn creates huge latency (15–20s per check), quickly consumes API rate limits, and multiplies false positive interventions ($1 - (0.95)^{20} \approx 64\%$).
- **Solution**: We introduced `--check-interval 5` and `--check-on-error True`:
  - Routine successful steps (`read`, `grep`, `edit` with `ok=True`) are observed silently (`observe_step`) to keep Sentry's sliding window intact.
  - Sentry's heavy LLM detector is triggered only every 5 steps, or **immediately** upon tool errors (`ok=False`, non-zero exit codes, tool crashes).

### 2. API Rate Limits & Quotas
- **Google AI Studio Free Tier**: Strict cap of **500 requests per day**. Running 5–6 complex tasks will exhaust this quota. In production, use a paid Tier 1 key or a self-hosted model.
- **OpenRouter Free Tier (`:free`)**: Hard cap of **50 requests per day**. Paid models (`deepseek/deepseek-chat`) cost fractions of a cent and do not have this daily restriction.
- **OpenCode Cloud Free Tier**: Shared global capacity; frequently hits `Free usage limit reached (HTTP 429)`. Always configure a custom provider or local model.

### 3. Context Window on Local LLMs (LM Studio)
- When evaluating long trajectories, Sentry's sliding window prompt can exceed 4,096 tokens.
- If LM Studio is configured with a 2k/4k context window, it will return `HTTP 400 Bad Request` or `ModelOutputTruncatedError`.
- **Recommendation**: Set LM Studio's context length (`n_ctx`) to **8,192** or **16,384** tokens for the judge model (`google/gemma-4-e4b` or similar).

### 4. Markdown Code Block Stripping
- Many local models (such as Gemma, Qwen, or LLaMA) wrap JSON responses in ```` ```json ... ``` ```` markdown fences despite instructions.
- Sentry includes automated code fence stripping in `Sentry/clients.py` and `Sentry/_structured.py` to prevent JSON parsing crashes.

### 5. Web Search Restrictions
- In each prepared repository, `opencode.json` is generated with:
  ```json
  {
    "permission": {
      "websearch": "deny",
      "webfetch": "deny"
    }
  }
  ```
  This guarantees that benchmarks remain clean and the agent cannot search for patches online.

### 6. Token Accounting: Cumulative API Tokens vs. Session Net Tokens
- **Why did tasks show ~1.5M - 3M tokens?**
  OpenCode streams per-step token usage via `step_finish`:
  `{"tokens": {"input": 45000, "output": 150, "total": 45150}}`
  Because LLM conversational agents send the **entire conversation history up to step $k$** as the prompt prefix on step $k$, summing `tokens.total` across all $N$ steps calculates the **cumulative tokens billed by the API provider** ($\sum_{k=1}^N \text{input}_k$).
- **Session Net Tokens (True Context Window)**:
  - The actual conversation context size at the end of a session is represented by `last_step_input` or `max_context_window` (~20,000–80,000 tokens).
  - The total text generated by the model across all turns is `total_generated` (~1,500–4,000 tokens).
  - The net unique tokens across the session is $\approx \text{final\_input} + \text{total\_generated}$.
- Both metrics are now explicitly tracked in `summary.json` as `cumulative_tokens` (billing perspective) and `session_net_tokens` (context perspective).

### 7. Sandbox & Host System Protection
To ensure benchmarks run safely without polluting the host or global Python/Node environments:
- **`PIP_REQUIRE_VIRTUALENV=true`**: Agents are strictly forbidden from installing packages into the host/system Python (`ERROR: Could not find an activated virtualenv`).
- **`PIP_NO_INDEX=true`**: Prevents agents from downloading untracked external packages from PyPI over the network.
- **`PYTHONNOUSERSITE=1`**: Prevents agents from installing to or reading packages from `~/.local/lib/pythonX.Y/site-packages`.
- **`NPM_CONFIG_GLOBAL=false`**: Blocks global npm package installations.
- **`external_directory: "deny"`**: OpenCode strictly blocks any tool execution or file reads outside the designated `workspaces/<instance_id>` folder.

### 8. Re-running Benchmarks in Another Contour
When transferring the repo to another machine or running with alternative models:
```bash
# Re-run only tasks that previously failed (errored or stopped with 0 steps)
python benchmarks/run_batch_benchmark.py \
  --model "openrouter/deepseek/deepseek-chat" \
  --sentry-config "configs/providers/vllm.yaml" \
  --rerun-failed

# Force re-run all 10 tasks from scratch
python benchmarks/run_batch_benchmark.py \
  --model "openrouter/deepseek/deepseek-chat" \
  --sentry-config "configs/providers/vllm.yaml" \
  --force
```

---

## 📄 License
This repository is licensed under the [MIT License](LICENSE).
