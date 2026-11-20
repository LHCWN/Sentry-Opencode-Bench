"""Lightweight in-container evaluator for SWE-bench Lite patches.

Evaluates generated patches by applying hidden test patches and executing the
task's FAIL_TO_PASS test suite inside the existing Docker container environment
without downloading external Docker images.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Optional

_DATASET_CACHE: dict[str, dict[str, Any]] = {}


def strip_test_hunks(patch_text: str) -> str:
    """Strip modifications to test files from model patch so test_patch applies cleanly.
    
    Standard SWE-bench evaluation only evaluates changes to source code files.
    """
    diff_files = re.split(r"(?=diff --git )", patch_text)
    clean_diffs = []
    for f_diff in diff_files:
        if not f_diff.strip():
            continue
        m = re.search(r"diff --git a/(.*?) b/", f_diff)
        if m:
            path_str = m.group(1).lower()
            if (
                path_str.startswith("tests/")
                or path_str.startswith("test/")
                or "/tests/" in path_str
                or "/test_" in path_str
                or path_str.startswith("test_")
            ):
                continue
        clean_diffs.append(f_diff)
    return "".join(clean_diffs)


def get_task_data(instance_id: str, split: str = "test") -> dict[str, Any]:
    """Retrieve task metadata from local eval_specs or SWE-bench Lite dataset."""
    global _DATASET_CACHE
    if not _DATASET_CACHE:
        eval_specs_file = Path("benchmarks/data/eval_specs.json")
        if not eval_specs_file.exists():
            eval_specs_file = Path("/app/benchmarks/data/eval_specs.json")
        if eval_specs_file.exists():
            with open(eval_specs_file, "r", encoding="utf-8") as f:
                _DATASET_CACHE = json.load(f)
        else:
            try:
                from datasets import load_dataset
                ds = load_dataset("princeton-nlp/SWE-bench_Lite", split=split)
                for item in ds:
                    _DATASET_CACHE[item["instance_id"]] = item
            except ImportError:
                raise RuntimeError("Evaluation specs not found and datasets package not available.")

    if instance_id not in _DATASET_CACHE:
        raise KeyError(f"Task '{instance_id}' not found in SWE-bench Lite ({split} split)")
    return _DATASET_CACHE[instance_id]


def parse_test_list(raw: Any) -> list[str]:
    """Parse a test list from JSON string or list."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except Exception:
            return [raw]
    return list(raw)


