# ruff: noqa PL0415
"""Digest command module."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

digest_app = typer.Typer(help="Build the weekly paper digest.", no_args_is_help=True)

RunDate = Annotated[
    str | None,
    typer.Option("--run-date", help="Build the digest as if run on this UTC date (YYYY-MM-DD); defaults to today."),
]

#: The closing note of an issue built from the fallback source.
FALLBACK_NOTE = (
    "The arXiv API was unavailable, so this week's papers were fetched from INSPIRE-HEP, "
    "which does not index every arXiv paper. A few papers may be missing."
)


def _window(run_date: str | None):  # noqa: ANN202 -- the import is deferred, so the type cannot be named here
    from journal_club.digest.window import Window

    if run_date is None:
        return Window.for_run(dt.datetime.now(dt.UTC).date())
    try:
        return Window.for_run(dt.date.fromisoformat(run_date))
    except ValueError as error:
        raise typer.BadParameter(f"{run_date!r} is not a date in YYYY-MM-DD form", param_hint="--run-date") from error


@digest_app.command("title")
def title_command(run_date: RunDate = None) -> None:
    """Print the issue title of the week a run on the date belongs to.

    Args:
        run_date: Build the digest as if run on this UTC date; defaults to today.
    """
    typer.echo(_window(run_date).title)


@digest_app.command("fetch")
def fetch_command(
    out: Annotated[Path, typer.Option("--out", help="Where to write the papers as JSON.")],
    run_date: RunDate = None,
) -> None:
    """Fetch the window's gravitational-wave papers, from arXiv or else from INSPIRE-HEP.

    Args:
        out: Where to write the papers as JSON.
        run_date: Build the digest as if run on this UTC date; defaults to today.

    Raises:
        Exit: With status 2 if neither source could deliver the complete week, or the week is too large to
            hand to the summariser.
    """
    import urllib.error
    from logging import getLogger

    from journal_club.digest import arxiv, inspire
    from journal_club.digest.http import FetchError
    from journal_club.digest.paper import ContextBudgetError, WeeklyPapers
    from journal_club.digest.relevance import is_gravitational_wave

    logger = getLogger("journal_club")

    window = _window(run_date)
    failures = []
    for source in (arxiv, inspire):
        try:
            fetched = source.fetch_papers(source.build_query(window))
        except (FetchError, urllib.error.URLError, TimeoutError) as error:
            logger.warning("Could not fetch from %s: %s", source.SOURCE, error)
            failures.append(f"{source.SOURCE}: {error}")
            continue
        papers = tuple(paper for paper in fetched if is_gravitational_wave(paper))
        try:
            WeeklyPapers(window=window, papers=papers, source=source.SOURCE).save(out)
        except ContextBudgetError as error:
            # Not a source failure, so the other source is not tried: it would return the same week.
            logger.error("Refusing to hand this week to the summariser: %s", error)
            raise typer.Exit(code=2) from error
        logger.info(
            "%d of %d papers submitted %s to %s are about gravitational waves (from %s)",
            len(papers),
            len(fetched),
            window.first,
            window.last,
            source.SOURCE,
        )
        return
    logger.error("No source could deliver the week: %s", "; ".join(failures))
    raise typer.Exit(code=2)


@digest_app.command("finalize")
def finalize_command(
    papers: Annotated[Path, typer.Option("--papers", help="The JSON written by `fetch`.")],
    digest: Annotated[Path, typer.Option("--digest", help="The Markdown digest Claude wrote.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the issue body.")],
) -> None:
    """Check the digest against the fetched papers and write the issue body.

    Args:
        papers: The JSON written by ``fetch``.
        digest: The Markdown digest Claude wrote; a missing file counts as an empty digest.
        out: Where to write the issue body.

    Raises:
        Exit: With status 2 if the digest cannot be published.
    """
    from logging import getLogger

    from journal_club.digest import arxiv
    from journal_club.digest.issue import DigestRejectedError, build_issue_body
    from journal_club.digest.paper import WeeklyPapers

    logger = getLogger("journal_club")

    weekly = WeeklyPapers.load(papers)
    text = digest.read_text(encoding="utf-8") if digest.exists() else ""
    note = None if weekly.source == arxiv.SOURCE else FALLBACK_NOTE
    try:
        body = build_issue_body(weekly.papers, text, note=note)
    except DigestRejectedError as error:
        logger.error("%s", error)
        raise typer.Exit(code=2) from error
    out.write_text(body, encoding="utf-8")
    logger.info("Wrote the issue body for %r to %s", weekly.window.title, out)


@digest_app.command("superseded")
def superseded_command(
    title: Annotated[str, typer.Option("--title", help="The title of the digest just published.")],
    issues: Annotated[
        Path, typer.Option("--issues", help="The open issues, from `gh issue list --json number,title`.")
    ],
) -> None:
    """Print the numbers of the open digest issues for earlier weeks, one per line, oldest first.

    Args:
        title: The title of the digest just published.
        issues: The open issues, from ``gh issue list --json number,title``.

    Raises:
        BadParameter: If *title* is not a digest title.
    """
    import json

    from journal_club.digest.issue import superseded_issues

    try:
        numbers = superseded_issues(json.loads(issues.read_text(encoding="utf-8")), title)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--title") from error
    for number in numbers:
        typer.echo(number)
