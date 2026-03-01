"""Unit tests for main.py."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch
import pytest

import main
from gemini_client import AnalysisResult, FileChange


BASE_ENV = {
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_TOKEN": "fake-token",
    "GEMINI_API_KEY": "fake-key",
    "DOCS_PATH": "",
    "GITHUB_EVENT_NAME": "pull_request",
}


def _write_event(tmp_path: str, data: dict) -> str:
    path = os.path.join(tmp_path, "event.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _make_pr_event(pr_number: int = 1, base_ref: str = "main") -> dict:
    return {
        "pull_request": {
            "number": pr_number,
            "base": {"ref": base_ref},
            "html_url": f"https://github.com/owner/repo/pull/{pr_number}",
        }
    }


def _make_push_event(
    before: str = "abc1234" * 5 + "abcd",
    after: str = "def5678" * 5 + "defg",
    ref: str = "refs/heads/main",
) -> dict:
    return {"before": before, "after": after, "ref": ref}


def _make_schedule_event() -> dict:
    return {}


class TestMainPullRequest:
    def test_opens_doc_pr_when_updates_needed(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=7))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        mock_repo = MagicMock()
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo

        result = AnalysisResult(
            updates_needed=True,
            summary="README mentions old name",
            changes=[FileChange(file="README.md", reason="renamed", updated_content="# New")],
        )

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=mock_gh):
                with patch("main.github_client.get_pr_diff", return_value="--- a/x\n+++ b/x\n@@ diff"):
                    with patch("main.find_docs", return_value=[{"path": "README.md", "content": "old"}]):
                        with patch("main.gemini_client.analyze", return_value=result):
                            with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/8") as mock_create:
                                main.main()

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["branch_suffix"] == "pr-7"
        assert call_kwargs["base_ref"] == "main"

    def test_exits_cleanly_when_no_updates_needed(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event())
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        result = AnalysisResult(updates_needed=False, summary="All good", changes=[])

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=[]):
                        with patch("main.gemini_client.analyze", return_value=result):
                            with patch("main.github_client.create_doc_pr") as mock_create:
                                with pytest.raises(SystemExit) as exc_info:
                                    main.main()

        assert exc_info.value.code == 0
        mock_create.assert_not_called()

    def test_skips_dependadocs_own_prs(self, tmp_path):
        event = _make_pr_event()
        event["pull_request"]["head"] = {"ref": "dependadocs/pr-5"}
        event_path = _write_event(str(tmp_path), event)
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff") as mock_diff:
                    with pytest.raises(SystemExit) as exc_info:
                        main.main()

        assert exc_info.value.code == 0
        mock_diff.assert_not_called()

    def test_exits_cleanly_when_empty_diff(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event())
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="   "):
                    with patch("main.gemini_client.analyze") as mock_analyze:
                        with pytest.raises(SystemExit) as exc_info:
                            main.main()

        assert exc_info.value.code == 0
        mock_analyze.assert_not_called()


class TestMainPush:
    def test_opens_doc_pr_for_push(self, tmp_path):
        before = "a" * 40
        after = "b" * 40
        event_path = _write_event(str(tmp_path), _make_push_event(before=before, after=after))
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": event_path}

        result = AnalysisResult(
            updates_needed=True,
            summary="API changed",
            changes=[FileChange(file="docs/api.md", reason="new endpoint", updated_content="# API")],
        )

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_commit_diff", return_value="--- a/x\n+++ b/x") as mock_diff:
                    with patch("main.find_docs", return_value=[]):
                        with patch("main.gemini_client.analyze", return_value=result):
                            with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/9") as mock_create:
                                main.main()

        mock_diff.assert_called_once_with(mock_diff.call_args.args[0], before, after)
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["branch_suffix"] == f"push-{after[:7]}"

    def test_exits_cleanly_for_initial_push(self, tmp_path):
        event_path = _write_event(
            str(tmp_path),
            _make_push_event(before="0" * 40, after="b" * 40),
        )
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": event_path}

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_commit_diff") as mock_diff:
                    with pytest.raises(SystemExit) as exc_info:
                        main.main()

        assert exc_info.value.code == 0
        mock_diff.assert_not_called()

    def test_exits_cleanly_when_empty_diff(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_push_event())
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": event_path}

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_commit_diff", return_value=""):
                    with patch("main.gemini_client.analyze") as mock_analyze:
                        with pytest.raises(SystemExit) as exc_info:
                            main.main()

        assert exc_info.value.code == 0
        mock_analyze.assert_not_called()


class TestMainScheduled:
    def test_opens_doc_pr_for_scheduled_run(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_schedule_event())
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": event_path}

        mock_repo = MagicMock()
        mock_repo.default_branch = "main"
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo

        result = AnalysisResult(
            updates_needed=True,
            summary="Changes detected",
            changes=[FileChange(file="README.md", reason="updated", updated_content="# New")],
        )

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=mock_gh):
                with patch("main.github_client.get_scheduled_diff", return_value=("some diff", "abc1234")) as mock_diff:
                    with patch("main.find_docs", return_value=[]):
                        with patch("main.gemini_client.analyze", return_value=result):
                            with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/10") as mock_create:
                                main.main()

        mock_diff.assert_called_once()
        mock_create.assert_called_once()
        assert "scheduled-" in mock_create.call_args.kwargs["branch_suffix"]

    def test_exits_cleanly_when_no_diff(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_schedule_event())
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": event_path}

        mock_repo = MagicMock()
        mock_repo.default_branch = "main"
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=mock_gh):
                with patch("main.github_client.get_scheduled_diff", return_value=("", "abc1234")):
                    with pytest.raises(SystemExit) as exc_info:
                        main.main()

        assert exc_info.value.code == 0

    def test_workflow_dispatch_routes_to_scheduled(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_schedule_event())
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_EVENT_PATH": event_path}

        mock_repo = MagicMock()
        mock_repo.default_branch = "main"
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=mock_gh):
                with patch("main.github_client.get_scheduled_diff", return_value=("", "abc1234")) as mock_diff:
                    with pytest.raises(SystemExit):
                        main.main()

        mock_diff.assert_called_once()


class TestFindDocsCalledWithDiff:
    def test_pull_request_passes_diff(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=3))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}
        diff = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ -1,3 +1,4 @@"
        result = AnalysisResult(updates_needed=False, summary="OK", changes=[])

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value=diff):
                    with patch("main.find_docs", return_value=[]) as mock_find_docs:
                        with patch("main.gemini_client.analyze", return_value=result):
                            with pytest.raises(SystemExit):
                                main.main()

        mock_find_docs.assert_called_once()
        assert mock_find_docs.call_args.kwargs.get("diff") == diff

    def test_push_passes_diff(self, tmp_path):
        before = "a" * 40
        after = "b" * 40
        event_path = _write_event(str(tmp_path), _make_push_event(before=before, after=after))
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": event_path}
        diff = "--- a/src/api.py\n+++ b/src/api.py\n@@ -1 +1 @@"
        result = AnalysisResult(updates_needed=False, summary="OK", changes=[])

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_commit_diff", return_value=diff):
                    with patch("main.find_docs", return_value=[]) as mock_find_docs:
                        with patch("main.gemini_client.analyze", return_value=result):
                            with pytest.raises(SystemExit):
                                main.main()

        mock_find_docs.assert_called_once()
        assert mock_find_docs.call_args.kwargs.get("diff") == diff

    def test_scheduled_passes_diff(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_schedule_event())
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": event_path}
        mock_repo = MagicMock()
        mock_repo.default_branch = "main"
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        diff = "--- a/src/models.py\n+++ b/src/models.py\n@@ -1 +1 @@"
        result = AnalysisResult(updates_needed=False, summary="OK", changes=[])

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=mock_gh):
                with patch("main.github_client.get_scheduled_diff", return_value=(diff, "abc1234")):
                    with patch("main.find_docs", return_value=[]) as mock_find_docs:
                        with patch("main.gemini_client.analyze", return_value=result):
                            with pytest.raises(SystemExit):
                                main.main()

        mock_find_docs.assert_called_once()
        assert mock_find_docs.call_args.kwargs.get("diff") == diff


class TestReadmeFallback:
    """Tests for _analyze_with_readme_fallback logic."""

    def test_readme_fallback_triggered_when_readme_not_in_primary_changes(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=1))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        primary_result = AnalysisResult(updates_needed=False, summary="no changes", changes=[])
        readme_result = AnalysisResult(
            updates_needed=True,
            summary="README wrong",
            changes=[FileChange(file="README.md", reason="wrong cmd", updated_content="# Fixed")],
        )
        readme_docs = [{"path": "README.md", "content": "old content"}]

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=readme_docs):
                        with patch("main.gemini_client.analyze", return_value=primary_result):
                            with patch("main.gemini_client.analyze_readme", return_value=readme_result) as mock_readme:
                                with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/2"):
                                    main.main()

        mock_readme.assert_called_once()

    def test_readme_fallback_not_triggered_when_readme_already_updated(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=1))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        primary_result = AnalysisResult(
            updates_needed=True,
            summary="readme updated",
            changes=[FileChange(file="README.md", reason="renamed", updated_content="# New")],
        )
        readme_docs = [{"path": "README.md", "content": "old content"}]

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=readme_docs):
                        with patch("main.gemini_client.analyze", return_value=primary_result):
                            with patch("main.gemini_client.analyze_readme") as mock_readme:
                                with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/2"):
                                    main.main()

        mock_readme.assert_not_called()

    def test_readme_fallback_not_triggered_when_no_readme_in_docs(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=1))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        primary_result = AnalysisResult(updates_needed=False, summary="ok", changes=[])

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=[{"path": "docs/guide.md", "content": "guide"}]):
                        with patch("main.gemini_client.analyze", return_value=primary_result):
                            with patch("main.gemini_client.analyze_readme") as mock_readme:
                                with pytest.raises(SystemExit):
                                    main.main()

        mock_readme.assert_not_called()

    def test_readme_fallback_failure_is_nonfatal(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=1))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        primary_result = AnalysisResult(updates_needed=False, summary="ok", changes=[])
        readme_docs = [{"path": "README.md", "content": "content"}]

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=readme_docs):
                        with patch("main.gemini_client.analyze", return_value=primary_result):
                            with patch("main.gemini_client.analyze_readme", side_effect=RuntimeError("API down")):
                                with pytest.raises(SystemExit) as exc_info:
                                    main.main()

        # Should exit 0 (no updates), not 1 (error)
        assert exc_info.value.code == 0

    def test_readme_fallback_changes_merged_into_result(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event(pr_number=1))
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        primary_result = AnalysisResult(
            updates_needed=True,
            summary="other doc changed",
            changes=[FileChange(file="docs/api.md", reason="endpoint removed", updated_content="# API")],
        )
        readme_result = AnalysisResult(
            updates_needed=True,
            summary="README wrong",
            changes=[FileChange(file="README.md", reason="wrong cmd", updated_content="# Fixed")],
        )
        docs = [
            {"path": "README.md", "content": "old"},
            {"path": "docs/api.md", "content": "api"},
        ]

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=docs):
                        with patch("main.gemini_client.analyze", return_value=primary_result):
                            with patch("main.gemini_client.analyze_readme", return_value=readme_result):
                                with patch("main.github_client.create_doc_pr", return_value="https://github.com/owner/repo/pull/2") as mock_create:
                                    main.main()

        mock_create.assert_called_once()
        call_changes = mock_create.call_args.kwargs["changes"]
        changed_files = {c.file for c in call_changes}
        assert "README.md" in changed_files
        assert "docs/api.md" in changed_files


class TestMainErrorHandling:
    def test_dies_when_event_path_missing(self):
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": ""}
        with patch.dict(os.environ, env):
            with pytest.raises(SystemExit) as exc_info:
                main.main()
        assert exc_info.value.code == 1

    def test_dies_when_unsupported_event(self, tmp_path):
        event_path = _write_event(str(tmp_path), {})
        env = {**BASE_ENV, "GITHUB_EVENT_NAME": "release", "GITHUB_EVENT_PATH": event_path}
        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with pytest.raises(SystemExit) as exc_info:
                    main.main()
        assert exc_info.value.code == 1

    def test_dies_when_github_token_missing(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event())
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path, "GITHUB_TOKEN": ""}
        with patch.dict(os.environ, env):
            with pytest.raises(SystemExit) as exc_info:
                main.main()
        assert exc_info.value.code == 1

    def test_dies_when_gemini_key_missing(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event())
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path, "GEMINI_API_KEY": ""}
        with patch.dict(os.environ, env):
            with pytest.raises(SystemExit) as exc_info:
                main.main()
        assert exc_info.value.code == 1

    def test_dies_when_gemini_raises(self, tmp_path):
        event_path = _write_event(str(tmp_path), _make_pr_event())
        env = {**BASE_ENV, "GITHUB_EVENT_PATH": event_path}

        with patch.dict(os.environ, env):
            with patch("main.github_client.get_github_client", return_value=MagicMock()):
                with patch("main.github_client.get_pr_diff", return_value="some diff"):
                    with patch("main.find_docs", return_value=[]):
                        with patch("main.gemini_client.analyze", side_effect=RuntimeError("API down")):
                            with pytest.raises(SystemExit) as exc_info:
                                main.main()

        assert exc_info.value.code == 1