def parse_test_metrics(
    output: str, exit_code: int, fail_to_pass: list[str], pass_to_pass: list[str]
) -> dict[str, Any]:
    """Parse test runner output into structured category metrics (FAIL_TO_PASS, PASS_TO_PASS)."""
    failed_lines = []
    passed_lines = []

    for line in output.splitlines():
        line_clean = line.strip()
        if re.search(r"\b(FAILED|ERROR|FAIL)\b", line_clean) and not line_clean.startswith("="):
            failed_lines.append(line_clean)
        elif re.search(r"\b(PASSED|ok)\b", line_clean) and not line_clean.startswith("="):
            passed_lines.append(line_clean)

    p_match = re.search(r"\b(\d+)\s+passed\b", output)
    f_match = re.search(r"\b(\d+)\s+failed\b", output)
    e_match = re.search(r"\b(\d+)\s+error(?:s)?\b", output)
    s_match = re.search(r"\b(\d+)\s+skipped\b", output)

    django_ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
    django_fail = re.search(r"failures=(\d+)", output)
    django_err = re.search(r"errors=(\d+)", output)

    total_passed = int(p_match.group(1)) if p_match else 0
    total_failed = (int(f_match.group(1)) if f_match else 0) + (int(e_match.group(1)) if e_match else 0)
    total_skipped = int(s_match.group(1)) if s_match else 0

    if django_ran:
        ran = int(django_ran.group(1))
        df = int(django_fail.group(1)) if django_fail else 0
        de = int(django_err.group(1)) if django_err else 0
        total_failed = df + de
        total_passed = max(0, ran - total_failed)
    elif not p_match and not f_match and exit_code == 0 and len(passed_lines) > 0:
        total_passed = len(passed_lines)

    def extract_token(test_name: str) -> str:
        t = test_name.split("::")[-1]
        m = re.match(r"^(.*?)\s*\(", t)
        if m:
            t = m.group(1)
        m2 = re.match(r"^(.*?)\[", t)
        if m2:
            t = m2.group(1)
        return t.strip()

    def check_test(t_str: str) -> bool:
        tok = extract_token(t_str)
        for fl in failed_lines:
            if tok in fl:
                return False
        if exit_code == 0:
            return True
        for pl in passed_lines:
            if tok in pl:
                return True
        if total_failed > 0 or exit_code != 0:
            return False
        return True

    f2p_succ = [t for t in fail_to_pass if check_test(t)]
    f2p_fail = [t for t in fail_to_pass if t not in f2p_succ]

    p2p_succ = [t for t in pass_to_pass if check_test(t)]
    p2p_fail = [t for t in pass_to_pass if t not in p2p_succ]

    resolved = (len(f2p_fail) == 0 and len(p2p_fail) == 0 and exit_code == 0) if fail_to_pass else (exit_code == 0)

    return {
        "resolved": resolved,
        "fail_to_pass": {
            "total": len(fail_to_pass),
            "passed": len(f2p_succ),
            "failed": len(f2p_fail),
            "success": f2p_succ,
            "failure": f2p_fail,
        },
        "pass_to_pass": {
            "total": len(pass_to_pass),
            "passed": len(p2p_succ),
            "failed": len(p2p_fail),
            "success": p2p_succ,
            "failure": p2p_fail,
        },
        "test_counts": {
            "total": total_passed + total_failed + total_skipped,
            "passed": total_passed,
            "failed": total_failed,
            "skipped": total_skipped,
        },
    }



