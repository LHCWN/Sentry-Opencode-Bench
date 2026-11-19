#!/usr/bin/env python3
"""Pre-fetches git workspaces with shallow fetch (depth 50) for given tasks so that
the benchmark can run under total network isolation without requiring GitHub access.
"""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.swebench_runner import fetch_swebench_instance, prepare_repo_workspace

DEFAULT_20_TASKS = [
    "sympy__sympy-11870",
    "django__django-12308",
    "django__django-11099",
    "sympy__sympy-15308",
    "django__django-14667",
    "django__django-14017",
    "django__django-13768",
    "django__django-12747",
    "sympy__sympy-15011",
    "django__django-12284",
    "sympy__sympy-13177",
    "sympy__sympy-22005",
    "pytest-dev__pytest-7220",
    "django__django-11999",
    "sphinx-doc__sphinx-7975",
    "django__django-16816",
    "django__django-11179",
    "django__django-11133",
    "django__django-12113",
    "django__django-13710",
]

def main():
    parser = argparse.ArgumentParser(description="Pre-fetch git repositories for SWE-bench tasks")
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_20_TASKS, help="Task IDs to prefetch")
    parser.add_argument("--workspaces", type=Path, default=Path("workspaces"), help="Workspaces directory")
    parser.add_argument("--depth", type=int, default=50, help="Shallow fetch commit depth")
    args = parser.parse_args()

    args.workspaces.mkdir(parents=True, exist_ok=True)
    print(f"📦 Pre-fetching {len(args.tasks)} task repositories with depth={args.depth} into {args.workspaces}...")

    for idx, instance_id in enumerate(args.tasks, 1):
        print(f"[{idx}/{len(args.tasks)}] Pre-fetching {instance_id}...")
        try:
            instance = fetch_swebench_instance(instance_id)
            work_dir = prepare_repo_workspace(instance, args.workspaces, depth=args.depth)
            print(f"  ✅ {instance_id} ready at {work_dir}")
        except Exception as e:
            print(f"  ❌ Error prefetching {instance_id}: {e}")

    print("\n🎉 Pre-fetch completed! All workspaces are prepared on disk.")

if __name__ == "__main__":
    main()
