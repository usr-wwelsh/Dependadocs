"""Unit tests for doc_finder.py."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch

import doc_finder


def _make_file(path: str, content: str = "# Doc") -> MagicMock:
    f = MagicMock()
    f.path = path
    f.name = os.path.basename(path)
    f.type = "file"
    f.decoded_content = content.encode("utf-8")
    return f


def _make_dir(path: str) -> MagicMock:
    d = MagicMock()
    d.path = path
    d.name = os.path.basename(path)
    d.type = "dir"
    return d


class TestCollectFiles:
    def test_finds_markdown_files(self):
        repo = MagicMock()
        readme = _make_file("README.md")
        repo.get_contents.return_value = [readme]

        result = doc_finder._collect_files(repo, "")
        assert "README.md" in result

    def test_skips_non_doc_extensions(self):
        repo = MagicMock()
        py_file = _make_file("main.py")
        repo.get_contents.return_value = [py_file]

        result = doc_finder._collect_files(repo, "")
        assert "main.py" not in result

    def test_skips_node_modules(self):
        repo = MagicMock()
        nm_file = _make_file("node_modules/pkg/README.md")
        repo.get_contents.return_value = [nm_file]

        result = doc_finder._collect_files(repo, "")
        assert "node_modules/pkg/README.md" not in result

    def test_recurses_into_subdirectory(self):
        repo = MagicMock()
        docs_dir = _make_dir("docs")
        docs_file = _make_file("docs/guide.md")

        def get_contents(path):
            if path in ("", "/"):
                return [docs_dir]
            if path == "docs":
                return [docs_file]
            return []

        repo.get_contents.side_effect = get_contents

        result = doc_finder._collect_files(repo, "")
        assert "docs/guide.md" in result

    def test_includes_rst_and_txt(self):
        repo = MagicMock()
        rst = _make_file("docs/api.rst")
        txt = _make_file("CHANGELOG.txt")
        repo.get_contents.return_value = [rst, txt]

        result = doc_finder._collect_files(repo, "")
        assert "docs/api.rst" in result
        assert "CHANGELOG.txt" in result


class TestFindDocs:
    def test_returns_path_and_content(self):
        repo = MagicMock()
        readme = _make_file("README.md", "# Hello")
        content_obj = MagicMock()
        content_obj.decoded_content = b"# Hello"

        repo.get_contents.side_effect = lambda path, **kw: (
            [readme] if path in ("", "/") else content_obj
        )

        with patch.object(doc_finder, "_collect_files", return_value=["README.md"]):
            docs = doc_finder.find_docs(repo, "")

        assert len(docs) == 1
        assert docs[0]["path"] == "README.md"
        assert "Hello" in docs[0]["content"]

    def test_truncates_at_max_files(self):
        repo = MagicMock()
        paths = [f"doc{i}.md" for i in range(doc_finder.MAX_FILES + 5)]

        def fake_get_contents(path, **kw):
            obj = MagicMock()
            obj.decoded_content = b"x" * 10
            return obj

        repo.get_contents.side_effect = fake_get_contents

        with patch.object(doc_finder, "_collect_files", return_value=paths):
            docs = doc_finder.find_docs(repo, "")

        assert len(docs) == doc_finder.MAX_FILES

    def test_respects_docs_path(self):
        repo = MagicMock()

        with patch.object(doc_finder, "_load_ignore_patterns", return_value=[]):
            with patch.object(doc_finder, "_collect_files", return_value=[]) as mock_collect:
                doc_finder.find_docs(repo, "docs/")

        mock_collect.assert_called_once_with(repo, "docs", [])

    def test_empty_repo_returns_empty_list(self):
        repo = MagicMock()
        repo.get_contents.return_value = []

        docs = doc_finder.find_docs(repo, "")
        assert docs == []

    def test_skips_file_when_read_raises(self):
        repo = MagicMock()
        repo.get_contents.side_effect = Exception("network error")

        with patch.object(doc_finder, "_collect_files", return_value=["README.md"]):
            docs = doc_finder.find_docs(repo, "")

        assert docs == []

    def test_skips_when_get_contents_returns_list(self):
        # get_contents returning a list signals a directory — should be skipped
        repo = MagicMock()
        repo.get_contents.return_value = [MagicMock(), MagicMock()]

        with patch.object(doc_finder, "_collect_files", return_value=["README.md"]):
            docs = doc_finder.find_docs(repo, "")

        assert docs == []

    def test_truncates_when_total_size_exceeded(self):
        repo = MagicMock()
        # Each file is just over half the limit so the second one pushes over
        big_content = b"x" * (doc_finder.MAX_TOTAL_BYTES // 2 + 1)

        call_count = 0

        def fake_get_contents(path, **kw):
            nonlocal call_count
            call_count += 1
            obj = MagicMock()
            obj.decoded_content = big_content
            return obj

        repo.get_contents.side_effect = fake_get_contents

        with patch.object(doc_finder, "_collect_files", return_value=["a.md", "b.md", "c.md"]):
            docs = doc_finder.find_docs(repo, "")

        # Only the first file fits; second exceeds the byte cap
        assert len(docs) == 1

    def test_collect_files_returns_empty_on_api_error(self):
        from github import GithubException
        repo = MagicMock()
        repo.get_contents.side_effect = GithubException(403, "forbidden")

        result = doc_finder._collect_files(repo, "")
        assert result == []

    def test_collect_files_single_item_not_list(self):
        # get_contents may return a single object instead of a list
        repo = MagicMock()
        single = _make_file("README.md")
        repo.get_contents.return_value = single  # not a list

        result = doc_finder._collect_files(repo, "")
        assert "README.md" in result

    def test_collect_files_handles_dir_read_error(self):
        from github import GithubException
        repo = MagicMock()
        subdir = _make_dir("docs")

        def get_contents(path):
            if path in ("", "/"):
                return [subdir]
            raise GithubException(500, "server error")

        repo.get_contents.side_effect = get_contents

        result = doc_finder._collect_files(repo, "")
        assert result == []


class TestLoadIgnorePatterns:
    def test_reads_docignore(self):
        repo = MagicMock()
        contents = MagicMock()
        contents.decoded_content = b"# Keep these untouched\nCHANGELOG.md\n\nADR/\n"
        repo.get_contents.return_value = contents

        result = doc_finder._load_ignore_patterns(repo)
        assert result == ["CHANGELOG.md", "ADR/"]

    def test_returns_empty_when_missing(self):
        from github import GithubException
        repo = MagicMock()
        repo.get_contents.side_effect = GithubException(404, "not found")

        result = doc_finder._load_ignore_patterns(repo)
        assert result == []

    def test_strips_whitespace(self):
        repo = MagicMock()
        contents = MagicMock()
        contents.decoded_content = b"  CHANGELOG.md  \n  ADR/  \n"
        repo.get_contents.return_value = contents

        result = doc_finder._load_ignore_patterns(repo)
        assert result == ["CHANGELOG.md", "ADR/"]


class TestMatchesIgnore:
    def test_filename_pattern(self):
        assert doc_finder._matches_ignore("docs/releases/CHANGELOG.md", ["CHANGELOG.md"]) is True

    def test_filename_pattern_no_false_positive(self):
        assert doc_finder._matches_ignore("docs/api.md", ["CHANGELOG.md"]) is False

    def test_directory_pattern(self):
        assert doc_finder._matches_ignore("docs/ADR/0001.md", ["ADR/"]) is True

    def test_directory_pattern_no_false_positive(self):
        # ADR.md is a filename, not inside an ADR directory
        assert doc_finder._matches_ignore("docs/ADR.md", ["ADR/"]) is False

    def test_glob_filename_pattern(self):
        assert doc_finder._matches_ignore("schema.generated.md", ["*.generated.md"]) is True

    def test_path_glob_pattern(self):
        assert doc_finder._matches_ignore("docs/internal/secrets.md", ["docs/internal/*"]) is True

    def test_path_glob_no_false_positive(self):
        assert doc_finder._matches_ignore("docs/public/guide.md", ["docs/internal/*"]) is False

    def test_empty_patterns(self):
        assert doc_finder._matches_ignore("README.md", []) is False


class TestCollectFilesWithIgnore:
    def test_skips_ignored_path(self):
        repo = MagicMock()
        changelog = _make_file("CHANGELOG.md")
        repo.get_contents.return_value = [changelog]

        result = doc_finder._collect_files(repo, "", ignore_patterns=["CHANGELOG.md"])
        assert "CHANGELOG.md" not in result

    def test_includes_non_ignored_path(self):
        repo = MagicMock()
        readme = _make_file("README.md")
        changelog = _make_file("CHANGELOG.md")
        repo.get_contents.return_value = [readme, changelog]

        result = doc_finder._collect_files(repo, "", ignore_patterns=["CHANGELOG.md"])
        assert "README.md" in result
        assert "CHANGELOG.md" not in result

    def test_no_ignore_patterns_unchanged(self):
        repo = MagicMock()
        readme = _make_file("README.md")
        repo.get_contents.return_value = [readme]

        result = doc_finder._collect_files(repo, "", ignore_patterns=None)
        assert "README.md" in result


class TestExtractChangedPaths:
    def test_parses_diff_paths(self):
        diff = "--- a/src/auth/login.py\n+++ b/src/auth/login.py\n@@ -1,3 +1,4 @@"
        result = doc_finder._extract_changed_paths(diff)
        assert "src/auth/login.py" in result

    def test_skips_dev_null(self):
        diff = "--- /dev/null\n+++ b/src/new_file.py\n@@ -0,0 +1 @@"
        result = doc_finder._extract_changed_paths(diff)
        assert "/dev/null" not in result
        assert "src/new_file.py" in result

    def test_empty_diff(self):
        result = doc_finder._extract_changed_paths("")
        assert result == set()

    def test_deduplicates(self):
        diff = "--- a/src/auth.py\n+++ b/src/auth.py\n@@ diff"
        result = doc_finder._extract_changed_paths(diff)
        assert result == {"src/auth.py"}


class TestKeywordsFromPaths:
    def test_splits_and_stems(self):
        result = doc_finder._keywords_from_paths({"src/auth/login.py"})
        assert "src" in result
        assert "auth" in result
        assert "login" in result

    def test_filters_short_tokens(self):
        result = doc_finder._keywords_from_paths({"a/b/c.py"})
        assert result == set()

    def test_lowercases(self):
        result = doc_finder._keywords_from_paths({"AuthService.py"})
        assert "authservice" in result

    def test_empty_set(self):
        result = doc_finder._keywords_from_paths(set())
        assert result == set()


class TestScorePath:
    def test_no_match_returns_zero(self):
        assert doc_finder._score_path("guide.md", {"auth"}) == 0

    def test_substring_match(self):
        # "auth" appears in "authentication.md" but is not the stem
        score = doc_finder._score_path("authentication.md", {"auth"})
        assert score == 1

    def test_exact_stem_match_bonus(self):
        # "auth" IS the stem of "auth.md" → extra point
        score = doc_finder._score_path("auth.md", {"auth"})
        assert score == 2

    def test_multiple_keywords(self):
        score = doc_finder._score_path("docs/auth/guide.md", {"auth", "guide"})
        # "auth": substring(1) + stem(1) = 2
        # "guide": substring(1) + stem(1) = 2
        assert score == 4

    def test_empty_keywords(self):
        assert doc_finder._score_path("README.md", set()) == 0


class TestFindDocsRanking:
    def _make_content_obj(self, content: str = "# Doc") -> MagicMock:
        obj = MagicMock()
        obj.decoded_content = content.encode("utf-8")
        return obj

    def test_ranks_by_relevance(self):
        repo = MagicMock()
        repo.get_contents.return_value = self._make_content_obj()
        diff = "--- a/src/auth/service.py\n+++ b/src/auth/service.py\n@@ diff"

        with patch.object(doc_finder, "_load_ignore_patterns", return_value=[]):
            with patch.object(doc_finder, "_collect_files", return_value=["guide.md", "auth.md"]):
                docs = doc_finder.find_docs(repo, "", diff=diff)

        paths = [d["path"] for d in docs]
        assert paths.index("auth.md") < paths.index("guide.md")

    def test_without_diff_preserves_alphabetical_order(self):
        repo = MagicMock()
        repo.get_contents.return_value = self._make_content_obj()

        with patch.object(doc_finder, "_load_ignore_patterns", return_value=[]):
            with patch.object(doc_finder, "_collect_files", return_value=["auth.md", "guide.md"]):
                docs = doc_finder.find_docs(repo, "", diff="")

        paths = [d["path"] for d in docs]
        assert paths == ["auth.md", "guide.md"]

    def test_with_diff_but_no_matching_keywords(self):
        repo = MagicMock()
        repo.get_contents.return_value = self._make_content_obj()
        # All path components are ≤2 chars → no keywords extracted → no re-sort
        diff = "--- a/x/y.py\n+++ b/x/y.py\n@@ diff"

        with patch.object(doc_finder, "_load_ignore_patterns", return_value=[]):
            with patch.object(doc_finder, "_collect_files", return_value=["guide.md", "auth.md"]):
                docs = doc_finder.find_docs(repo, "", diff=diff)

        paths = [d["path"] for d in docs]
        assert paths == ["guide.md", "auth.md"]
