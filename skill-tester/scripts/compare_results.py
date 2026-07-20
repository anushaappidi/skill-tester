#!/usr/bin/env python3
"""
compare_results.py — deterministic grading, no LLM involved.

Grades every case in cases.json whose check_type is "deterministic"
against the actual output the agent produced for it. Writes result.json
next to each case's actual output. Semantic cases are left untouched —
those are graded by a separate, scoped LLM call (see SKILL.md Step 6).

Supported check types:
    file_exists      -- {"target": "<relative path under the case dir>"}
    regex_match       -- {"target": "actual.txt", "pattern": "<regex>"}
    exit_code         -- {"target": "exit_code.txt", "expected_exit_code": 0}
    line_count_min    -- {"target": "actual.txt", "min_lines": 5}

Usage:
    python compare_results.py --case workspace/repos/foo/cases.json \
        --actual-dir workspace/repos/foo/cases
"""
import argparse
import json
import re
from pathlib import Path

import jsonschema
from schemas import RESULT_SCHEMA


def run_check(check: dict, case_dir: Path) -> tuple[bool, str]:
    check_type = check["type"]

    if check_type == "file_exists":
        target = case_dir / check["target"]
        exists = target.exists()
        return exists, f"expected file '{check['target']}' to exist: {'found' if exists else 'missing'}"

    if check_type == "regex_match":
        target = case_dir / check.get("target", "actual.txt")
        if not target.exists():
            return False, f"'{target.name}' not found in case directory"
        content = target.read_text(errors="ignore")
        pattern = check["pattern"]
        matched = re.search(pattern, content) is not None
        return matched, f"pattern '{pattern}' {'matched' if matched else 'did not match'} in {target.name}"

    if check_type == "exit_code":
        target = case_dir / check.get("target", "exit_code.txt")
        if not target.exists():
            return False, f"'{target.name}' not found; cannot check exit code"
        try:
            actual_code = int(target.read_text().strip())
        except ValueError:
            return False, f"'{target.name}' did not contain an integer exit code"
        expected = check["expected_exit_code"]
        return actual_code == expected, f"expected exit code {expected}, got {actual_code}"

    if check_type == "line_count_min":
        target = case_dir / check.get("target", "actual.txt")
        if not target.exists():
            return False, f"'{target.name}' not found in case directory"
        line_count = len(target.read_text(errors="ignore").splitlines())
        min_lines = check["min_lines"]
        return line_count >= min_lines, f"expected >= {min_lines} lines, got {line_count}"

    return False, f"unknown check type: {check_type}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="Path to cases.json for one repo")
    ap.add_argument("--actual-dir", required=True, help="Directory containing <case_id>/actual.txt etc.")
    args = ap.parse_args()

    cases = json.loads(Path(args.case).read_text())
    actual_root = Path(args.actual_dir)

    graded, skipped = 0, 0
    for case in cases:
        if case.get("check_type") != "deterministic":
            skipped += 1
            continue

        case_dir = actual_root / case["case_id"]
        check = case.get("check")
        if not check:
            result = {
                "case_id": case["case_id"], "pass": False,
                "detail": "check_type=deterministic but no 'check' object provided",
                "graded_by": "error",
            }
        else:
            passed, detail = run_check(check, case_dir)
            result = {"case_id": case["case_id"], "pass": passed, "detail": detail, "graded_by": "script"}

        subs_path = case_dir / "input_substitutions.json"
        if subs_path.exists():
            try:
                subs = json.loads(subs_path.read_text())
                if subs:
                    result["input_substitutions"] = subs
            except (json.JSONDecodeError, OSError):
                pass  # malformed substitutions log shouldn't block grading

        jsonschema.validate(instance=result, schema=RESULT_SCHEMA)
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "result.json").write_text(json.dumps(result, indent=2))
        graded += 1
        print(f"[{'PASS' if result['pass'] else 'FAIL'}] {case['case_id']}: {result['detail']}")

    print(f"\nGraded {graded} deterministic case(s), skipped {skipped} semantic case(s) (grade those via LLM separately).")


if __name__ == "__main__":
    main()