def evaluate_patch(
    instance_id: str,
    patch_content: Optional[str] = None,
    patch_file: Optional[Path | str] = None,
    workspace_dir: Optional[Path | str] = None,
    timeout: int = 180,
    reset_to_base: bool = False,
) -> dict[str, Any]:
    """Evaluate a generated patch against the ground truth test suite.

    Args:
        instance_id: SWE-bench task identifier (e.g., 'psf__requests-2317')
        patch_content: Diff string to evaluate. If None, read from patch_file or existing workspace.
        patch_file: Path to model_patch.diff.
        workspace_dir: Path to repository workspace. Defaults to 'workspaces/{instance_id}'.
        timeout: Maximum seconds to wait for pytest execution.
        reset_to_base: Whether to hard reset workspace to base_commit before applying patch.

    Returns:
        Structured evaluation result dict.
    """
    task = get_task_data(instance_id)
    base_commit = task["base_commit"]
    test_patch = task.get("test_patch", "")
    fail_to_pass = parse_test_list(task.get("FAIL_TO_PASS") or task.get("fail_to_pass", []))
    pass_to_pass = parse_test_list(task.get("PASS_TO_PASS") or task.get("pass_to_pass", []))


    if workspace_dir is None:
        workspace = Path("workspaces") / instance_id
    else:
        workspace = Path(workspace_dir)

    if not workspace.is_dir():
        return {
            "instance_id": instance_id,
            "resolved": False,
            "patch_applied": False,
            "test_patch_applied": False,
            "fail_to_pass_count": len(fail_to_pass),
            "fail_to_pass_tests": fail_to_pass,
            "error": f"Workspace directory '{workspace}' does not exist",
            "exit_code": -1,
            "duration_seconds": 0.0,
            "pytest_output": "",
        }

    # Resolve patch content if specified
    if patch_content is None and patch_file is not None:
        p_path = Path(patch_file)
        if p_path.is_file():
            patch_content = p_path.read_text(encoding="utf-8")

    # If reset_to_base requested, always ensure clean checkout of base_commit
    if reset_to_base:
        index_lock = workspace / ".git" / "index.lock"
        if index_lock.exists():
            try:
                index_lock.unlink()
            except Exception:
                pass
        subprocess.run(["git", "-C", str(workspace), "reset", "--hard", "HEAD"], check=False, capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "-f", base_commit], check=False, capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "clean", "-fdx"], check=False, capture_output=True)

    if patch_content is not None:
        # Strip test files from model patch so hidden test_patch doesn't conflict
        clean_model_patch = strip_test_hunks(patch_content)

        if clean_model_patch.strip():
            apply_res = subprocess.run(
                ["git", "-C", str(workspace), "apply", "--whitespace=nowarn"],
                input=clean_model_patch.encode("utf-8"),
                capture_output=True,
            )
            if apply_res.returncode != 0:
                return {
                    "instance_id": instance_id,
                    "resolved": False,
                    "patch_applied": False,
                    "test_patch_applied": False,
                    "fail_to_pass_count": len(fail_to_pass),
                    "fail_to_pass_tests": fail_to_pass,
                    "error": f"Failed to apply model patch: {apply_res.stderr.decode('utf-8')}",
                    "exit_code": apply_res.returncode,
                    "duration_seconds": 0.0,
                    "pytest_output": "",
                }

    # Apply test_patch
    test_patch_applied = False
    if test_patch.strip():
        apply_test_res = subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn"],
            input=test_patch.encode("utf-8"),
            capture_output=True,
        )
        if apply_test_res.returncode != 0:
            apply_test_res = subprocess.run(
                ["git", "-C", str(workspace), "apply", "--3way", "--whitespace=nowarn"],
                input=test_patch.encode("utf-8"),
                capture_output=True,
            )
        test_patch_applied = (apply_test_res.returncode == 0)
        if not test_patch_applied:
            return {
                "instance_id": instance_id,
                "resolved": False,
                "patch_applied": True,
                "test_patch_applied": False,
                "fail_to_pass_count": len(fail_to_pass),
                "fail_to_pass_tests": fail_to_pass,
                "error": f"Failed to apply test patch: {apply_test_res.stderr.decode('utf-8')}",
                "exit_code": apply_test_res.returncode,
                "duration_seconds": 0.0,
                "pytest_output": "",
            }

    start_time = time.time()
    pytest_output = ""
    exit_code = -1

    try:
        # Prepare python runner with compatibility shims for older Python 2/3 codebases
        shimmed_runner = (
            "import sys, os\n"
            "if os.path.isdir('src'):\n"
            "    sys.path.insert(0, os.path.abspath('src'))\n"
            "sys.path.insert(0, os.path.abspath('.'))\n"
            "import urllib.parse\n"
            "try:\n"
            "    import werkzeug.urls\n"
            "    if not hasattr(werkzeug.urls, 'url_quote'):\n"
            "        werkzeug.urls.url_quote = urllib.parse.quote\n"
            "    if not hasattr(werkzeug.urls, 'url_unquote'):\n"
            "        werkzeug.urls.url_unquote = urllib.parse.unquote\n"
            "except Exception:\n"
            "    pass\n"
            "import collections, collections.abc\n"
            "for name in ['Mapping', 'MutableMapping', 'Sequence', 'Iterable', 'Callable', 'Container', 'Hashable']:\n"
            "    if not hasattr(collections, name) and hasattr(collections.abc, name):\n"
            "        setattr(collections, name, getattr(collections.abc, name))\n"
            "try:\n"
            "    import _pytest.monkeypatch\n"
            "    if hasattr(_pytest.monkeypatch, 'NOTSET') and not hasattr(_pytest.monkeypatch, 'notset'):\n"
            "        _pytest.monkeypatch.notset = _pytest.monkeypatch.NOTSET\n"
            "except Exception:\n"
            "    pass\n"
            "import pytest\n"
            "args = sys.argv[1:]\n"
            "sys.exit(pytest.main(args))\n"
        )

        repo = task.get("repo", "")
        test_files = [f for f in re.findall(r"diff --git a/(.*?) b/", test_patch) if f.endswith(".py")]
        if repo.startswith("django/"):
            converted_tests = []
            for t in fail_to_pass:
                m = re.match(r"^(.*?)\s*\((.*?)\)$", t.strip())
                if m:
                    fn = m.group(1).strip()
                    cls = m.group(2).strip()
                    if cls.endswith("." + fn):
                        converted_tests.append(cls)
                    else:
                        converted_tests.append(f"{cls}.{fn}")
                else:
                    converted_tests.append(t)
            runtests_script = workspace / "tests" / "runtests.py"
            if runtests_script.exists():
                cmd = [sys.executable, "tests/runtests.py", "--settings=test_sqlite", "-v", "2"] + converted_tests
            else:
                cmd = [sys.executable, "-c", shimmed_runner, "-v"] + test_files + ["-k", " or ".join([t.split(" ")[0] for t in fail_to_pass])]
        elif repo.startswith("sympy/"):
            cmd = [sys.executable, "-c", shimmed_runner, "-v"] + test_files + (["-k", " or ".join(fail_to_pass)] if fail_to_pass else [])
        else:
            test_args = ["-v"] + test_files + (["-k", " or ".join(fail_to_pass)] if fail_to_pass else [])
            cmd = [sys.executable, "-c", shimmed_runner] + test_args

        env = os.environ.copy()
        env["PYTHONPATH"] = f".:{env.get('PYTHONPATH', '')}"
        env["PYTHONWARNINGS"] = "ignore::DeprecationWarning"

        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = proc.returncode
        pytest_output = proc.stdout + "\n" + proc.stderr

    except subprocess.TimeoutExpired:
        pytest_output = f"Pytest execution timed out after {timeout} seconds"
        exit_code = 124
    except Exception as e:
        pytest_output = f"Execution error: {e}"
        exit_code = 1
    finally:
        if test_patch.strip() and test_patch_applied:
            rev_res = subprocess.run(
                ["git", "-C", str(workspace), "apply", "-R", "--whitespace=nowarn"],
                input=test_patch.encode("utf-8"),
                capture_output=True,
            )
            if rev_res.returncode != 0:
                diff_stat = subprocess.run(
                    ["git", "-C", str(workspace), "diff", "--name-only"],
                    capture_output=True,
                    text=True,
                )
                for line in diff_stat.stdout.splitlines():
                    if line.startswith("tests/") or line.startswith("test_") or "test" in line:
                        subprocess.run(["git", "-C", str(workspace), "checkout", "--", line], check=False)

    duration = time.time() - start_time
    metrics = parse_test_metrics(pytest_output, exit_code, fail_to_pass, pass_to_pass)

    return {
        "instance_id": instance_id,
        "resolved": metrics["resolved"],
        "patch_applied": True,
        "test_patch_applied": test_patch_applied,
        "fail_to_pass": metrics["fail_to_pass"],
        "pass_to_pass": metrics["pass_to_pass"],
        "test_counts": metrics["test_counts"],
        "fail_to_pass_count": len(fail_to_pass),
        "fail_to_pass_tests": fail_to_pass,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 2),
        "pytest_output": pytest_output[-4000:],
    }


