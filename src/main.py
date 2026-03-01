"""Dependadocs orchestrator — entry point for the GitHub Action."""

from __future__ import annotations

import datetime
import json
import os
import sys

# Ensure src/ is on the path so sibling modules resolve correctly.
sys.path.insert(0, os.path.dirname(__file__))

import gemini_client
import github_client
from doc_finder import find_docs


def main() -> None:
    # ── Read GitHub event context ─────────────────────────────────────────
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")

    if not event_path:
        _die("GITHUB_EVENT_PATH is not set. Are you running inside GitHub Actions?")

    try:
        with open(event_path) as fh:
            event = json.load(fh)
    except Exception as exc:
        _die(f"Could not read event file at {event_path}: {exc}")

    repo_full_name: str = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo_full_name:
        _die("GITHUB_REPOSITORY is not set.")

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        _die("GITHUB_TOKEN is not set.")

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_api_key:
        _die("GEMINI_API_KEY is not set.")

    docs_path = os.environ.get("DOCS_PATH", "").strip()
    lookback_days = int(os.environ.get("LOOKBACK_DAYS", "7"))

    # ── Initialise GitHub client ──────────────────────────────────────────
    gh = github_client.get_github_client(token)
    repo = gh.get_repo(repo_full_name)

    # ── Route by event type ───────────────────────────────────────────────
    if event_name == "pull_request":
        _handle_pull_request(event, repo, docs_path)
    elif event_name == "push":
        _handle_push(event, repo, docs_path)
    elif event_name in ("schedule", "workflow_dispatch"):
        _handle_scheduled(repo, docs_path, lookback_days)
    else:
        _die(
            f"Unsupported event type: '{event_name}'. "
            "Dependadocs supports: pull_request, push, schedule, workflow_dispatch."
        )


def _handle_pull_request(event: dict, repo, docs_path: str) -> None:
    pull_request = event.get("pull_request")
    if not pull_request:
        _die("pull_request event is missing 'pull_request' data.")

    pr_number: int = pull_request["number"]
    base_ref: str = pull_request["base"]["ref"]
    trigger_pr_url: str = pull_request.get("html_url", "")
    head_ref: str = pull_request.get("head", {}).get("ref", "")

    if head_ref.startswith("dependadocs/"):
        print("[dependadocs] PR is from a Dependadocs branch — skipping to avoid loops.")
        sys.exit(0)

    print(f"[dependadocs] Processing PR #{pr_number} (base: {base_ref})")

    diff = github_client.get_pr_diff(repo, pr_number)
    if not diff.strip():
        print("[dependadocs] PR has no diff. Exiting.")
        sys.exit(0)

    docs = find_docs(repo, docs_path, diff=diff)
    result = _analyze(diff, docs)

    if not result.updates_needed or not result.changes:
        print("[dependadocs] No documentation updates needed. All good!")
        sys.exit(0)

    _log_changes(result.changes)
    pr_url = _create_pr(
        repo=repo,
        base_ref=base_ref,
        changes=result.changes,
        branch_suffix=f"pr-{pr_number}",
        pr_title=f"docs: update documentation for PR #{pr_number}",
        trigger_description=f"in response to {trigger_pr_url or f'PR #{pr_number}'}",
    )
    print(f"[dependadocs] Documentation PR opened: {pr_url}")


def _handle_push(event: dict, repo, docs_path: str) -> None:
    before_sha: str = event.get("before", "")
    after_sha: str = event.get("after", "")
    ref: str = event.get("ref", "")
    base_ref = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref

    if not before_sha or not after_sha:
        _die("push event is missing 'before' or 'after' SHA.")

    # GitHub sends all-zeros SHA for the initial push to a new branch
    if before_sha == "0" * 40:
        print("[dependadocs] Initial push to new branch — no base to diff against. Exiting.")
        sys.exit(0)

    print(f"[dependadocs] Processing push {before_sha[:7]}..{after_sha[:7]} on {base_ref}")

    diff = github_client.get_commit_diff(repo, before_sha, after_sha)
    if not diff.strip():
        print("[dependadocs] Push has no diff. Exiting.")
        sys.exit(0)

    docs = find_docs(repo, docs_path, diff=diff)
    result = _analyze(diff, docs)

    if not result.updates_needed or not result.changes:
        print("[dependadocs] No documentation updates needed. All good!")
        sys.exit(0)

    _log_changes(result.changes)
    short_sha = after_sha[:7]
    pr_url = _create_pr(
        repo=repo,
        base_ref=base_ref,
        changes=result.changes,
        branch_suffix=f"push-{short_sha}",
        pr_title=f"docs: update documentation (push {short_sha})",
        trigger_description=f"in response to push `{short_sha}` on `{base_ref}`",
    )
    print(f"[dependadocs] Documentation PR opened: {pr_url}")


def _handle_scheduled(repo, docs_path: str, lookback_days: int = 7) -> None:
    default_branch = repo.default_branch
    print(f"[dependadocs] Scheduled/manual run on {default_branch}")

    diff, head_sha = github_client.get_scheduled_diff(repo, default_branch, lookback_days)

    if not diff.strip():
        print("[dependadocs] No changes since last run. Exiting.")
        sys.exit(0)

    docs = find_docs(repo, docs_path, diff=diff)
    result = _analyze(diff, docs)

    if not result.updates_needed or not result.changes:
        print("[dependadocs] No documentation updates needed. All good!")
        sys.exit(0)

    _log_changes(result.changes)
    date_str = datetime.date.today().isoformat()
    pr_url = _create_pr(
        repo=repo,
        base_ref=default_branch,
        changes=result.changes,
        branch_suffix=f"scheduled-{date_str}",
        pr_title=f"docs: update documentation ({date_str})",
        trigger_description=f"by a scheduled run on {date_str}",
    )
    print(f"[dependadocs] Documentation PR opened: {pr_url}")


def _analyze(diff: str, docs: list[dict]):
    print("[dependadocs] Sending diff + docs to Gemini for analysis…")
    try:
        result = gemini_client.analyze(diff, docs)
    except Exception as exc:
        _die(f"Gemini analysis failed: {exc}")
    print(f"[dependadocs] Summary: {result.summary}")
    return result


def _create_pr(repo, base_ref, changes, branch_suffix, pr_title, trigger_description):
    print("[dependadocs] Creating documentation PR…")
    try:
        return github_client.create_doc_pr(
            repo=repo,
            base_ref=base_ref,
            changes=changes,
            branch_suffix=branch_suffix,
            pr_title=pr_title,
            trigger_description=trigger_description,
        )
    except Exception as exc:
        _die(f"Failed to create doc PR: {exc}")


def _log_changes(changes) -> None:
    print(f"[dependadocs] {len(changes)} file(s) need updating:")
    for change in changes:
        print(f"  - {change.file}: {change.reason}")


def _die(message: str) -> None:
    print(f"[dependadocs] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
