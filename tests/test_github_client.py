"""Unit tests for github_client.py."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, call
from github import GithubException

import github_client
from gemini_client import FileChange


def _make_pr_file(filename: str, patch_text: str = "@@ -1 +1 @@ change") -> MagicMock:
    f = MagicMock()
    f.filename = filename
    f.patch = patch_text
    return f


class TestGetPrDiff:
    def test_assembles_diff_from_files(self):
        repo = MagicMock()
        pr = MagicMock()
        pr.get_files.return_value = [
            _make_pr_file("src/main.py", "@@ -1 +1 @@ -def foo\n+def bar"),
        ]
        repo.get_pull.return_value = pr

        diff = github_client.get_pr_diff(repo, 42)
        assert "src/main.py" in diff
        assert "def foo" in diff

    def test_handles_binary_files(self):
        repo = MagicMock()
        pr = MagicMock()
        f = _make_pr_file("image.png", None)
        f.patch = None
        pr.get_files.return_value = [f]
        repo.get_pull.return_value = pr

        diff = github_client.get_pr_diff(repo, 1)
        assert "image.png" in diff
        assert "binary" in diff.lower()

    def test_empty_pr_returns_empty_string(self):
        repo = MagicMock()
        pr = MagicMock()
        pr.get_files.return_value = []
        repo.get_pull.return_value = pr

        diff = github_client.get_pr_diff(repo, 1)
        assert diff == ""


class TestGetCommitDiff:
    def test_assembles_diff_from_comparison(self):
        repo = MagicMock()
        comparison = MagicMock()
        f = MagicMock()
        f.filename = "src/app.py"
        f.patch = "@@ -1 +1 @@ -old\n+new"
        comparison.files = [f]
        repo.compare.return_value = comparison

        diff = github_client.get_commit_diff(repo, "abc1234", "def5678")

        repo.compare.assert_called_once_with("abc1234", "def5678")
        assert "src/app.py" in diff
        assert "-old" in diff

    def test_returns_empty_string_on_github_error(self):
        repo = MagicMock()
        repo.compare.side_effect = GithubException(422, "invalid range")

        diff = github_client.get_commit_diff(repo, "abc1234", "def5678")
        assert diff == ""

    def test_truncates_at_max_bytes(self, monkeypatch):
        monkeypatch.setattr(github_client, "MAX_DIFF_BYTES", 10)

        repo = MagicMock()
        comparison = MagicMock()
        f1 = MagicMock()
        f1.filename = "a.py"
        f1.patch = "x" * 20
        f2 = MagicMock()
        f2.filename = "b.py"
        f2.patch = "y" * 20
        comparison.files = [f1, f2]
        repo.compare.return_value = comparison

        diff = github_client.get_commit_diff(repo, "aaa", "bbb")
        assert "b.py" not in diff


class TestGetScheduledDiff:
    def test_uses_existing_tag_as_base(self):
        repo = MagicMock()
        tag_ref = MagicMock()
        tag_ref.object.sha = "tag_sha_1234567"
        tag_ref.object.type = "commit"
        repo.get_git_ref.return_value = tag_ref

        branch = MagicMock()
        branch.commit.sha = "head_sha_7654321"
        repo.get_branch.return_value = branch

        with MagicMock() as mock_diff:
            github_client.get_commit_diff = MagicMock(return_value="some diff")
            diff, head_sha = github_client.get_scheduled_diff(repo, "main")

        assert head_sha == "head_sha_7654321"
        github_client.get_commit_diff.assert_called_once_with(
            repo, "tag_sha_1234567", "head_sha_7654321"
        )

    def test_falls_back_to_last_50_commits_when_no_tag(self):
        repo = MagicMock()
        repo.get_git_ref.side_effect = GithubException(404, "not found")

        branch = MagicMock()
        branch.commit.sha = "head_sha"
        repo.get_branch.return_value = branch

        commits = [MagicMock() for _ in range(10)]
        for i, c in enumerate(commits):
            c.sha = f"sha_{i:04d}"
        repo.get_commits.return_value = commits

        github_client.get_commit_diff = MagicMock(return_value="fallback diff")
        diff, head_sha = github_client.get_scheduled_diff(repo, "main")

        assert head_sha == "head_sha"
        # Should use the oldest of the 10 commits as base
        github_client.get_commit_diff.assert_called_once_with(repo, commits[9].sha, "head_sha")

    def test_returns_empty_diff_when_no_new_commits(self):
        repo = MagicMock()
        tag_ref = MagicMock()
        tag_ref.object.sha = "same_sha"
        tag_ref.object.type = "commit"
        repo.get_git_ref.return_value = tag_ref

        branch = MagicMock()
        branch.commit.sha = "same_sha"
        repo.get_branch.return_value = branch

        diff, head_sha = github_client.get_scheduled_diff(repo, "main")
        assert diff == ""
        assert head_sha == "same_sha"

    def test_returns_empty_when_fewer_than_two_commits(self):
        repo = MagicMock()
        repo.get_git_ref.side_effect = GithubException(404, "not found")

        branch = MagicMock()
        branch.commit.sha = "only_sha"
        repo.get_branch.return_value = branch

        single_commit = MagicMock()
        single_commit.sha = "only_sha"
        repo.get_commits.return_value = [single_commit]

        diff, head_sha = github_client.get_scheduled_diff(repo, "main")
        assert diff == ""


class TestUpdateLastRunTag:
    def test_creates_tag_when_missing(self):
        repo = MagicMock()
        repo.get_git_ref.side_effect = GithubException(404, "not found")

        github_client.update_last_run_tag(repo, "abc1234")

        repo.create_git_ref.assert_called_once_with(
            ref="refs/tags/dependadocs-last-run", sha="abc1234"
        )

    def test_updates_existing_tag(self):
        repo = MagicMock()
        ref = MagicMock()
        repo.get_git_ref.return_value = ref

        github_client.update_last_run_tag(repo, "newsha")

        ref.edit.assert_called_once_with(sha="newsha", force=True)


class TestEnsureBranch:
    def test_creates_new_branch_when_missing(self):
        repo = MagicMock()
        repo.get_git_ref.side_effect = GithubException(404, "not found")

        github_client._ensure_branch(repo, "dependadocs/pr-1", "abc123")

        repo.create_git_ref.assert_called_once_with(
            ref="refs/heads/dependadocs/pr-1", sha="abc123"
        )

    def test_resets_existing_branch(self):
        repo = MagicMock()
        ref = MagicMock()
        repo.get_git_ref.return_value = ref

        github_client._ensure_branch(repo, "dependadocs/pr-1", "newsha")

        ref.edit.assert_called_once_with(sha="newsha", force=True)


class TestUpsertFile:
    def test_updates_existing_file(self):
        repo = MagicMock()
        existing = MagicMock()
        existing.sha = "oldsha"
        repo.get_contents.return_value = existing

        change = FileChange(file="README.md", reason="updated API name", updated_content="# New")
        github_client._upsert_file(repo, "dependadocs/pr-1", change)

        repo.update_file.assert_called_once()
        call_kwargs = repo.update_file.call_args
        assert call_kwargs.kwargs["path"] == "README.md" or call_kwargs.args[0] == "README.md"

    def test_creates_new_file_when_missing(self):
        repo = MagicMock()
        repo.get_contents.side_effect = GithubException(404, "not found")

        change = FileChange(file="docs/new.md", reason="new page", updated_content="# New Page")
        github_client._upsert_file(repo, "dependadocs/pr-1", change)

        repo.create_file.assert_called_once()


class TestCreateDocPr:
    def test_opens_pr_with_correct_metadata(self):
        repo = MagicMock()
        branch_obj = MagicMock()
        branch_obj.commit.sha = "base_sha"
        repo.get_branch.return_value = branch_obj
        repo.get_git_ref.side_effect = GithubException(404, "not found")

        existing = MagicMock()
        existing.sha = "filsha"
        repo.get_contents.return_value = existing

        created_pr = MagicMock()
        created_pr.html_url = "https://github.com/owner/repo/pull/2"
        repo.create_pull.return_value = created_pr
        repo.get_label.side_effect = GithubException(404, "no label")

        changes = [FileChange(file="README.md", reason="renamed function", updated_content="# Up")]
        url = github_client.create_doc_pr(
            repo=repo,
            base_ref="main",
            changes=changes,
            branch_suffix="pr-1",
            pr_title="docs: update documentation for PR #1",
            trigger_description="in response to https://github.com/owner/repo/pull/1",
        )

        assert url == "https://github.com/owner/repo/pull/2"
        repo.create_pull.assert_called_once()
        call_kwargs = repo.create_pull.call_args.kwargs
        assert call_kwargs["head"] == "dependadocs/pr-1"
        assert call_kwargs["base"] == "main"
        assert "PR #1" in call_kwargs["title"]

    def test_opens_pr_for_scheduled_run(self):
        repo = MagicMock()
        branch_obj = MagicMock()
        branch_obj.commit.sha = "base_sha"
        repo.get_branch.return_value = branch_obj
        repo.get_git_ref.side_effect = GithubException(404, "not found")
        repo.get_contents.return_value = MagicMock(sha="x")

        created_pr = MagicMock()
        created_pr.html_url = "https://github.com/owner/repo/pull/3"
        repo.create_pull.return_value = created_pr
        repo.get_label.side_effect = GithubException(404, "no label")

        changes = [FileChange(file="docs/guide.md", reason="updated", updated_content="# Guide")]
        url = github_client.create_doc_pr(
            repo=repo,
            base_ref="main",
            changes=changes,
            branch_suffix="scheduled-2026-02-27",
            pr_title="docs: update documentation (2026-02-27)",
            trigger_description="by a scheduled run on 2026-02-27",
        )

        assert url == "https://github.com/owner/repo/pull/3"
        call_kwargs = repo.create_pull.call_args.kwargs
        assert call_kwargs["head"] == "dependadocs/scheduled-2026-02-27"
        assert "2026-02-27" in call_kwargs["title"]
