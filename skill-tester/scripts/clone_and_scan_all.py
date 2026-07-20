#!/usr/bin/env python3
"""
clone_and_scan_all.py — runs Steps 2+3 (clone + scan) for every repo in
config/repos.json IN PARALLEL, deterministically, with no LLM involved.

Why this exists: agent-level subagent parallelism (multi-agent mode)
depends on the Copilot runtime/plan and isn't guaranteed. The clone and
scan steps don't need a model at all, so they can be parallelized safely
in plain Python regardless -- this alone captures most of the wall-clock
savings, since cloning is the slowest part of the pipeline and each repo
is fully independent (separate destination directory, separate scan
output, no shared mutable state).

Safety properties:
  - Each repo writes only to its own workspace/repos/<name>/ directory.
    Nothing is shared between workers, so there's no locking to get wrong.
  - Concurrency is capped (--max-workers, default 4) to avoid hammering
    GitHub with simultaneous clones and tripping secondary rate limits.
  - One repo failing (bad URL, network blip, missing ref) is caught and
    recorded -- it does not abort or corrupt the other workers' results.
  - Idempotent: a repo already cloned is skipped (matches clone_repos.py
    behavior) unless --force is passed.

Usage:
    python clone_and_scan_all.py --config config/repos.json --dest workspace/repos
    python clone_and_scan_all.py --config config/repos.json --dest workspace/repos --max-workers 6
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scan_repo import scan

DEFAULT_MAX_WORKERS = 4  # keep conservative by default -- see safety notes above


def repo_name_from_url(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_and_scan_one(entry: dict, dest_dir: Path, force: bool) -> dict:
    url = entry["url"]
    ref = entry.get("ref", "main")
    name = repo_name_from_url(url)
    target = dest_dir / name
    started = time.time()

    if target.exists() and not force:
        clone_status = "already_cloned"
    else:
        if target.exists():
            shutil.rmtree(target)
        cmd = ["git", "clone", "--depth", "1", "--branch", ref, url, str(target)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
            clone_status = "cloned"
        except subprocess.CalledProcessError as e:
            return {"name": name, "url": url, "status": "clone_error", "detail": e.stderr.strip(),
                    "elapsed_sec": round(time.time() - started, 1)}
        except subprocess.TimeoutExpired:
            return {"name": name, "url": url, "status": "clone_error", "detail": "clone timed out after 300s",
                    "elapsed_sec": round(time.time() - started, 1)}

    try:
        summary = scan(target)
        (target / "scan.json").write_text(json.dumps(summary, indent=2))
    except Exception as e:
        return {"name": name, "url": url, "status": "scan_error", "detail": str(e),
                "elapsed_sec": round(time.time() - started, 1)}

    return {
        "name": name, "url": url, "ref": ref, "status": clone_status,
        "path": str(target), "tree_entries": len(summary["file_tree"]),
        "elapsed_sec": round(time.time() - started, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to repos.json")
    ap.add_argument("--dest", required=True, help="Directory to clone repos into")
    ap.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
                     help=f"Max concurrent clone+scan workers (default {DEFAULT_MAX_WORKERS}, "
                          f"raise cautiously -- higher values risk GitHub rate limiting)")
    ap.add_argument("--force", action="store_true", help="Re-clone even if directory already exists")
    args = ap.parse_args()

    config_path = Path(args.config)
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)

    repos = json.loads(config_path.read_text())
    if not isinstance(repos, list) or not repos:
        print("repos.json must be a non-empty JSON array of {url, ref} objects", file=sys.stderr)
        sys.exit(1)

    print(f"Cloning+scanning {len(repos)} repo(s) with max {args.max_workers} concurrent workers...")
    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(clone_and_scan_one, entry, dest_dir, args.force): entry for entry in repos}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            ok = result["status"] in ("cloned", "already_cloned")
            marker = "OK" if ok else "FAIL"
            print(f"[{marker}] {result['name']}: {result['status']} ({result['elapsed_sec']}s)")

    total_elapsed = round(time.time() - start, 1)
    summary_path = dest_dir / "_clone_scan_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))

    failures = [r for r in results if r["status"] not in ("cloned", "already_cloned")]
    print(f"\nDone in {total_elapsed}s wall-clock ({len(repos)} repos, {args.max_workers} workers).")
    print(f"{len(results) - len(failures)} succeeded, {len(failures)} failed. See {summary_path}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
