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


def analyze_docs_audit(docs: list[dict]) -> AnalysisResult:
    """Holistic docs audit with no diff context — for when there are no recent commits.

    Args:
        docs: List of {path, content} dicts for all doc files.

    Returns:
        AnalysisResult with any factual corrections needed.
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_docs_audit_prompt(docs)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            max_output_tokens=16384,
        ),
    )

    return _parse_response(response.text)


def analyze_readme(diff: str, readme_docs: list[dict]) -> AnalysisResult:
    """Secondary pass: check README files for correctness independent of the diff.

    Args:
        diff: Unified diff string (used as context only).
        readme_docs: List of {path, content} dicts for README files.

    Returns:
        AnalysisResult with any factual corrections needed.
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_readme_prompt(diff, readme_docs)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            max_output_tokens=16384,
        ),
    )

    return _parse_response(response.text)


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
            max_output_tokens=16384,
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
- Flag docs that contain **factual errors** caused by the code change: renamed APIs,
  changed CLI flags, updated config keys, modified function signatures, removed features.
- Also flag **incorrect names** already present in the docs: wrong filenames, misspelled
  command names, wrong flag names, or broken code examples — these are factual errors,
  not style issues.
- Do NOT fix prose typos, grammar, or style issues.
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


def _build_docs_audit_prompt(docs: list[dict]) -> str:
    docs_section = "\n\n".join(
        f"### {doc['path']}\n```\n{doc['content']}\n```" for doc in docs
    )

    return f"""You are a documentation auditor. There are no recent code changes to anchor on.

Review each documentation file below and identify any **factual errors**.

Ask yourself: do the commands, file paths, API names, feature descriptions, and code
examples accurately reflect how the project actually works?

Rules:
- Flag only genuine **factual errors**: wrong commands, outdated examples, incorrect
  filenames, broken code snippets, or features that don't match reality.
- Do NOT fix prose, grammar, or style.
- Do NOT flag missing documentation — only incorrect documentation.
- Be conservative — when in doubt, omit. A false negative is better than a false positive.
- If a doc needs updating, return its **complete updated content** (not a diff).
  Preserve exact file structure: every blank line, every newline, every heading.
- If all docs are correct, set updates_needed to false and return an empty changes array.

## Documentation Files

{docs_section}

Respond with JSON matching the provided schema.
"""


def _build_readme_prompt(diff: str, readme_docs: list[dict]) -> str:
    docs_section = "\n\n".join(
        f"### {doc['path']}\n```\n{doc['content']}\n```" for doc in readme_docs
    )

    return f"""You are a documentation reviewer. A code change was recently made (diff shown below).
The primary diff analysis did not flag any README updates, but READMEs are often overlooked.

Your job: review each README file and decide if it is **factually correct**.

Do NOT anchor only on what changed in the diff — review the README holistically.
Ask yourself: do the commands, file paths, API names, feature descriptions, and code
examples accurately reflect how the project actually works?

Rules:
- Flag only genuine **factual errors**: wrong commands, outdated examples, incorrect
  filenames, broken code snippets, or features that don't match reality.
- Do NOT fix prose, grammar, or style.
- Do NOT flag missing documentation — only incorrect documentation.
- Be conservative — when in doubt, omit. A false negative is better than a false positive.
- If a README needs updating, return its **complete updated content** (not a diff).
  Preserve exact file structure: every blank line, every newline, every heading.
- If the README is correct, set updates_needed to false and return an empty changes array.

## Recent Diff (for context)

```diff
{diff}
```

## README File(s) to Review

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
