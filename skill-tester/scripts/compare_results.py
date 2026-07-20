#!/usr/bin/env python3
"""
compare_results.py — deterministic grading, no LLM involved.

Grades every case in cases.json whose check_type is "deterministic"
against the skill's actual output (from the single, shared Step 5 skill
run for this repo -- see SKILL.md). Writes result.json next to each
case's own directory (used for grading bookkeeping, not for the skill's
output itself). Semantic cases are left untouched — those are graded by
a separate, scoped LLM call (see SKILL.md Step 6).

Each check's "root" decides where its "target" path is resolved:
    "skill_run" (default) -- against the skill's shared output directory
    "case"                -- against this case's own directory (for a
                             verification artifact the grading step
                             itself produces, e.g. a test-run exit code)

Supported check types:
    file_exists      -- {"target": "<relative path>", "root": "skill_run"|"case"}
    regex_match       -- {"target": "<relative path>", "pattern": "<regex>", "root": ...}
    exit_code         -- {"target": "exit_code.txt", "expected_exit_code": 0, "root": "case"}
    line_count_min    -- {"target": "<relative path>", "min_lines": 5, "root": ...}

Usage:
    python compare_results.py --case workspace/repos/foo/cases.json \
        --skill-run-dir workspace/repos/foo/skill_run \
        --case-dir workspace/repos/foo/cases \
        --input-substitutions workspace/repos/foo/input_substitutions.json
"""
import argparse
import json
import re
from pathlib import Path

import jsonschema
from schemas import RESULT_SCHEMA


def resolve_root(check: dict, skill_run_dir: Path, case_dir: Path) -> Path:
    default_root = "case" if check["type"] == "exit_code" else "skill_run"
    return case_dir if check.get("root", default_root) == "case" else skill_run_dir


def run_check(check: dict, skill_run_dir: Path, case_dir: Path) -> tuple[bool, str]:
    check_type = check["type"]
    root = resolve_root(check, skill_run_dir, case_dir)

    if check_type == "file_exists":
        target = root / check["target"]
        exists = target.exists()
        return exists, f"expected '{check['target']}' to exist under {root.name}/: {'found' if exists else 'missing'}"

    if check_type == "regex_match":
        target = root / check.get("target", "actual.txt")
        if not target.exists():
            return False, f"'{target.name}' not found under {root.name}/"
        content = target.read_text(errors="ignore")
        pattern = check["pattern"]
        matched = re.search(pattern, content) is not None
        return matched, f"pattern '{pattern}' {'matched' if matched else 'did not match'} in {root.name}/{target.name}"

    if check_type == "exit_code":
        target = root / check.get("target", "exit_code.txt")
        if not target.exists():
            return False, f"'{target.name}' not found under {root.name}/; cannot check exit code"
        try:
            actual_code = int(target.read_text().strip())
        except ValueError:
            return False, f"'{target.name}' did not contain an integer exit code"
        expected = check["expected_exit_code"]
        return actual_code == expected, f"expected exit code {expected}, got {actual_code}"

    if check_type == "line_count_min":
        target = root / check.get("target", "actual.txt")
        if not target.exists():
            return False, f"'{target.name}' not found under {root.name}/"
        line_count = len(target.read_text(errors="ignore").splitlines())
        min_lines = check["min_lines"]
        return line_count >= min_lines, f"expected >= {min_lines} lines, got {line_count}"

    return False, f"unknown check type: {check_type}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="Path to cases.json for one repo")
    ap.add_argument("--skill-run-dir", required=True, help="Shared directory the skill's actual output lives in")
    ap.add_argument("--case-dir", required=True, help="Directory containing <case_id>/ grading bookkeeping")
    ap.add_argument("--input-substitutions", default=None,
                     help="Path to the repo's shared input_substitutions.json from Step 5 (optional)")
    args = ap.parse_args()

    cases = json.loads(Path(args.case).read_text())
    skill_run_dir = Path(args.skill_run_dir)
    case_root = Path(args.case_dir)

    shared_subs = []
    if args.input_substitutions:
        subs_path = Path(args.input_substitutions)
        if subs_path.exists():
            try:
                shared_subs = json.loads(subs_path.read_text())
            except json.JSONDecodeError:
                pass  # malformed substitutions log shouldn't block grading

    graded, skipped = 0, 0
    for case in cases:
        if case.get("check_type") != "deterministic":
            skipped += 1
            continue

        case_dir = case_root / case["case_id"]
        check = case.get("check")
        if not check:
            result = {
                "case_id": case["case_id"], "pass": False,
                "detail": "check_type=deterministic but no 'check' object provided",
                "graded_by": "error",
            }
        else:
            passed, detail = run_check(check, skill_run_dir, case_dir)
            result = {"case_id": case["case_id"], "pass": passed, "detail": detail, "graded_by": "script"}

        if shared_subs:
            result["input_substitutions"] = shared_subs

        jsonschema.validate(instance=result, schema=RESULT_SCHEMA)
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "result.json").write_text(json.dumps(result, indent=2))
        graded += 1
        print(f"[{'PASS' if result['pass'] else 'FAIL'}] {case['case_id']}: {result['detail']}")

    print(f"\nGraded {graded} deterministic case(s), skipped {skipped} semantic case(s) (grade those via LLM separately).")


if __name__ == "__main__":
    main()
