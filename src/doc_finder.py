"""Discover documentation files in a GitHub repository."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github.Repository import Repository

DOC_EXTENSIONS = {".md", ".rst", ".txt"}
SKIP_DIRS = {"node_modules", ".git", "vendor", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_FILES = 30
MAX_TOTAL_BYTES = 200 * 1024  # 200 KB


def find_docs(repo: "Repository", docs_path: str = "") -> list[dict]:
    """Return a list of {path, content} dicts for doc files in the repo.

    Args:
        repo: PyGithub Repository object.
        docs_path: Optional subdirectory to restrict search to.

    Returns:
        List of dicts with keys 'path' and 'content'.
    """
    root = docs_path.strip("/") if docs_path else ""
    all_files = _collect_files(repo, root)

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


def _collect_files(repo: "Repository", root: str) -> list[str]:
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
                results.append(item.path)

    return sorted(results)
