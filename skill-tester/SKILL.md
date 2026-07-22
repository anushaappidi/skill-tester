---
name: skill-tester
description: Test whether another skill (a SKILL.md) actually works by running it against real repos and grading the results. Use when the user wants to validate, benchmark, or regression-test a skill, or wants an evals report for one.
---

# Skill Tester

Given a **skill under test** (its `SKILL.md`, path given by the user) and a **repo list** (`config/repos.json`), this clones each repo, runs the skill against it phase-by-phase, grades the result, and produces one report: `evals/report.md`.

Cloning, scanning, gating, grading of checkable cases, phase-coverage diffing, and report rendering are all plain Python — deterministic, no LLM, can't hallucinate. The model is only used for: reading the target skill's `SKILL.md` (Step 1), writing eval cases (Step 4), and actually running the skill (Step 5) — plus grading cases that genuinely can't be checked by script (Step 6).

## Rules

These apply throughout the workflow below. Each step references the rule number it's most relevant to, but all of them hold at all times.

1. **A repo must be in `gate_check.py`'s ELIGIBLE list before any eval case is generated or graded for it.** A failed clone is reported as "skipped," never as a pass.
2. **A phase is "completed" only if its actual work happened and produced a real artifact.** Checking whether a phase *would apply* to a repo is not performing it. "Not confirmed available" / "might not be" / similar hedges are never valid reasons to skip — test for real (run `mvn --version`, install if missing) before concluding something can't run.
3. **Never write new scripts to reimplement the skill under test.** Apply it by following its own `SKILL.md` directly, the way it would run normally. Use its own bundled scripts if it has any.
4. **Do every phase, for every eligible repo, however many turns it takes.** Running low on turns is never a reason to shortcut to shallow checks.
5. **`build_report.py` runs unconditionally at the end of every session**, regardless of how far anything else got. No report = failed session.
6. **The model never computes or states aggregate counts.** Only `build_report.py`'s numbers are real.
7. **Every LLM JSON output is validated against `schemas.py` before being written.** Retry once with the validation error attached; if it fails twice, write an `"error"` result instead of guessing.
8. **Semantic grading (Step 6) sees only that one case's rubric + output** — never the whole report or other cases, to avoid the model rationalizing consistency instead of judging on the merits.

## Folder contents

```
skill-tester/
├── SKILL.md
├── config/repos.example.json        (copy to repos.json)
├── scripts/
│   ├── clone_and_scan_all.py        clone + scan every repo, in parallel
│   ├── gate_check.py                marks repos ineligible if clone/scan failed (rule 1)
│   ├── phase_coverage.py            diffs phase_log.json against expected phases
│   ├── compare_results.py           grades deterministic cases against skill_run/
│   ├── build_report.py              renders evals/report.md from the JSON on disk
│   └── schemas.py                   JSON schemas for every LLM output (rule 7)
├── templates/report_template.md     plain {{PLACEHOLDER}} markdown, no template engine
└── references/
    ├── eval_case_types.md           deterministic vs semantic case guidance
    └── default_input_policy.md      default answers when the skill asks for input
```

## Workflow

### Step 0 — Setup
```bash
mkdir -p workspace/repos evals
cp skill-tester/config/repos.example.json skill-tester/config/repos.json   # if not present
```
Confirm `repos.json` and the skill-under-test path with the user if either is ambiguous.

### Step 1 — Parse the skill under test [LLM, 1 call]
Read the target `SKILL.md` in full. Write `workspace/skill_spec.json` matching `schemas.py::SKILL_SPEC_SCHEMA` (rule 7):
- `purpose`, `triggers`, `inputs`, `outputs`, `success_criteria` — direct extraction.
- `user_inputs` — every point the skill would pause and ask a human something (`[]` if none). Default values come from `references/default_input_policy.md`.
- `phases` — every distinct stage the skill's own `SKILL.md` describes (usually literal "Step N"/"Phase N" sections; one phase if the skill has no internal structure). This list is the fixed yardstick every repo's run gets checked against.

