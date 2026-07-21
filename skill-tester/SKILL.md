---
name: skill-tester
description: Test whether another skill (defined in a SKILL.md) actually works, by running it against a set of real repositories and grading the results. Use this whenever the user wants to validate, benchmark, or regression-test a skill against multiple repos, wants an evals report for a skill, or asks to "test my skill against these repos." Minimizes LLM calls by delegating every deterministic step (cloning, scanning, comparing, reporting) to Python scripts, using the model only for the three steps that genuinely require judgment.
---

# Skill Tester

## Purpose

Given:
1. A **skill under test** — a `SKILL.md` (and any bundled scripts) somewhere in the workspace.
2. A **list of repos** to test it against — `config/repos.json`.

...this skill clones each repo, figures out what a fair test of the skill looks like on that specific repo, runs the skill, grades the result, and produces a single Markdown report.

## Design principle: minimize LLM calls

LLMs can hallucinate, especially when asked to summarize their own results or do arithmetic. So the rule here is:

- **Only 3 kinds of calls use the model** (parsing the skill spec once, generating eval cases once per repo, running the skill under test once per repo — plus grading *only* for cases that truly can't be checked mechanically).
- **Everything else is Python**: cloning, repo scanning, deterministic checks, counting, aggregating, and rendering the final report. The model never writes the final pass/fail counts — `scripts/build_report.py` computes them from raw JSON files on disk.
- **Prefer deterministic eval cases over semantic ones.** When generating eval cases in Step 4, always ask: "can this be checked with a regex / file-exists / exit-code check?" before falling back to LLM judgment.

## Folder contents

```
skill-tester/
├── SKILL.md                    (this file)
├── config/
│   └── repos.example.json      (copy to repos.json and edit)
├── scripts/
│   ├── clone_repos.py          (deterministic: git clone, single-repo/standalone)
│   ├── scan_repo.py            (deterministic: structure summary -> JSON, single-repo/standalone)
│   ├── clone_and_scan_all.py   (deterministic: clone+scan ALL repos in parallel, safely)
│   ├── gate_check.py           (deterministic: hard-blocks Steps 4-6 for repos that didn't actually clone)
│   ├── phase_coverage.py       (deterministic: diffs expected phases vs phase_log.json -> phase_coverage.json)
│   ├── compare_results.py      (deterministic: grade check_type="deterministic" cases against skill_run/)
│   ├── build_report.py         (deterministic: JSON -> Markdown report)
│   └── schemas.py              (JSON schemas used to validate every LLM output)
├── templates/
│   └── report_template.md
└── references/
    ├── eval_case_types.md      (what makes a good deterministic vs semantic case)
    └── default_input_policy.md (deterministic defaults when the skill under test asks for input)
```

## Workflow

Run these steps in order. Steps marked **[LLM]** are the only ones where you (the agent) generate content yourself rather than running a script. Steps marked **[python]** must be run via the terminal tool exactly as shown — do not reimplement their logic yourself, and do not skip them.

### Step 0 — Setup

```bash
mkdir -p workspace/repos evals
cp skill-tester/config/repos.example.json skill-tester/config/repos.json   # if not already present
```

Ask the user to confirm `config/repos.json` and the path to the skill under test before proceeding, if either is ambiguous.

### Step 1 — Parse the skill under test **[LLM, 1 call]**

Read the target skill's `SKILL.md` in full. Produce strict JSON matching `scripts/schemas.py::SKILL_SPEC_SCHEMA`:

```json
{
  "purpose": "...",
  "triggers": ["...", "..."],
  "inputs": ["..."],
  "outputs": ["..."],
  "success_criteria": ["...", "..."],
  "user_inputs": [
    {
      "name": "confirm_overwrite",
      "description": "asks before overwriting an existing file",
      "prompt_kind": "confirm_yes_no",
      "default": "yes"
    }
  ],
  "phases": [
    {
      "phase_id": "phase1",
      "name": "Validate inputs",
      "description": "checks the repo has the expected structure before doing anything",
      "expected_outputs": ["a validation summary"]
    }
  ]
}
```

`user_inputs` covers every point where the skill would normally pause and ask a human something — confirmations, choices, free-text parameters, paths. Use `[]` if the skill is fully non-interactive. Pick each `default` using `references/default_input_policy.md`'s fallback table unless the skill's own docs suggest a more specific sensible default for that particular prompt.

`phases` covers every distinct stage the target `SKILL.md` describes — most skills are already written as "Step 1 / Step 2 / ..." or "Phase 1 / Phase 2 / ...", so this is usually direct extraction, not inference. If the skill genuinely has no internal phase structure (a single-shot task), use one phase covering the whole thing. This list is what makes it possible to see exactly how far a run got on a given repo, instead of only knowing whether the final output matched — get this right, since it's used as the fixed yardstick for every repo's phase log later.

Write it to `workspace/skill_spec.json` (use the file-write tool; do not hand-format — copy the JSON exactly).

### Step 2+3 — Clone and scan repos, in parallel **[python]**

```bash
python skill-tester/scripts/clone_and_scan_all.py \
  --config skill-tester/config/repos.json \
  --dest workspace/repos \
  --max-workers 4
```

This runs the clone + scan for every repo concurrently using a bounded
thread pool (default 4 workers) — fully deterministic, no model involved,
and safe by construction:

- Each repo only ever writes to its own `workspace/repos/<name>/`
  directory, so there's no shared mutable state between workers to
  corrupt.
- Concurrency is capped to avoid tripping GitHub's secondary rate limits
  from too many simultaneous clones. Raise `--max-workers` cautiously —
  8-10 max even on a fast connection; going higher tends to produce
  intermittent clone failures rather than real speedup.
- One repo failing (bad URL, wrong ref, network blip) is caught and
  recorded in `_clone_scan_summary.json` without aborting the others.
- Re-running is safe: already-cloned repos are skipped unless `--force`
  is passed.

This step alone captures most of the wall-clock savings, since cloning is
the slowest part of the pipeline and doesn't depend on the agent runtime
supporting parallel subagents at all.

If you'd rather run clone/scan one repo at a time (e.g. debugging a
single failure), `scripts/clone_repos.py` and `scripts/scan_repo.py`
still work standalone exactly as before.

