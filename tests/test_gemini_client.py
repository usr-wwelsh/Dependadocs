"""Unit tests for gemini_client.py."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch
import pytest

import gemini_client


class TestParseResponse:
    def test_parses_updates_needed_true(self):
        payload = {
            "updates_needed": True,
            "summary": "README mentions old function name",
            "changes": [
                {
                    "file": "README.md",
                    "reason": "function renamed from foo to bar",
                    "updated_content": "# Updated docs",
                }
            ],
        }
        result = gemini_client._parse_response(json.dumps(payload))
        assert result.updates_needed is True
        assert result.summary == "README mentions old function name"
        assert len(result.changes) == 1
        assert result.changes[0].file == "README.md"
        assert result.changes[0].updated_content == "# Updated docs"

    def test_parses_updates_needed_false(self):
        payload = {
            "updates_needed": False,
            "summary": "No doc changes needed",
            "changes": [],
        }
        result = gemini_client._parse_response(json.dumps(payload))
        assert result.updates_needed is False
        assert result.changes == []

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            gemini_client._parse_response("not json {{{")

    def test_missing_changes_defaults_to_empty(self):
        payload = {"updates_needed": False, "summary": "ok"}
        result = gemini_client._parse_response(json.dumps(payload))
        assert result.changes == []


class TestBuildPrompt:
    def test_includes_diff(self):
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-def foo():\n+def bar():"
        docs = [{"path": "README.md", "content": "Call `foo()` to start."}]
        prompt = gemini_client._build_prompt(diff, docs)
        assert "def foo" in prompt
        assert "def bar" in prompt

    def test_includes_doc_content(self):
        diff = "some diff"
        docs = [{"path": "docs/guide.md", "content": "## Guide\nUse the API."}]
        prompt = gemini_client._build_prompt(diff, docs)
        assert "docs/guide.md" in prompt
        assert "Use the API" in prompt

    def test_handles_empty_docs(self):
        prompt = gemini_client._build_prompt("diff", [])
        assert "no documentation files found" in prompt

    def test_multiple_docs_all_included(self):
        docs = [
            {"path": "README.md", "content": "readme"},
            {"path": "docs/api.md", "content": "api reference"},
        ]
        prompt = gemini_client._build_prompt("diff", docs)
        assert "README.md" in prompt
        assert "docs/api.md" in prompt


class TestAnalyze:
    def test_calls_gemini_and_returns_result(self):
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "updates_needed": True,
                "summary": "test summary",
                "changes": [
                    {
                        "file": "README.md",
                        "reason": "renamed",
                        "updated_content": "new content",
                    }
                ],
            }
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            with patch("gemini_client.genai.Client", return_value=mock_client):
                result = gemini_client.analyze("some diff", [{"path": "README.md", "content": "old"}])

        assert result.updates_needed is True
        assert len(result.changes) == 1
        assert result.changes[0].file == "README.md"
