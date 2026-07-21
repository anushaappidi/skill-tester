#!/usr/bin/env python3
"""
build_report.py — deterministic aggregation and rendering. No LLM involved.

Walks workspace/repos/<name>/cases.json + workspace/repos/<name>/cases/<id>/result.json
for every repo, computes counts in plain Python (so nothing can be
hallucinated), and fills in templates/report_template.md via simple
{{PLACEHOLDER}} string substitution. No template engine dependency —
stdlib only.

Usage:
    python build_report.py --workspace workspace \
        --template skill-tester/templates/report_template.md \
        --out evals/report.md
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_repo(repo_dir: Path) -> dict:
    name = repo_dir.name

    # SKIPPED.json is authoritative and set by gate_check.py based on
    # actual clone/scan success -- it overrides everything else, even if
    # a cases.json exists for this repo (which would mean Steps 4-6 ran
    # against a repo that was never actually available, producing a
    # misleading report).
    skipped_marker = repo_dir / "SKIPPED.json"
    if skipped_marker.exists():
        info = json.loads(skipped_marker.read_text())
        result = {"name": name, "status": "skipped", "reason": info.get("reason", "unknown")}
        if (repo_dir / "cases.json").exists():
            result["reason"] += (" [NOTE: cases.json was found for this repo despite it being marked "
                                  "ineligible by gate_check.py -- those results were discarded]")
        return result

    cases_path = repo_dir / "cases.json"
    if not cases_path.exists():
        return {"name": name, "status": "skipped", "reason": "no cases.json found (repo was never gated eligible)"}

    cases = json.loads(cases_path.read_text())
    enriched = []
    pass_count = fail_count = error_count = 0

    for case in cases:
        result_path = repo_dir / "cases" / case["case_id"] / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
        else:
            result = {"pass": False, "detail": "no result.json found — case was never graded", "graded_by": "error"}

        if result.get("graded_by") == "error":
            error_count += 1
        elif result.get("pass"):
            pass_count += 1
        else:
            fail_count += 1

        enriched.append({**case, "result": result})

    phase_coverage_path = repo_dir / "phase_coverage.json"
    phase_coverage = json.loads(phase_coverage_path.read_text()) if phase_coverage_path.exists() else None

    return {
        "name": name,
        "status": "tested",
        "cases": enriched,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "phase_coverage": phase_coverage,
    }


def render_phase_table(phase_coverage: dict) -> str:
    if not phase_coverage:
        return "*(no phase_coverage.json found for this repo -- Step 5.5 wasn't run, or the skill under test has no declared phases)*\n"

    status_marks = {
        "completed": "✅ completed", "started": "🟡 started (not completed)",
        "skipped": "⏭️ skipped", "error": "❌ error", "not_reached": "⬜ not reached",
    }
    rows = []
    for p in phase_coverage["phases"]:
        mark = status_marks.get(p["status"], p["status"])
        detail = p["detail"]
        if p.get("unverified_skip"):
            detail = f"⚠️ UNVERIFIED ASSUMPTION, not a tested blocker: {detail}"
        rows.append(f"| {p['phase_id']} | {p['name']} | {mark} | {detail} |")

    header = f"**Phase coverage: {phase_coverage['completed_phases']}/{phase_coverage['total_phases']} completed**\n\n"
    table = "| Phase | Name | Status | Detail |\n|---|---|---|---|\n" + "\n".join(rows)
    return header + table + "\n"


def render_repo_section(repo: dict) -> str:
    if repo["status"] == "skipped":
        return f"## {repo['name']}\n\n**Skipped** — {repo['reason']}\n"

    phase_section = render_phase_table(repo.get("phase_coverage"))

    rows = []
    for case in repo["cases"]:
        result = case["result"]
        mark = "✅ PASS" if result.get("pass") else "❌ FAIL"
        if result.get("graded_by") == "error":
            mark = "⚠️ ERROR"
        subs = result.get("input_substitutions") or []
        subs_note = f"{len(subs)} ({'; '.join(subs)})" if subs else "-"
        phase_tag = case.get("phase_id", "-")
        rows.append(f"| {case['case_id']} | {phase_tag} | {case['check_type']} | {mark} | {result.get('detail', '')} | {subs_note} |")

    table = "| Case | Phase | Type | Result | Detail | Defaults used |\n|---|---|---|---|---|---|\n" + "\n".join(rows)
    counts = f"- Cases: {len(repo['cases'])} ({repo['pass_count']} passed, {repo['fail_count']} failed"
    if repo["error_count"]:
        counts += f", {repo['error_count']} errored"
    counts += ")"

    return f"## {repo['name']}\n\n{phase_section}\n{counts}\n\n{table}\n"


def render_report(template_text: str, values: dict) -> str:
    rendered = template_text
    for key, val in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(val))
    return rendered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True, help="Path containing repos/<name>/ dirs")
    ap.add_argument("--template", required=True, help="Path to report_template.md")
    ap.add_argument("--out", required=True, help="Where to write the final report")
    ap.add_argument("--skill-spec", default=None, help="Path to skill_spec.json (defaults to <workspace>/skill_spec.json)")
    args = ap.parse_args()

    workspace = Path(args.workspace)
    repos_dir = workspace / "repos"
    spec_path = Path(args.skill_spec) if args.skill_spec else workspace / "skill_spec.json"

    skill_spec = json.loads(spec_path.read_text()) if spec_path.exists() else {"purpose": "(skill_spec.json not found)"}

    repo_results = []
    for repo_dir in sorted(p for p in repos_dir.iterdir() if p.is_dir()):
        repo_results.append(load_repo(repo_dir))

    total_pass = sum(r.get("pass_count", 0) for r in repo_results)
    total_fail = sum(r.get("fail_count", 0) for r in repo_results)
    total_error = sum(r.get("error_count", 0) for r in repo_results)
    total_cases = total_pass + total_fail + total_error
    skipped_repos = sum(1 for r in repo_results if r["status"] == "skipped")
    pass_rate = round(100 * total_pass / total_cases, 1) if total_cases else 0.0

    phase_pcts = []
    for r in repo_results:
        pc = r.get("phase_coverage")
        if pc and pc["total_phases"]:
            phase_pcts.append(100 * pc["completed_phases"] / pc["total_phases"])
    avg_phase_completion = round(sum(phase_pcts) / len(phase_pcts), 1) if phase_pcts else "n/a"

    repo_sections = "\n".join(render_repo_section(r) for r in repo_results)

    template_text = Path(args.template).read_text()
    rendered = render_report(template_text, {
        "PURPOSE": skill_spec.get("purpose", "(unknown)"),
        "GENERATED_AT": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "TOTAL_REPOS": len(repo_results),
        "SKIPPED_REPOS": skipped_repos,
        "TOTAL_CASES": total_cases,
        "TOTAL_PASS": total_pass,
        "TOTAL_FAIL": total_fail,
        "TOTAL_ERROR": total_error,
        "PASS_RATE": pass_rate,
        "AVG_PHASE_COMPLETION": avg_phase_completion,
        "REPO_SECTIONS": repo_sections,
    })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered)
    print(f"Wrote report: {out_path}")
    print(f"Totals: {total_pass} passed / {total_fail} failed / {total_error} errored (pass rate {pass_rate}%)")


if __name__ == "__main__":
    main()