### Step 3.5 — Gate: only repos that actually cloned may proceed **[python, mandatory]**

```bash
python skill-tester/scripts/gate_check.py --dest workspace/repos
```

Run this before touching Step 4. It reads the clone/scan summary and marks any repo that didn't actually clone+scan successfully with a `SKIPPED.json` file in that repo's directory.

**Hard rule: for every repo in the SKIPPED list this prints, do not perform Steps 4-6 for it. Do not generate `cases.json`. Do not call the model claiming to "apply the skill" against it.** A repo that failed to clone has no content to test against — generating eval cases anyway produces a report that looks like the skill passed when it was never actually run. `build_report.py` also enforces this at the code level (a `SKIPPED.json` marker overrides any `cases.json` found for that repo), but don't rely on that backstop — treat the ELIGIBLE list from this script's output as the actual scope of Steps 4-6.

If a repo you expected to test shows up SKIPPED, check the reason before moving on — it's usually one of: wrong `ref` in `config/repos.json` (fixed automatically now — omit `ref` entirely unless you need a non-default branch), a private repo needing auth (see note below), or the URL being wrong/repo renamed.

**Private repos:** these scripts use plain `git clone` over HTTPS, so a private repo will fail with an auth error unless your environment's git is already configured with credentials (e.g. a credential helper or an `https://<token>@github.com/...` URL in `config/repos.json`). There's no separate auth mechanism built into these scripts — whatever `git clone <url>` would do in your terminal is what happens here.

### Step 4 — Generate eval cases **[LLM, 1 call per repo]**

Input: `workspace/skill_spec.json` + `workspace/repos/<name>/scan.json` (never the raw repo — scan.json only).

