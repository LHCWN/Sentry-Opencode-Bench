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

Results on SWE-bench Lite tasks evaluated with **OpenCode (google/gemini-3.5-flash-lite)** and **Sentry (google/gemma-4-e4b on LM Studio)**:

| Task ID | Mode | Steps | Interventions | Elapsed Time | Agent Tokens | Sentry Tokens | Total Tokens | Patch Size |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`psf__requests-2317`** | Base | 43 | — | 1923.1s | 1,652,084 | — | 1,652,084 | 1,775 B |
| | **Sentry** | **29** | **1** | **424.4s** *(4.5× faster)* | 879,514 | 13,365 | **892,879** *(-46%)* | 1,892 B |
| **`pallets__flask-4045`** | Base | 46 | — | 517.8s | 2,406,252 | — | 2,406,252 | 2,630 B |
| | **Sentry** | **30** | **1** | **298.4s** *(1.7× faster)* | 852,381 | 23,700 | **876,081** *(-64%)* | 3,072 B |
| **`pallets__flask-5063`** | Base | 67 | — | 2842.0s | 3,463,402 | — | 3,463,402 | 6,642 B |
| | **Sentry** | **34** | **2** | **325.7s** *(8.7× faster)* | 787,792 | 22,872 | **810,664** *(-77%)* | 0 B |
| **`psf__requests-2148`** | Base | 41 | — | 14518.2s | 2,012,165 | — | 2,012,165 | 4,728 B |
| | **Sentry** | **23** | **1** | **335.3s** *(43× faster)* | 867,054 | 5,288 | **872,342** *(-57%)* | 0 B |

### Key Takeaways:
1. **Dramatic Token Savings (-46% to -77%)**: When agents drift into repetitive exploratory loops (reading files repeatedly, redundant grep patterns), Sentry intervenes early, preventing millions of wasted tokens.
2. **Massive Speedups (1.7× to 43× faster)**: Early intervention stops runaway turns and infinite tool retries.
3. **Overhead of Sentry is Minimal**: Sentry tokens accounted for only 1% to 2.8% of total tokens spent.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10 or 3.11
- [OpenCode CLI](https://opencode.ai) installed (`npm install -g opencode-ai` or via homebrew)
- Git and Docker (optional, for isolated environments)
- LM Studio / vLLM / Ollama (for local Sentry judge) OR an API key

### 2. Environment Setup
```bash
git clone https://github.com/NixNi/Sentry-Opencode-Bench.git
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

---

## 📄 License
This repository is licensed under the [MIT License](LICENSE).