### Step 2 — Clone + scan, in parallel [python]
```bash
python skill-tester/scripts/clone_and_scan_all.py --config skill-tester/config/repos.json --dest workspace/repos --max-workers 4
```
Each repo writes only to its own `workspace/repos/<name>/`, so concurrency is safe by construction. `ref` in `repos.json` is optional — omit it to clone the repo's actual default branch (don't assume `main`).

### Step 3 — Gate [python, mandatory]
```bash
python skill-tester/scripts/gate_check.py --dest workspace/repos
```
Marks any repo that didn't actually clone+scan with `SKIPPED.json`. Only repos in the printed ELIGIBLE list may proceed past this point (rule 1). `build_report.py` treats `SKIPPED.json` as authoritative even if a `cases.json` exists for that repo.

### Step 4 — Generate eval cases [LLM, 1 call per eligible repo]
Input: `skill_spec.json` + that repo's `scan.json` only (not the raw repo — keeps the prompt small). Write 3-5 cases to `workspace/repos/<name>/cases.json` matching `schemas.py::EVAL_CASE_SCHEMA`:
- Prefer `check_type: "deterministic"` (file exists / regex / exit code / line count) over `"semantic"`. Only use semantic for genuinely open-ended output, with a short concrete `rubric`.
- Tag each case's `phase_id` so the report can show coverage per phase, not just one pass/fail pile.
- `check.target` paths resolve against the shared `skill_run/` output by default (see Step 6).

### Step 5 — Run the skill [LLM, 1 call per eligible repo — not per case]
Run the skill **once per repo**, following its own `SKILL.md` phase by phase against `workspace/repos/<name>/` (rule 3). All that repo's cases grade this one run.

- Save whatever the skill produces under `workspace/repos/<name>/skill_run/`.
- Log every phase transition **live, as it happens** to `workspace/repos/<name>/phase_log.json` (`schemas.py::PHASE_LOG_ENTRY_SCHEMA`): a `"started"` entry, then `"completed"`/`"skipped"`/`"error"` with a one-sentence `detail`. Never backfill entries for phases you didn't reach, never mark something `"completed"` that wasn't (rule 2).
- If the skill asks for input, resolve it immediately per `references/default_input_policy.md` — never wait for a person. Log substitutions to `workspace/repos/<name>/input_substitutions.json` (`[]` if none). Exception: don't auto-confirm anything destructive the skill's spec didn't already expect — log that as an `"error"` phase instead.
- Do every phase for real (rule 2, rule 4). Don't self-grade here.

### Step 5.5 — Phase coverage [python, mandatory]
```bash
python skill-tester/scripts/phase_coverage.py --skill-spec workspace/skill_spec.json --phase-log workspace/repos/<name>/phase_log.json --out workspace/repos/<name>/phase_coverage.json
```
Diffs the expected phase list against what was actually logged; anything missing becomes `"not_reached"`. Also flags skip/error reasons that look like unverified assumptions ("not confirmed available" etc.) rather than tested blockers.

### Step 6 — Grade
Deterministic cases [python]:
```bash
python skill-tester/scripts/compare_results.py --case workspace/repos/<name>/cases.json --skill-run-dir workspace/repos/<name>/skill_run --case-dir workspace/repos/<name>/cases --input-substitutions workspace/repos/<name>/input_substitutions.json
```
Semantic cases [LLM, 1 call each]: rubric + output only (rule 8) → strict `{"pass": bool, "rationale": "<=2 sentences"}` validated against `JUDGMENT_SCHEMA`, merged with substitutions, written as `result.json` matching `RESULT_SCHEMA`.

### Step 7 — Build the report [python, mandatory, unconditional]
```bash
python skill-tester/scripts/build_report.py --workspace workspace --template skill-tester/templates/report_template.md --out evals/report.md
```
Run this regardless of how far anything above got (rule 5) — it faithfully reflects whatever partial state is on disk.

## Parallelizing across repos

Steps 2 is always parallel (bounded thread pool, isolated per-repo directories — safe by construction). For Steps 4-6, if the runtime supports subagents: one track per repo, capped at 4-6 concurrent, each confined to its own repo's directory, failures isolated per-track. Step 7 is a hard barrier — run exactly once, after every track finishes.
