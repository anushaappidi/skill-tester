#!/usr/bin/env python3
"""
clone_repos.py — deterministic repo cloning, no LLM involved.

Reads a JSON config listing repos and shallow-clones each one into a
destination directory. Safe to re-run: existing clones are left alone
unless --force is passed.

Usage:
    python clone_repos.py --config config/repos.json --dest workspace/repos
    python clone_repos.py --config config/repos.json --dest workspace/repos --force
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def repo_name_from_url(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_one(url: str, ref: str, dest_dir: Path, force: bool) -> dict:
    name = repo_name_from_url(url)
    target = dest_dir / name

    if target.exists():
        if force:
            shutil.rmtree(target)
        else:
            return {"name": name, "url": url, "status": "already_cloned", "path": str(target)}

    cmd = [
        "git", "clone",
        "--depth", "1",
        "--branch", ref,
        url, str(target),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        return {"name": name, "url": url, "ref": ref, "status": "cloned", "path": str(target)}
    except subprocess.CalledProcessError as e:
        return {"name": name, "url": url, "ref": ref, "status": "error", "detail": e.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"name": name, "url": url, "ref": ref, "status": "error", "detail": "clone timed out after 300s"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to repos.json")
    ap.add_argument("--dest", required=True, help="Directory to clone repos into")
    ap.add_argument("--force", action="store_true", help="Re-clone even if directory already exists")
    args = ap.parse_args()

    config_path = Path(args.config)
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)

    repos = json.loads(config_path.read_text())
    if not isinstance(repos, list):
        print("repos.json must be a JSON array of {url, ref} objects", file=sys.stderr)
        sys.exit(1)

    results = []
    for entry in repos:
        url = entry["url"]
        ref = entry.get("ref", "main")
        result = clone_one(url, ref, dest_dir, args.force)
        results.append(result)
        status = result["status"]
        marker = "OK" if status in ("cloned", "already_cloned") else "FAIL"
        print(f"[{marker}] {result['name']}: {status}")

    summary_path = dest_dir / "_clone_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))

    failures = [r for r in results if r["status"] == "error"]
    if failures:
        print(f"\n{len(failures)} repo(s) failed to clone. See {summary_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
