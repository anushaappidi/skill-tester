"""
schemas.py — JSON Schemas that every LLM output must validate against
before it's trusted and written to disk. This is the main defense
against hallucinated/malformed output silently corrupting the report.

Usage from another script:

    import jsonschema
    from schemas import EVAL_CASE_SCHEMA
    jsonschema.validate(instance=case_obj, schema=EVAL_CASE_SCHEMA)
"""

SKILL_SPEC_SCHEMA = {
    "type": "object",
    "required": ["purpose", "triggers", "inputs", "outputs", "success_criteria", "user_inputs", "phases"],
    "properties": {
        "purpose": {"type": "string", "minLength": 1},
        "triggers": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "inputs": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
        "success_criteria": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        # Every point where the skill under test would normally pause and
        # ask a human something (confirmations, choices, free-text
        # parameters). Empty array if the skill is fully non-interactive.
        "user_inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "prompt_kind", "default"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "prompt_kind": {
                        "type": "string",
                        "enum": ["confirm_yes_no", "choice", "path", "free_text", "number"],
                    },
                    "choices": {"type": "array", "items": {"type": "string"}},
                    "default": {"type": ["string", "number", "boolean"]},
                },
                "additionalProperties": False,
            },
        },
        # Every distinct stage/phase the skill under test's own SKILL.md
        # describes (e.g. "Step 1", "Phase 2: Validation"). Extracted once
        # here so every repo run can be checked against the SAME expected
        # phase list, regardless of how far the agent actually got.
        "phases": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["phase_id", "name", "description"],
                "properties": {
                    "phase_id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                    "expected_outputs": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

EVAL_CASE_SCHEMA = {
    "type": "object",
    "required": ["case_id", "description", "input", "check_type"],
    "properties": {
        "case_id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
        "description": {"type": "string", "minLength": 1},
        "input": {"type": "string", "minLength": 1},
        "check_type": {"type": "string", "enum": ["deterministic", "semantic"]},
        # Required when check_type == "deterministic"
        "check": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["file_exists", "regex_match", "exit_code", "line_count_min"],
                },
                "target": {"type": "string"},
                "pattern": {"type": "string"},
                "expected_exit_code": {"type": "integer"},
                "min_lines": {"type": "integer"},
                # "skill_run" = resolve target against the skill's shared
                # output directory (the normal case -- checking what the
                # skill actually produced). "case" = resolve against this
                # case's own directory (for a verification artifact the
                # grading step itself creates, e.g. a test-run exit code).
                # Defaults to "skill_run" if omitted.
                "root": {"type": "string", "enum": ["skill_run", "case"]},
            },
            "required": ["type"],
        },
        # Required when check_type == "semantic"
        "rubric": {"type": "string", "maxLength": 400},
        # Which phase (skill_spec.phases[].phase_id) this case is verifying.
        # Optional but strongly preferred -- lets the report show coverage
        # per phase, not just an undifferentiated pass/fail pile.
        "phase_id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
        # Optional: overrides skill_spec.user_inputs defaults for this
        # specific case (e.g. this case wants prompt_kind "path" answered
        # with "./src" instead of the global default ".").
        "input_defaults": {
            "type": "object",
            "additionalProperties": {"type": ["string", "number", "boolean"]},
        },
    },
    "additionalProperties": False,
}

JUDGMENT_SCHEMA = {
    "type": "object",
    "required": ["pass", "rationale"],
    "properties": {
        "pass": {"type": "boolean"},
        "rationale": {"type": "string", "maxLength": 400},
    },
    "additionalProperties": False,
}

RESULT_SCHEMA = {
    "type": "object",
    "required": ["case_id", "pass", "detail", "graded_by"],
    "properties": {
        "case_id": {"type": "string"},
        "pass": {"type": "boolean"},
        "detail": {"type": "string"},
        "graded_by": {"type": "string", "enum": ["script", "llm", "error"]},
        # Optional, only present if the skill under test paused for input
        # at least once during this case and a default was substituted.
        "input_substitutions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}

# One entry per phase transition, appended to phase_log.json IN REAL TIME
# as the agent works through the skill under test's phases in Step 5 --
# not reconstructed retroactively at the end. This is what makes it
# possible to see exactly where a run actually stopped, instead of only
# knowing the skill "didn't fully work."
PHASE_LOG_ENTRY_SCHEMA = {
    "type": "object",
    "required": ["phase_id", "status", "detail"],
    "properties": {
        "phase_id": {"type": "string", "pattern": "^[a-z0-9_-]+$"},
        "status": {"type": "string", "enum": ["started", "completed", "skipped", "error"]},
        "detail": {"type": "string", "maxLength": 400},
    },
    "additionalProperties": False,
}
