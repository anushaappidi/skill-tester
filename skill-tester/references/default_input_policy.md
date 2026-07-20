# Default input policy

Used in SKILL.md Steps 1, 4, and 5. Read this whenever the skill under
test would normally pause and ask a human something.

## Principle

The skill-tester runs unattended. If the skill under test ever stops to
ask a question — a confirmation prompt, a choice of options, a free-text
parameter, a path — **never wait for a real person**. Supply a default
immediately and keep going. What matters is that the default is chosen
by a fixed, predictable rule, not improvised fresh each time — otherwise
identical runs could produce different results depending on how the
model "feels" about a prompt that day.

## Where defaults come from, in priority order

1. **The eval case's own `input_defaults`**, if the case set one for
   this specific prompt name (Step 4 can override the skill-wide
   default when a case specifically needs a different answer to test a
   particular path).
2. **The skill spec's `user_inputs[].default`**, extracted once in Step
   1 when the skill's `SKILL.md` was parsed.
3. **The fallback table below**, if a prompt appears at runtime that
   wasn't anticipated in Step 1 (the skill under test asked something
   its own SKILL.md didn't document).

## Fallback table (used only when 1 and 2 don't cover it)

| prompt_kind | Fallback default | Why |
|---|---|---|
| `confirm_yes_no` | `yes` | Assume the common/happy path proceeds; a skill that destructively assumes "yes" on every confirmation is itself worth flagging as a finding, not silently avoided |
| `choice` | First item in the listed choices | Deterministic, reproducible — not "whichever seems best" |
| `path` | `.` (current repo root) | Matches the natural default for a tool operating on the cloned repo |
| `free_text` | Empty string, or if the skill errors on empty, the literal string `test` | Prefer empty first — reveals whether the skill actually requires meaningful input |
| `number` | `1` | Smallest valid/typical value; avoids accidentally triggering expensive or large-scale behavior |

## Recording substitutions (required, for transparency)

Whenever a default is used — from any of the 3 sources above — record it
in the case's `result.json` under `input_substitutions`, e.g.:

```json
{"input_substitutions": ["confirm_overwrite=yes (from skill_spec default)", "target_dir=. (fallback table)"]}
```

This makes it visible in the report which cases actually exercised a
default vs. which ran with no interactive prompts at all — a case that
silently used a fallback-table default (source 3) is a signal the skill
under test has undocumented interactive behavior worth investigating,
not just a testing artifact to hide.

## What this does NOT cover

Do not use this policy to paper over prompts that are asking something
genuinely unsafe to default (e.g. "this will delete production data,
proceed?"). If a prompt's wording suggests a destructive or irreversible
action, treat that as a finding — record it as a failed case with
`graded_by: "error"` and a detail explaining what was skipped, rather
than defaulting to "yes" and letting it run.
