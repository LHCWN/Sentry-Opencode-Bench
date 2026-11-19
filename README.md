# Sentry + OpenCode SWE-bench Lite Benchmark

[![arXiv](https://img.shields.io/badge/arXiv-2610.02994-b31b1b)](https://arxiv.org/abs/2610.02994)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An evaluation and reproduction harness integrating **[Sentry](https://arxiv.org/abs/2610.02994)** (runtime failure management for LLM agents) with the **[OpenCode](https://opencode.ai)** CLI agent across **SWE-bench Lite**.

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

## 📊 Empirical Results Summary

Status and metrics across the 10 SWE-bench Lite candidate tasks evaluated using **OpenCode (`google/gemini-3.5-flash-lite`)** as the agent and **Sentry (`google/gemma-4-e4b` on LM Studio)** as the runtime monitor:

### 1. Overall Batch Status (10 Tasks)

| Task ID | Base Status | Base Patch | Sentry Status | Sentry Patch | Failure Cause (if any) |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`psf__requests-2317`** | Completed (43 steps) | **1,775 B** | Completed (29 steps) | **1,892 B** | — (Valid comparative run) |
| **`pallets__flask-4045`** | Completed (46 steps) | **2,630 B** | Completed (30 steps) | **3,072 B** | — (Valid comparative run) |
| **`pallets__flask-5063`** | Completed (67 steps) | **6,642 B** | Aborted early (34 steps) | **0 B** | Agent stopped after intervention without making code edits |
| **`psf__requests-2148`** | Completed (41 steps) | **4,728 B** | Aborted early (23 steps) | **0 B** | Agent stopped after intervention without making code edits |
| **`pallets__flask-4992`** | Completed (35 steps) | **2,081 B** | Crashed (step 0) | **0 B** | LM Studio `HTTP 400` (context window overflow) |
| **`psf__requests-1963`** | Completed (33 steps) | **2,598 B** | Crashed (step 0) | **0 B** | LM Studio `HTTP 400` (context window overflow) |
| **`psf__requests-2674`** | Not run (0 steps) | **0 B** | Not run (0 steps) | **0 B** | Gemini API free tier limit exhausted (500 req/day) |
| **`psf__requests-3362`** | Not run (0 steps) | **0 B** | Not run (0 steps) | **0 B** | Gemini API free tier limit exhausted (500 req/day) |
| **`psf__requests-863`** | Not run (0 steps) | **0 B** | Not run (0 steps) | **0 B** | Gemini API free tier limit exhausted (500 req/day) |
| **`pytest-dev__pytest-11143`** | Not run (0 steps) | **0 B** | Not run (0 steps) | **0 B** | Gemini API free tier limit exhausted (500 req/day) |

---

### 2. Verified Comparative Runs (Tasks with Real Patches)

Only 2 out of 10 tasks produced non-zero, valid patches in both Base and Sentry modes:

| Task ID | Mode | Steps | Interventions | Elapsed Time | Billed Tokens (API) | Patch Size |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **`psf__requests-2317`** | Base | 43 | — | 1923.1s | 1,652,084 | 1,775 B |
| | **Sentry** | **29** | **1** | **424.4s** | **892,879** | 1,892 B |
| **`pallets__flask-4045`** | Base | 46 | — | 517.8s | 2,406,252 | 2,630 B |
| | **Sentry** | **30** | **1** | **298.4s** | **876,081** | 3,072 B |

### Empirical Observations:
1. **On tasks where Sentry succeeded (`requests-2317`, `flask-4045`)**:
   - 1 targeted intervention helped guide the agent back to the core issue, avoiding redundant exploratory cycles.
   - Reduced step count by ~32–35% while preserving patch validity.
2. **On tasks where Sentry failed to produce a patch (`flask-5063`, `requests-2148`)**:
   - The agent misinterpreted Sentry's corrective guidance as a termination instruction and stopped before making file modifications (resulting in 0-byte patches).
   - This caused lower step counts, but represents a failure to solve the task rather than an optimization.
3. **Infrastructure Bottlenecks**:
   - 4 tasks could not be evaluated due to API quota exhaustion (Google AI Studio 500 req/day limit).
   - 2 tasks crashed due to local judge model context limits in LM Studio (`n_ctx` < 8k).

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
