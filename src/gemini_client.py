"""Gemini client — build prompt, call API, parse structured response."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "updates_needed": {"type": "BOOLEAN"},
        "summary": {"type": "STRING"},
        "changes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "file": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                    "updated_content": {"type": "STRING"},
                },
                "required": ["file", "reason", "updated_content"],
            },
        },
    },
    "required": ["updates_needed", "summary", "changes"],
}


@dataclass
class FileChange:
    file: str
    reason: str
    updated_content: str


@dataclass
class AnalysisResult:
    updates_needed: bool
    summary: str
    changes: list[FileChange] = field(default_factory=list)


def analyze(diff: str, docs: list[dict]) -> AnalysisResult:
    """Send diff + docs to Gemini and return structured analysis.

    Args:
        diff: Unified diff string from the pull request.
        docs: List of {path, content} dicts for existing doc files.

    Returns:
        AnalysisResult with update decisions.
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_prompt(diff, docs)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )

    return _parse_response(response.text)


def _build_prompt(diff: str, docs: list[dict]) -> str:
    docs_section = ""
    if docs:
        parts = []
        for doc in docs:
            parts.append(f"### {doc['path']}\n```\n{doc['content']}\n```")
        docs_section = "\n\n".join(parts)
    else:
        docs_section = "(no documentation files found in this repository)"

    return f"""You are a documentation maintainer. A pull request has introduced code changes.
Your job is to identify which documentation files are **factually stale** as a result.

Rules:
- Only flag docs that contain **factual errors** caused by the code change: renamed APIs,
  changed CLI flags, updated config keys, modified function signatures, removed features.
- Do NOT fix typos, grammar, or style issues.
- Do NOT flag docs that are still accurate.
- If a doc file needs updating, return its **complete updated content** (not a diff).
  Preserve the exact file structure: every blank line, every newline, every heading.
  The `updated_content` field must be the full file exactly as it should be written to disk.
- Be conservative — when in doubt, omit. A false negative is better than a false positive.
- If no docs need updating, set updates_needed to false and return an empty changes array.

## Pull Request Diff

```diff
{diff}
```

## Existing Documentation

{docs_section}

Respond with JSON matching the provided schema.
"""


def _parse_response(text: str) -> AnalysisResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON: {exc}\nRaw response:\n{text}") from exc

    changes = [
        FileChange(
            file=c["file"],
            reason=c["reason"],
            updated_content=c["updated_content"].replace("\\n", "\n"),
        )
        for c in data.get("changes", [])
    ]

    return AnalysisResult(
        updates_needed=bool(data.get("updates_needed", False)),
        summary=data.get("summary", ""),
        changes=changes,
    )
