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
    "required": ["purpose", "triggers", "inputs", "outputs", "success_criteria", "user_inputs"],
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
            },
            "required": ["type"],
        },
        # Required when check_type == "semantic"
        "rubric": {"type": "string", "maxLength": 400},
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
