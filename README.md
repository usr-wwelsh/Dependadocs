# Dependadocs

**Dependabot for your documentation.** Dependadocs runs inside GitHub Actions and automatically opens a PR with AI-generated documentation updates whenever a code PR changes something that makes your docs stale.

- **Zero infrastructure** — pure GitHub Actions, no servers
- **BYOK** — bring your own Gemini API key (free tier works)
- **Human-in-the-loop** — always opens a separate PR for review; never auto-merges
- **Conservative** — only flags factually incorrect docs (renamed APIs, changed flags, etc.), ignores style/typos

---

## How it works

```
Your PR opened/updated, or on schedule, or manually triggered
  → fetch diff via GitHub API
  → discover .md / .rst / .txt files in your repo
  → send diff + docs to Gemini 2.5 Flash
  → if docs are stale:
      open a new PR  →  dependadocs/pr-{number}  →  targeting your base branch
  → if docs look fine:
      exit cleanly, no PR opened
```

---

## Quick start

### 1. Add your Gemini API key as a secret

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Name: `GEMINI_API_KEY`
Value: your key from [Google AI Studio](https://aistudio.google.com/app/apikey)

### 2. Create the workflow file

`.github/workflows/dependadocs.yml`:

```yaml
on:
  pull_request:
    types: [opened, synchronize]
  schedule:
    - cron: '0 9 * * 1'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  dependadocs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: usr-wwelsh/dependadocs@main
        with:
          gemini-api-key: ${{ secrets.GEMINI_API_KEY }}
```

### 3. Allow Actions to open pull requests

In your repo: **Settings → Actions → General → Workflow permissions**

Enable **"Allow GitHub Actions to create and approve pull requests"**.

That's it. The next time someone opens a PR, Dependadocs will run.

---

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `gemini-api-key` | Yes | — | Your Gemini API key |
| `docs-path` | No | `""` (whole repo) | Restrict doc discovery to a subdirectory, e.g. `"docs/"` |
| `github-token` | No | `${{ github.token }}` | Override the default GitHub token |
| `lookback-days` | No | `7` | Number of days of commits to diff on scheduled/manual runs |

---

## What Gemini looks for

Dependadocs instructs Gemini to flag documentation that is **factually stale** due to code changes:

- Function or method renames
- Changed CLI flags or config keys
- Updated API signatures
- Removed or added features referenced in docs

It is explicitly told to **ignore** typos, grammar, and style improvements.

---

## Ignoring files

You can exclude files from Dependadocs by creating a `.docignore` file in your repo root. Each line is a glob pattern — files matching any pattern will be skipped.

```
# Example .docignore
CHANGELOG.md
ADR/
docs/internal/*
*.generated.md
```

Patterns with a trailing `/` match any file inside that directory (e.g. `ADR/` excludes all files under `ADR/`). Patterns without a `/` match by filename anywhere in the repo.

---

## Permissions

The workflow needs:

```yaml
permissions:
  contents: write       # create branches + commit files
  pull-requests: write  # open the doc-update PR
```

---

## Development

```bash
pip install -r requirements.txt pytest pytest-mock ruff
pytest tests/ -v
ruff check src/ tests/
```

---

## License

MIT