def evaluate_summary_file(summary_path: Path | str, reset_to_base: bool = True) -> dict[str, Any]:
    """Evaluate a single task run from its summary.json."""
    sum_file = Path(summary_path)
    if not sum_file.is_file():
        raise FileNotFoundError(f"Summary file not found: {sum_file}")

    data = json.loads(sum_file.read_text(encoding="utf-8"))
    instance_id = data.get("instance_id")
    if not instance_id:
        raise ValueError(f"No instance_id found in {sum_file}")

    patch_file = sum_file.parent / "model_patch.diff"
    patch_content = patch_file.read_text(encoding="utf-8") if patch_file.is_file() else None

    workspace_dir = Path("workspaces") / instance_id
    if not workspace_dir.exists():
        workspace_dir = Path("/app/workspaces") / instance_id
    if not workspace_dir.exists():
        workspace_dir = Path("/app/workspace")

    eval_result = evaluate_patch(
        instance_id=instance_id,
        patch_content=patch_content,
        patch_file=patch_file if patch_file.is_file() else None,
        workspace_dir=workspace_dir,
        reset_to_base=reset_to_base,
    )

    data["evaluation"] = eval_result
    data["resolved"] = eval_result["resolved"]
    data["fail_to_pass"] = eval_result.get("fail_to_pass")
    data["pass_to_pass"] = eval_result.get("pass_to_pass")
    data["test_counts"] = eval_result.get("test_counts")
    sum_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return eval_result