Produce 3-5 eval cases as JSON matching `scripts/schemas.py::EVAL_CASE_SCHEMA`. For each case, set `check_type` to `"deterministic"` whenever the expected result can be checked by a script (a file exists, a string matches a regex, a command's exit code is 0, a specific line count). Only use `"semantic"` when the skill's output is genuinely open-ended (e.g. quality of written prose) and provide a `rubric` (1-2 sentences, not a full essay) for the semantic case.

Set each case's `phase_id` to the `skill_spec.phases[].phase_id` it's actually verifying — this is what lets the report show coverage per phase instead of one undifferentiated pile of pass/fail. Try to cover multiple phases across your cases, not just the skill's final output; a case checking something phase 2 produces is what catches "phase 2 silently never ran" even when later phases happen to look fine.

Since all cases for a repo check the output of a single shared skill run (Step 5), a case's `check.target` should be a path relative to that run's output directory unless it's an `exit_code` check (see `check.root` in the schema).

Write to `workspace/repos/<name>/cases.json`.

If a particular case needs a different answer to one of the skill's `user_inputs` than the global default (e.g. to specifically test the "no" branch of a confirmation), set that case's `input_defaults` to override it for that case only — see `scripts/schemas.py::EVAL_CASE_SCHEMA`.

### Step 5 — Apply the skill under test **[LLM, 1 call per repo, not per case]**

Run the skill **once per repo**, following its phases in order against the cloned repo at `workspace/repos/<name>/`. All of that repo's eval cases (Step 4) check the output of this single run — the skill isn't re-run separately per case. This is both more realistic (phase-based skills are meant to run start-to-finish once) and cheaper (one model-driven run instead of N).

**"Running a phase" means actually doing the phase's work, not checking whether the phase would apply.** If the skill under test has no executable scripts of its own — it's instructions for an agent to carry out by hand — then carrying it out means genuinely reading the relevant code, making the judgment calls the phase describes, and producing whatever artifact the phase is supposed to produce. Determining "this repo matches the profile this phase targets" or "this is the route this phase would take" is discovery, not execution — it is never sufficient to log a phase `"completed"`. A phase without a concrete produced artifact (a file written, a diff made, a decision explicitly recorded with its reasoning) is not completed, no matter how confident the routing analysis was.

If a phase's `expected_outputs` (from `skill_spec.json`) says it should produce something, that something needs to actually exist under `skill_run/` before you log `"completed"` for it. If you find yourself about to write `"completed"` based on reasoning like "this would route to X" or "the profile indicates Y applies here" without X or Y having actually been done — stop, that's the shortcut this rule exists to catch, and it is not permitted. Do every phase for real, for every eligible repo. Running out of context or turns partway through is not a reason to switch to shallow checks for the remaining phases or repos — continue the actual execution work across as many turns/tool calls as it takes.

**"Not confirmed available" is never a valid reason to skip a phase.** If a phase needs a build tool, test runner, or dependency (Maven, npm, pip, etc.), you have a terminal — check for real (`mvn --version`, `npm --version`) and if it's missing, install it (`apt-get install`, `npm install -g`, etc.) before concluding the phase can't run. A blanket assumption that tooling "might not be available in the test environment" is exactly the kind of shortcut this rule exists to catch — it is not permitted regardless of how many repos or phases are in scope. The only acceptable reason to log something other than `"completed"` is a genuine blocker you actually hit and can point to specific evidence for — the exact command you ran and its exact failure output (a real install failure, no network access, a permission error) — never a supposition you didn't test.

Put whatever files the skill produces under `workspace/repos/<name>/skill_run/` (create it if the skill doesn't already write there — copy/move its output in if it wrote elsewhere).

**Log every phase transition to `workspace/repos/<name>/phase_log.json` in real time, as you go — not reconstructed at the end.** Each entry matches `scripts/schemas.py::PHASE_LOG_ENTRY_SCHEMA`:

```json
{"phase_id": "phase2", "status": "started", "detail": "running test suite"}
```

Append a `"started"` entry when you begin a phase, then a `"completed"`, `"skipped"`, or `"error"` entry when it resolves, with a one-sentence `detail`. If you stop partway through — the skill errors out, a phase's prerequisites aren't met, you run out of context — the log up to that point is the truth of what happened; do not go back and add entries for phases you didn't actually reach, and do not describe a phase as `"completed"` if it wasn't. This log is the entire point of this step's structure: it's what makes a partial run visible in the report instead of just looking like a mysteriously-failing final check.

**If the skill under test pauses to ask for input at any point, never wait for a real person.** Resolve it immediately using `references/default_input_policy.md`'s priority order (case's `input_defaults` → skill spec's `user_inputs` default → fallback table), supply that value, and keep going. Record every substitution as a JSON array of short strings (e.g. `"confirm_overwrite=yes (from skill_spec default)"`) and write it to `workspace/repos/<name>/input_substitutions.json`. Write `[]` if the run had no interactive prompts at all.

Exception: if a prompt is asking about something destructive or irreversible that the skill spec didn't already document as expected behavior, don't auto-confirm it — log it as an `"error"` phase entry with the reason instead, and stop there.

Do not self-grade in this step. Just run the skill and log what happened.

### Step 5.5 — Compute phase coverage **[python, mandatory]**

```bash
python skill-tester/scripts/phase_coverage.py \
  --skill-spec workspace/skill_spec.json \
  --phase-log workspace/repos/<name>/phase_log.json \
  --out workspace/repos/<name>/phase_coverage.json
```

Run once per repo, right after Step 5. Purely deterministic — it diffs the expected phase list from `skill_spec.json` against what actually got logged, and marks any expected phase with no log entry as `"not_reached"`. This is what surfaces a 7-phase skill that quietly stopped after phase 2 as "2/7 completed, phases 3-7 not reached" in the final report, rather than the report only reflecting whatever the last-reached phase happened to produce.

### Step 6 — Grade

- **Deterministic cases [python]:**
  ```bash
  python skill-tester/scripts/compare_results.py \
    --case workspace/repos/<name>/cases.json \
    --skill-run-dir workspace/repos/<name>/skill_run \
    --case-dir workspace/repos/<name>/cases \
    --input-substitutions workspace/repos/<name>/input_substitutions.json
  ```
  Writes `result.json` per case with `{"pass": true/false, "detail": "..."}`, checked against the skill's actual output in `skill_run/`. No model call, no hallucination risk. It automatically folds in the repo's shared `input_substitutions.json` from Step 5, if present.

- **Semantic cases [LLM, 1 call per semantic case only]:** Give the model the case's rubric + the relevant part of `skill_run/`'s output, ask for strict JSON: `{"pass": true|false, "rationale": "<=2 sentences"}`. Nothing else — no free-form commentary, no summarizing other cases. Validate against `schemas.py::JUDGMENT_SCHEMA`, then merge in the repo's `input_substitutions.json` (if any) before writing the combined object to `result.json`, matching `schemas.py::RESULT_SCHEMA`.

### Step 7 — Build the report **[python]**

```bash
python skill-tester/scripts/build_report.py \
  --workspace workspace \
  --template skill-tester/templates/report_template.md \
  --out evals/report.md
```

Reads every `cases.json` + `result.json` on disk, computes pass/fail counts and per-repo breakdowns in Python, and renders the Markdown report from the template. The model is never asked to summarize or total anything here — that's exactly the kind of step where LLMs quietly get arithmetic wrong.

## Parallelizing across repos

**Deterministic steps (2+3):** always parallel via `clone_and_scan_all.py` — see above. This works regardless of agent runtime capabilities and needs no special handling, since each repo is fully isolated on disk.

**LLM steps (4-6):** if the agent runtime supports subagents/multi-agent mode, dispatch one subagent per repo for eval-case generation, skill application, and grading. Keep it safe:

- **Bound concurrency.** Don't spawn more parallel subagents than repos actually need — 4-6 at once is a reasonable ceiling even if more repos are queued, to avoid rate limits on the model API and to keep output legible if you're watching the chat live. Queue the rest.
- **No shared writes.** Each subagent must only read/write inside its own `workspace/repos/<name>/` directory (it already only needs `skill_spec.json`, which is read-only by this point, and its own `scan.json`). Never have a subagent touch another repo's directory or the shared `evals/` output.
- **Isolate failures.** One repo's subagent erroring out (bad clone, model refusal, malformed JSON that fails schema validation twice) must not block or corrupt the other tracks. Mark that repo `"error"` in its own directory and move on.
- **Step 7 is a hard synchronization barrier.** `build_report.py` must run exactly once, after every subagent track has finished (successfully or with a recorded error) — never run it mid-flight, and never run it more than once per session (it would just overwrite the same file, but running it early produces an incomplete/misleading report).
- If the runtime falls back to sequential subagents (no true parallelism), that's fine — it's still correct, just slower. `clone_and_scan_all.py` already gives you the bulk of the time savings independent of this.

See `references/eval_case_types.md` for guidance the subagents can share.

## Guardrails (read before running)

- **Never generate eval cases or apply the skill against a repo that isn't in `gate_check.py`'s ELIGIBLE list.** This is one of the two most important rules in this file — a skipped/failed clone must produce a "skipped" result in the report, never a "passed" one. If you're ever unsure whether a repo actually cloned, check for `scan.json` in its directory before doing anything else with it.
- **Never substitute checking whether a phase would apply for actually performing it.** This is the other most important rule — a phase is only `"completed"` if its real work happened and produced a concrete artifact. Confirming "this repo matches the routing profile for phase 3" is not phase 3. If a full end-to-end run across every repo turns out to be too much work for one pass, say so and propose running fewer repos at full depth rather than all repos at shallow depth — a smaller number of honestly-executed repos is worth more than a report that looks complete but isn't.
- Never let the model report aggregate counts, percentages, or "X out of Y passed" — that must come from `build_report.py` only.
- Every LLM JSON output must validate against the matching schema in `scripts/schemas.py` before being written to disk. If it fails validation, retry the call once with the validation error appended; if it fails twice, mark the case as `"error"` rather than guessing.
- Keep semantic-judgment prompts scoped to a single case (rubric + actual output). Never show the model the whole report-in-progress when grading a single case — that invites it to rationalize consistency with earlier cases instead of judging this one on its merits.
- If a repo fails to clone or a scan turns up nothing usable, mark it `"skipped"` in the report with the reason — don't have the model improvise eval cases for a repo it can't actually see.
