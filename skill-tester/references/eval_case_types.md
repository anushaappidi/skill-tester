# Writing good eval cases

Used in SKILL.md Step 4. Read this before generating `cases.json` for a repo.

## Prefer deterministic checks

A case is a good candidate for `check_type: "deterministic"` if the skill's
expected output is one of these shapes:

| Skill produces... | Use check type | Example |
|---|---|---|
| A specific file | `file_exists` | Skill should create `CHANGELOG.md` |
| Text containing a required pattern | `regex_match` | Output must mention the correct package manager (`npm`/`pip`/`cargo`) for this repo |
| A command that should succeed/fail | `exit_code` | Skill's generated fix makes `pytest` exit 0 |
| A minimum amount of output | `line_count_min` | Skill should generate at least N lines of docs |

These are graded entirely by `scripts/compare_results.py` — no LLM, no
ambiguity, fully reproducible across runs.

## When to use semantic cases

Only fall back to `check_type: "semantic"` when the correctness genuinely
depends on judgment a script can't express — e.g. "is this refactor
idiomatic for this codebase's existing style," or "does this summary
accurately reflect the repo's purpose." Keep the `rubric` field short
(1-2 sentences) and concrete. A vague rubric produces a vague, less
trustworthy grade.

Bad rubric: `"Check if the output is good."`
Better rubric: `"Pass only if the output references the repo's actual
build tool (found in manifests_present) and does not suggest a build
tool the repo doesn't use."`

## Case count guidance

3-5 cases per repo is usually enough. More cases per repo doesn't
meaningfully increase confidence once you're covering the skill's main
success criteria — it just multiplies LLM calls (Step 5) without adding
much signal. Better to add more *repos* than more cases per repo if you
want a more rigorous test.

## Every case needs a unique, filesystem-safe case_id

Lowercase, digits, hyphens/underscores only (`^[a-z0-9_-]+$`) — it's used
directly as a directory name in `workspace/repos/<name>/cases/<case_id>/`.
