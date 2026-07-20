#!/usr/bin/env python3
"""
scan_repo.py — deterministic, lightweight repo summary. No LLM involved.

Produces a small JSON summary of a repo: a depth-limited file tree,
extension counts, presence of common manifest/config files, and a short
README excerpt. This is deliberately NOT the full repo contents — the
point is to give the eval-case-generation step just enough signal
without dumping a huge, noisy context at the model (which invites
hallucinated eval cases).

Usage:
    python scan_repo.py --repo workspace/repos/foo --out workspace/repos/foo/scan.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
MANIFEST_FILES = [
    "package.json", "pyproject.toml", "requirements.txt", "setup.py",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile",
    "Dockerfile", "docker-compose.yml", "Makefile", ".github/workflows",
]
README_NAMES = ["README.md", "README.rst", "README.txt", "README"]
MAX_DEPTH = 3
MAX_TREE_ENTRIES = 500
README_LINES = 40


def build_tree(root: Path, max_depth: int, max_entries: int):
    tree = []
    count = 0

    def walk(path: Path, depth: int):
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.name in IGNORE_DIRS or entry.name.startswith("."):
                if entry.name != ".github":
                    continue
            if count >= max_entries:
                return
            rel = str(entry.relative_to(root))
            tree.append(rel + ("/" if entry.is_dir() else ""))
            count += 1
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(root, 0)
    return tree


def extension_counts(root: Path) -> dict:
    counts = Counter()
    for path in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix:
            counts[path.suffix] += 1
    return dict(counts.most_common(20))


def find_manifests(root: Path) -> list:
    found = []
    for name in MANIFEST_FILES:
        if (root / name).exists():
            found.append(name)
    return found


def readme_excerpt(root: Path) -> str:
    for name in README_NAMES:
        candidate = root / name
        if candidate.exists():
            try:
                lines = candidate.read_text(errors="ignore").splitlines()
                return "\n".join(lines[:README_LINES])
            except Exception:
                return ""
    return ""


def scan(root: Path) -> dict:
    return {
        "repo_path": str(root),
        "file_tree": build_tree(root, MAX_DEPTH, MAX_TREE_ENTRIES),
        "extension_counts": extension_counts(root),
        "manifests_present": find_manifests(root),
        "readme_excerpt": readme_excerpt(root),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to a cloned repo")
    ap.add_argument("--out", required=True, help="Where to write scan.json")
    args = ap.parse_args()

    root = Path(args.repo)
    if not root.exists():
        raise SystemExit(f"repo path does not exist: {root}")

    summary = scan(root)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"Wrote scan summary: {out_path} ({len(summary['file_tree'])} entries)")


if __name__ == "__main__":
    main()
