#!/usr/bin/env python3
"""
gate_check.py — deterministic gate between clone/scan and eval generation.

This exists because an agent can, in principle, ignore instructions and
generate eval cases for a repo that never actually cloned (producing a
report that shows passing evals against a repo it never touched -- this
happened in practice, which is why this script exists). Steps 4-6 in
SKILL.md must not run for any repo this script marks as ineligible.

It reads _clone_scan_summary.json (written by clone_and_scan_all.py) and,
for every repo that isn't actually cloned+scanned successfully, writes a
SKIPPED.json marker into that repo's directory. build_report.py treats
SKIPPED.json as authoritative and will report that repo as skipped even
if a cases.json was generated for it anyway -- so a misbehaving agent
run can't silently produce a misleading report.

Usage:
    python gate_check.py --dest workspace/repos
Prints:
    ELIGIBLE: repo-a, repo-c
    SKIPPED:  repo-b (clone_error: ...), repo-d (scan_error: ...)
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="workspace/repos directory (contains _clone_scan_summary.json)")
    args = ap.parse_args()

    dest_dir = Path(args.dest)
    summary_path = dest_dir / "_clone_scan_summary.json"
    if not summary_path.exists():
        print(f"ERROR: {summary_path} not found. Run clone_and_scan_all.py first.", file=sys.stderr)
        sys.exit(1)

    results = json.loads(summary_path.read_text())
    eligible, skipped = [], []

    for r in results:
        name = r["name"]
        repo_dir = dest_dir / name
        ok = r["status"] in ("cloned", "already_cloned") and (repo_dir / "scan.json").exists()

        if ok:
            eligible.append(name)
            skipped_marker = repo_dir / "SKIPPED.json"
            if skipped_marker.exists():
                skipped_marker.unlink()  # e.g. a retry succeeded after an earlier failed run
        else:
            reason = f"{r['status']}: {r.get('detail', 'scan.json missing')}"
            skipped.append((name, reason))
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "SKIPPED.json").write_text(json.dumps({"status": r["status"], "reason": reason}, indent=2))

    print(f"ELIGIBLE ({len(eligible)}): {', '.join(eligible) if eligible else '(none)'}")
    print(f"SKIPPED  ({len(skipped)}): {', '.join(f'{n} ({r})' for n, r in skipped) if skipped else '(none)'}")

    if not eligible:
        print("\nNo repos are eligible to proceed. Do not run Steps 4-6 for any repo.", file=sys.stderr)


if __name__ == "__main__":
    main()