def evaluate_batch_dir(batch_dir: Path | str) -> list[dict[str, Any]]:
    """Scan directory recursively for summary.json files and evaluate all runs."""
    root = Path(batch_dir)
    results = []
    summary_files = sorted(root.glob("**/summary.json"))

    print(f"🔍 Found {len(summary_files)} summary files in {root}")
    for s_file in summary_files:
        try:
            print(f"Evaluating {s_file.parent.name}...")
            res = evaluate_summary_file(s_file, reset_to_base=True)
            status_emoji = "✅ RESOLVED" if res.get("resolved") else "❌ FAILED"
            f2p = res.get("fail_to_pass") or {}
            p2p = res.get("pass_to_pass") or {}
            counts = res.get("test_counts") or {}
            dur = res.get("duration_seconds", 0.0)
            f2p_str = f"F2P: {f2p.get('passed',0)}/{f2p.get('total',0)}"
            p2p_str = f"P2P: {p2p.get('passed',0)}/{p2p.get('total',0)}"
            print(f"  -> {status_emoji} | {f2p_str} | {p2p_str} | ({counts.get('passed',0)} pass, {counts.get('failed',0)} fail) in {dur}s")
            results.append(res)
        except Exception as e:
            print(f"  -> ⚠️ Error evaluating {s_file}: {e}")
            results.append({"summary_file": str(s_file), "resolved": False, "error": str(e)})

    return results



def main() -> None:
    parser = argparse.ArgumentParser(description="Lightweight In-Container Evaluator for SWE-bench Lite")
    parser.add_argument("--instance-id", type=str, help="SWE-bench instance ID to evaluate")
    parser.add_argument("--patch-file", type=str, help="Path to model_patch.diff")
    parser.add_argument("--workspace-dir", type=str, help="Path to task repository workspace")
    parser.add_argument("--summary-file", type=str, help="Path to task summary.json to evaluate and update")
    parser.add_argument("--batch-dir", type=str, help="Directory containing multiple task runs to evaluate")
    parser.add_argument("--reset-to-base", action="store_true", help="Hard reset workspace to base commit before evaluation")
    parser.add_argument("--json", action="store_true", help="Output raw JSON result")

    args = parser.parse_args()

    if args.batch_dir:
        batch_results = evaluate_batch_dir(args.batch_dir)
        resolved_count = sum(1 for r in batch_results if r.get("resolved"))
        print(f"\n📊 Batch Evaluation Complete: {resolved_count}/{len(batch_results)} resolved.")
        if args.json:
            print(json.dumps(batch_results, indent=2, ensure_ascii=False))
        return

    if args.summary_file:
        res = evaluate_summary_file(args.summary_file, reset_to_base=args.reset_to_base)
        status_emoji = "✅ RESOLVED" if res["resolved"] else "❌ FAILED"
        tests_cnt = res.get("fail_to_pass_count", 0)
        dur = res.get("duration_seconds", 0.0)
        print(f"\n{status_emoji}: {res['instance_id']} (tests: {tests_cnt}, time: {dur}s)")
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.instance_id:
        res = evaluate_patch(
            instance_id=args.instance_id,
            patch_file=args.patch_file,
            workspace_dir=args.workspace_dir,
            reset_to_base=args.reset_to_base,
        )
        status_emoji = "✅ RESOLVED" if res["resolved"] else "❌ FAILED"
        tests_cnt = res.get("fail_to_pass_count", 0)
        dur = res.get("duration_seconds", 0.0)
        print(f"\n{status_emoji}: {args.instance_id} (tests: {tests_cnt}, time: {dur}s)")
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res["resolved"] else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
