---
mode: agent
---
Follow the workflow in `skill-tester/SKILL.md` exactly, step by step.

Rules:
- Steps marked [python] must be run via the terminal tool using the exact
  commands shown in SKILL.md. Do not reimplement their logic yourself.
- After cloning/scanning, run `gate_check.py` before doing anything else.
  Never generate eval cases or claim to run the skill against a repo
  that isn't in its ELIGIBLE output — a repo that failed to clone must
  show up as "skipped" in the final report, never as passing.
- Steps marked [LLM] are the only ones where you generate content directly.
  Validate that content against the matching schema in
  `skill-tester/scripts/schemas.py` before writing it to disk.
- Never compute or state aggregate pass/fail counts yourself — those come
  only from `scripts/build_report.py`'s output.
- Always use `clone_and_scan_all.py` (not the single-repo scripts) so
  cloning and scanning run in parallel across all repos.
- If subagents are available, parallelize the LLM steps (eval-case
  generation, applying the skill, grading) one track per repo, capped at
  4-6 concurrent tracks. Each track may only read/write inside its own
  repo's directory — never touch another repo's files or the shared
  evals/ output mid-flight. Run the report-building step exactly once,
  only after every track has finished.
- If the skill under test asks for input at any point while you're
  applying it (Step 5), never wait for me. Resolve it per
  `skill-tester/references/default_input_policy.md` and log the
  substitution — unless the prompt concerns something destructive or
  irreversible the skill's spec didn't already expect, in which case
  treat it as a failed case instead of auto-confirming.
- Ask me to confirm `skill-tester/config/repos.json` and the path to the
  skill under test before starting if either is missing or ambiguous.
- Before running any destructive command (e.g. --force re-clone), ask
  for confirmation first.

When finished, open `evals/report.md` and give me a one-paragraph summary.
