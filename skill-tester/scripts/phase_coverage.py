#!/usr/bin/env python3
"""
phase_coverage.py — deterministic, no LLM involved.

Reads the expected phase list from skill_spec.json and the actual
phase_log.json written live during Step 5 for one repo, and computes a
per-phase coverage table: did each expected phase start, complete, get
skipped, or error -- and for phases with no log entry at all, "not
reached" (this is the exact case that was previously invisible: a skill
with 7 phases that silently stopped after phase 2 used to just look like
"the final output didn't match," not "phases 3-7 never ran").

Usage:
    python phase_coverage.py \
        --skill-spec workspace/skill_spec.json \
        --phase-log workspace/repos/<name>/phase_log.json \
        --out workspace/repos/<name>/phase_coverage.json
"""
import argparse
import json
from pathlib import Path

# last entry for a phase_id wins, since a phase can legitimately go
# started -> completed, and we want its final state
STATUS_RANK = {"error": 0, "skipped": 1, "started": 2, "completed": 3}

# Phrases that indicate the agent assumed something was unavailable
# instead of actually testing it -- e.g. "not confirmed available in
# test environment" without ever running `mvn --version`. This doesn't
# block anything (the log entry is still recorded honestly), it just
# makes an unverified skip visible in the report instead of blending in
# with a genuinely-tested blocker.
UNVERIFIED_SKIP_PHRASES = [
    "not confirmed", "might not be available", "may not be available",
    "assumed", "assuming", "not sure whether", "unclear whether",
    "possibly not available", "presumably", "likely not available",
]


def flag_unverified(detail: str) -> bool:
    lowered = detail.lower()
    return any(phrase in lowered for phrase in UNVERIFIED_SKIP_PHRASES)


def compute_coverage(expected_phases: list, log_entries: list) -> list:
    last_entry_by_phase = {}
    for entry in log_entries:
        last_entry_by_phase[entry["phase_id"]] = entry

    coverage = []
    for phase in expected_phases:
        pid = phase["phase_id"]
        entry = last_entry_by_phase.get(pid)
        if entry is None:
            coverage.append({
                "phase_id": pid, "name": phase["name"],
                "status": "not_reached", "detail": "no log entry -- the skill run never got here",
                "unverified_skip": False,
            })
        else:
            status = entry["status"]
            unverified = status in ("skipped", "error") and flag_unverified(entry["detail"])
            coverage.append({
                "phase_id": pid, "name": phase["name"],
                "status": status, "detail": entry["detail"],
                "unverified_skip": unverified,
            })
    return coverage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-spec", required=True, help="Path to skill_spec.json (has the expected phases list)")
    ap.add_argument("--phase-log", required=True, help="Path to this repo's phase_log.json")
    ap.add_argument("--out", required=True, help="Where to write phase_coverage.json")
    args = ap.parse_args()

    skill_spec = json.loads(Path(args.skill_spec).read_text())
    expected_phases = skill_spec.get("phases", [])

    log_path = Path(args.phase_log)
    log_entries = json.loads(log_path.read_text()) if log_path.exists() else []

    coverage = compute_coverage(expected_phases, log_entries)

    completed = sum(1 for c in coverage if c["status"] == "completed")
    total = len(coverage)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "total_phases": total,
        "completed_phases": completed,
        "phases": coverage,
    }, indent=2))

    print(f"Phase coverage: {completed}/{total} completed")
    for c in coverage:
        print(f"  [{c['status']:>11}] {c['phase_id']}: {c['name']}")
        if c["unverified_skip"]:
            print(f"      ⚠ WARNING: this looks like an unverified assumption, not a tested blocker: \"{c['detail']}\"")


if __name__ == "__main__":
    main()
