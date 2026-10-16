# Journal Club

[![Python CI](https://github.com/Leuven-Gravity-Institute/journal-club/actions/workflows/ci.yml/badge.svg)](https://github.com/Leuven-Gravity-Institute/journal-club/actions/workflows/ci.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/Leuven-Gravity-Institute/journal-club/main.svg)](https://results.pre-commit.ci/latest/github/Leuven-Gravity-Institute/journal-club/main)
[![Documentation Status](https://github.com/Leuven-Gravity-Institute/journal-club/actions/workflows/documentation.yml/badge.svg)](https://leuven-gravity-institute.github.io/journal-club/)
[![codecov](https://codecov.io/gh/Leuven-Gravity-Institute/journal-club/graph/badge.svg?token=COF8341N60)](https://codecov.io/gh/Leuven-Gravity-Institute/journal-club)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![DOI](https://zenodo.org/badge/924023559.svg)](https://doi.org/10.5281/zenodo.18017404)
[![SPEC 0 — Minimum Supported Dependencies](https://img.shields.io/badge/SPEC-0-green?labelColor=%23004811&color=%235CA038)](https://scientific-python.org/specs/spec-0000/)

Tooling for the group's journal club. It is not published to PyPI.

## Weekly paper digest

Every Monday at 07:00 UTC, the
[Weekly Paper Digest](.github/workflows/paper_digest.yml) workflow opens one
issue summarising the previous week's gravitational-wave papers on arXiv:

1. `journal_club digest fetch` queries the arXiv API for papers submitted in the
   window (Friday to Thursday of the week before, so every paper has been
   announced) and keeps the ones about gravitational waves. If arXiv is still
   unavailable after its retries (rate limiting, outages, or a response that is
   not a feed), the same search goes to [INSPIRE-HEP](https://inspirehep.net)
   instead, and the issue says so.
2. Claude reads those papers and writes the digest, following
   [`.github/paper-digest/prompt.md`](.github/paper-digest/prompt.md).
3. `journal_club digest finalize` checks the digest against the fetched papers:
   an arXiv ID that was not fetched stops the run, and any paper the digest left
   out is listed at the end.
4. A separate job opens the issue.

A backup run on Tuesday builds the same week. If Monday's issue exists it stops
before Claude runs, so it uses no Claude usage on a normal week. A manual run on
any day builds the digest of that day's week, and is skipped the same way if the
issue already exists.

To change what the digest covers, edit the categories and keywords in
`src/journal_club/digest/relevance.py`; both sources use them. To change how it
is written, edit the prompt.

**Setup.** Run `claude setup-token` and store the token as the secret
`CLAUDE_CODE_OAUTH_TOKEN` of the `paper-digest` environment (Settings →
Environments), which only `main` may deploy to. Do not keep it as a repository
secret: workflows on any branch can read those. Runs count against that Claude
account's usage, so only that account (set in the workflow's `if` conditions)
can start or re-run it by hand: Actions → Weekly Paper Digest → Run workflow,
optionally for a past date, or `gh workflow run paper_digest.yml`. Runs started
by anyone else are skipped before any paper is fetched.

**Locally.**

```bash
uv sync
uv run journal_club digest fetch --out papers.json --run-date 2026-10-19
uv run journal_club digest finalize --papers papers.json --digest digest.md --out issue.md
```
