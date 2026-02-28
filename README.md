# Dependadocs

**Dependabot for your documentation.** Dependadocs runs inside GitHub Actions and automatically opens a PR with AI-generated documentation updates whenever a code PR changes something that makes your docs stale.

- **Zero infrastructure** — pure GitHub Actions, no servers
- **BYOK** — bring your own Gemini API key (free tier works)
- **Human-in-the-loop** — always opens a separate PR for review; never auto-merges
- **Conservative** — only flags factually incorrect docs (renamed APIs, changed flags, etc.), ignores style/typos

---

## How it works

```
Your PR opened/updated
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

permissions:
  contents: write
  pull-requests: write

jobs:
  dependadocs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: wwelsh/dependadocs@v1
        with:
          gemini-api-key: ${{ secrets.GEMINI_API_KEY }}
```

That's it. The next time someone opens a PR, Dependadocs will run.

---

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `gemini-api-key` | Yes | — | Your Gemini API key |
| `docs-path` | No | `""` (whole repo) | Restrict doc discovery to a subdirectory, e.g. `"docs/"` |
| `github-token` | No | `${{ github.token }}` | Override the default GitHub token |

---

## What Gemini looks for

Dependadocs instructs Gemini to flag documentation that is **factually stale** due to code changes:

- Function or method renames
- Changed CLI flags or config keys
- Updated API signatures
- Removed or added features referenced in docs

It is explicitly told to **ignore** typos, grammar, and style improvements.

---

## Limits

To stay within Gemini's context window, Dependadocs caps discovery at **30 files** or **200 KB** of doc content, whichever comes first. If your repo is larger, set `docs-path` to point at the relevant subdirectory.

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
