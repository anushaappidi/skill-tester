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
    cases_path = repo_dir / "cases.json"
    if not cases_path.exists():
        return {"name": name, "status": "skipped", "reason": "no cases.json found (scan/clone likely failed)"}

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

    return {
        "name": name,
        "status": "tested",
        "cases": enriched,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
    }


def render_repo_section(repo: dict) -> str:
    if repo["status"] == "skipped":
        return f"## {repo['name']}\n\n**Skipped** — {repo['reason']}\n"

    rows = []
    for case in repo["cases"]:
        result = case["result"]
        mark = "✅ PASS" if result.get("pass") else "❌ FAIL"
        if result.get("graded_by") == "error":
            mark = "⚠️ ERROR"
        subs = result.get("input_substitutions") or []
        subs_note = f"{len(subs)} ({'; '.join(subs)})" if subs else "-"
        rows.append(f"| {case['case_id']} | {case['check_type']} | {mark} | {result.get('detail', '')} | {subs_note} |")

    table = "| Case | Type | Result | Detail | Defaults used |\n|---|---|---|---|---|\n" + "\n".join(rows)
    counts = f"- Cases: {len(repo['cases'])} ({repo['pass_count']} passed, {repo['fail_count']} failed"
    if repo["error_count"]:
        counts += f", {repo['error_count']} errored"
    counts += ")"

    return f"## {repo['name']}\n\n{counts}\n\n{table}\n"


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
        "REPO_SECTIONS": repo_sections,
    })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered)
    print(f"Wrote report: {out_path}")
    print(f"Totals: {total_pass} passed / {total_fail} failed / {total_error} errored (pass rate {pass_rate}%)")


if __name__ == "__main__":
    main()
