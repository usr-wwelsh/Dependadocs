"""Discover documentation files in a GitHub repository."""

from __future__ import annotations

import fnmatch
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github.Repository import Repository

DOC_EXTENSIONS = {".md", ".rst", ".txt"}
SKIP_DIRS = {"node_modules", ".git", "vendor", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_FILES = 30
MAX_TOTAL_BYTES = 200 * 1024  # 200 KB


def find_docs(repo: "Repository", docs_path: str = "", diff: str = "") -> list[dict]:
    """Return a list of {path, content} dicts for doc files in the repo.

    Args:
        repo: PyGithub Repository object.
        docs_path: Optional subdirectory to restrict search to.
        diff: Optional unified diff string used to rank docs by relevance.

    Returns:
        List of dicts with keys 'path' and 'content'.
    """
    root = docs_path.strip("/") if docs_path else ""
    ignore_patterns = _load_ignore_patterns(repo)
    all_files = _collect_files(repo, root, ignore_patterns)

    if diff:
        changed_paths = _extract_changed_paths(diff)
        keywords = _keywords_from_paths(changed_paths)
        if keywords:
            all_files = sorted(all_files, key=lambda p: _score_path(p, keywords), reverse=True)

    docs: list[dict] = []
    total_bytes = 0
    truncated = False

    for file_path in all_files:
        if len(docs) >= MAX_FILES:
            truncated = True
            break

        try:
            content_file = repo.get_contents(file_path)
            # content_file may be a list if it's a directory (shouldn't happen here)
            if isinstance(content_file, list):
                continue
            decoded = content_file.decoded_content.decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"[dependadocs] Warning: could not read {file_path}: {exc}")
            continue

        file_bytes = len(decoded.encode("utf-8"))
        if total_bytes + file_bytes > MAX_TOTAL_BYTES:
            truncated = True
            break

        docs.append({"path": file_path, "content": decoded})
        total_bytes += file_bytes

    if truncated:
        print(
            f"[dependadocs] Warning: doc discovery truncated at {len(docs)} files / "
            f"{total_bytes // 1024} KB. Set docs-path to narrow the scope."
        )

    print(f"[dependadocs] Found {len(docs)} doc file(s) for review.")
    return docs


def _load_ignore_patterns(repo) -> list[str]:
    """Load exclusion patterns from .docignore at the repo root."""
    try:
        contents = repo.get_contents(".docignore")
        if isinstance(contents, list):
            return []
        text = contents.decoded_content.decode("utf-8", errors="replace")
        patterns = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return patterns
    except Exception:
        return []


def _matches_ignore(path: str, patterns: list[str]) -> bool:
    """Return True if path matches any ignore pattern."""
    for pattern in patterns:
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            if dir_name in path.split("/")[:-1]:
                return True
        elif "/" not in pattern:
            if fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        else:
            if fnmatch.fnmatch(path, pattern):
                return True
    return False


def _collect_files(
    repo: "Repository", root: str, ignore_patterns: list[str] | None = None
) -> list[str]:
    """Recursively collect doc file paths under root."""
    results: list[str] = []
    try:
        contents = repo.get_contents(root or "/")
    except Exception as exc:
        print(f"[dependadocs] Warning: could not list {root or '/'}: {exc}")
        return results

    if not isinstance(contents, list):
        contents = [contents]

    stack = list(contents)
    while stack:
        item = stack.pop()
        # Skip unwanted directories
        parts = item.path.split("/")
        if any(part in SKIP_DIRS for part in parts):
            continue

        if item.type == "dir":
            try:
                children = repo.get_contents(item.path)
                if isinstance(children, list):
                    stack.extend(children)
                else:
                    stack.append(children)
            except Exception as exc:
                print(f"[dependadocs] Warning: could not list {item.path}: {exc}")
        elif item.type == "file":
            _, ext = os.path.splitext(item.name.lower())
            if ext in DOC_EXTENSIONS:
                if ignore_patterns and _matches_ignore(item.path, ignore_patterns):
                    continue
                results.append(item.path)

    return sorted(results)


def _extract_changed_paths(diff: str) -> set[str]:
    """Parse unified diff and return the set of changed file paths."""
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            path = line[6:]
            if path != "/dev/null":
                paths.add(path)
    return paths


def _keywords_from_paths(paths: set[str]) -> set[str]:
    """Extract lowercase stem keywords from a set of file paths."""
    keywords: set[str] = set()
    for path in paths:
        for component in path.split("/"):
            stem = os.path.splitext(component)[0].lower()
            if len(stem) > 2:
                keywords.add(stem)
    return keywords


def _score_path(doc_path: str, keywords: set[str]) -> int:
    """Score a doc path by how many keywords appear in it."""
    lowered = doc_path.lower()
    doc_stems = {os.path.splitext(p)[0].lower() for p in doc_path.split("/")}
    score = 0
    for kw in keywords:
        if kw in lowered:
            score += 1
            if kw in doc_stems:
                score += 1
    return score
