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

        with patch.object(doc_finder, "_collect_files", return_value=[]) as mock_collect:
            doc_finder.find_docs(repo, "docs/")

        mock_collect.assert_called_once_with(repo, "docs")

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
