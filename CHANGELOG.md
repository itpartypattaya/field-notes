# Changelog

## 2.0.1 — 2026-10-08

Fixes from a full code review (Codex CLI, gpt-6.1-sol).

- **Store lock** is now an OS file lock (`fcntl.flock` / `msvcrt.locking`): the OS releases it when
  the owner exits, so a lock held by a live process is never broken by age.
- **`migrate`** removes the legacy `**Date:** · **Area:** · **Status:**` line only right after the
  first `# Title`; the same line inside a code block or elsewhere in the body is kept.
  A file whose first line is `---` followed by spaces is treated as frontmatter and, if damaged, skipped.
- **Frontmatter parser** reports unclosed quotes and lists instead of accepting them; backslash
  escapes before a closing quote are handled (`"C:\\" # comment`).
- **Masking** in `issue-draft`: user names with spaces (`C:\Users\First Last\…`, `/home/First Last/…`)
  and whole Claude project slugs (`C--Users-<name>-…`) are masked.
- **Secret patterns** (shared by `issue-draft` and `lint`): Telegram bot tokens ending in `-`,
  `ghr_`/all `gh*_` tokens, GitLab `glpat-` and friends, lower-case `bearer`, Google API keys,
  Stripe `sk_live_`/`rk_live_`, JWTs.
- **`lint`**: dates must be exactly `YYYY-MM-DD` (Python 3.11+ `fromisoformat` also accepts
  `20260101` and week dates); unsupported `schema_version` is an error.
- **`search`**: short and technical terms (`C++`, `C#`, `R`, `Go`) are matched as whole words and no
  longer dropped from the query.
- **`fn.sh`**: `grep` searches the literal string (special characters escaped) and tells "no matches"
  (exit 1) from a search error (exit 2); `--root`, `--read-only` and `--json` are honoured by the shell
  commands too; without Python `init`/`new` refuse `--read-only`, validate the slug and never
  overwrite a note created in parallel. `root --json` prints JSON in both the shell and Python paths.
- Tests: 23 → 37, including a live two-process lock test and shell-wrapper tests.

## 2.0.0 — 2026-10-08

- `scripts/fieldnotes.py`: notes with flat frontmatter, `INDEX.md` generated under a store lock,
  `lint`, ranked `search`, `touch`, `issue-draft` with masking, `migrate` from 1.x.
- Statuses `workaround`, `needs-verification`, `fixed-upstream`, `obsolete`, `promoted`; `upstream`
  and `tool_version` fields.
- `fn.sh` became a wrapper with Python discovery and a reduced fallback mode.
- Trigger phrases first in the description; `evals/evals.json`; README in English and Russian.
