"""The `journal_club digest` commands the weekly workflow runs."""

from __future__ import annotations

import datetime as dt
import json
import urllib.error

import pytest
from builders import http_error, make_paper
from typer.testing import CliRunner

from journal_club.cli.digest import FALLBACK_NOTE
from journal_club.cli.main import app
from journal_club.digest.arxiv import ArxivError
from journal_club.digest.inspire import InspireError
from journal_club.digest.paper import WeeklyPapers
from journal_club.digest.window import Window

pytestmark = pytest.mark.unit

runner = CliRunner()

WINDOW = Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15))
GW_PAPER = make_paper("2610.00001", title="Gravitational waves from somewhere")
OTHER_PAPER = make_paper("2610.00002", title="Galaxy rotation curves")


def _write_week(path, source: str) -> None:
    WeeklyPapers(window=WINDOW, papers=(make_paper("2610.00001"),), source=source).save(path)


def _source(monkeypatch, module: str, outcome) -> list[str]:
    """Make *module*'s ``fetch_papers`` return *outcome*, or raise it if it is an exception.

    Returns:
        The queries it was called with.
    """
    queries: list[str] = []

    def fake_fetch(query: str) -> list:
        queries.append(query)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(f"journal_club.digest.{module}.fetch_papers", fake_fetch)
    return queries


def _fetch(out, *extra: str):
    return runner.invoke(app, ["digest", "fetch", "--out", str(out), "--run-date", "2026-10-19", *extra])


class TestTitle:
    """`journal_club digest title`."""

    def test_the_title_of_the_runs_week_is_printed(self) -> None:
        """The workflow checks for an existing issue with this title before spending anything on Claude."""
        result = runner.invoke(app, ["digest", "title", "--run-date", "2026-10-20"])
        assert result.exit_code == 0, result.output
        assert result.output == "Paper digest: 2026-10-09 to 2026-10-15\n"

    def test_without_a_run_date_today_is_used(self) -> None:
        """The scheduled runs pass no date."""
        result = runner.invoke(app, ["digest", "title"])
        assert result.output == Window.for_run(dt.datetime.now(dt.UTC).date()).title + "\n"

    def test_a_malformed_run_date_is_a_usage_error(self) -> None:
        """A typo in the manual run's date input fails loudly instead of building today's digest."""
        result = runner.invoke(app, ["digest", "title", "--run-date", "19/10/2026"])
        assert result.exit_code == 2


class TestFetch:
    """`journal_club digest fetch`."""

    def test_arxiv_is_used_when_it_answers(self, tmp_path, monkeypatch) -> None:
        """INSPIRE is not asked at all, and only gravitational-wave papers are written."""
        arxiv_queries = _source(monkeypatch, "arxiv", [GW_PAPER, OTHER_PAPER])
        inspire_queries = _source(monkeypatch, "inspire", [])
        out = tmp_path / "papers.json"
        result = _fetch(out)
        assert result.exit_code == 0, result.output
        assert arxiv_queries == [
            (
                "(cat:gr-qc OR cat:astro-ph.HE OR cat:astro-ph.CO OR cat:astro-ph.IM OR cat:physics.ins-det)"
                " AND submittedDate:[202610090000 TO 202610152359]"
            )
        ]
        assert inspire_queries == []
        week = WeeklyPapers.load(out)
        assert (week.source, week.window, week.papers) == ("arXiv", WINDOW, (GW_PAPER,))
        assert json.loads(out.read_text())["title"] == "Paper digest: 2026-10-09 to 2026-10-15"

    @pytest.mark.parametrize(
        "failure",
        [
            ArxivError("empty page"),
            http_error(429),
            http_error(400),
            urllib.error.URLError("unreachable"),
            TimeoutError("timed out"),
        ],
    )
    def test_inspire_is_used_when_arxiv_fails(self, tmp_path, monkeypatch, failure: Exception) -> None:
        """Every way arXiv can fail leads to the fallback, for the same window, with the same filter."""
        _source(monkeypatch, "arxiv", failure)
        inspire_queries = _source(monkeypatch, "inspire", [GW_PAPER, OTHER_PAPER])
        out = tmp_path / "papers.json"
        result = _fetch(out)
        assert result.exit_code == 0, result.output
        assert len(inspire_queries) == 1
        assert inspire_queries[0].endswith("and de 2026-10-09->2026-10-15")
        week = WeeklyPapers.load(out)
        assert (week.source, week.window, week.papers) == ("INSPIRE-HEP", WINDOW, (GW_PAPER,))

    def test_both_sources_failing_fails_without_writing(self, tmp_path, monkeypatch) -> None:
        """No file means the later steps have nothing to publish; the log names both failures."""
        _source(monkeypatch, "arxiv", http_error(429))
        _source(monkeypatch, "inspire", InspireError("returned 1 of 5 records"))
        out = tmp_path / "papers.json"
        result = _fetch(out)
        assert result.exit_code == 2
        assert not out.exists()

    def test_a_week_over_the_budget_fails_without_writing_or_falling_back(self, tmp_path, monkeypatch) -> None:
        """The other source would return the same oversized week, so the run stops for a person to look."""
        _source(
            monkeypatch, "arxiv", [make_paper(f"2610.{index:05d}", title="Gravitational waves") for index in range(201)]
        )
        inspire_queries = _source(monkeypatch, "inspire", [GW_PAPER])
        out = tmp_path / "papers.json"
        result = _fetch(out)
        assert result.exit_code == 2
        assert not out.exists()
        assert inspire_queries == []

    def test_an_unexpected_error_is_not_mistaken_for_an_outage(self, tmp_path, monkeypatch) -> None:
        """A bug in the code must fail the run, not quietly switch sources every week."""
        _source(monkeypatch, "arxiv", KeyError("bug"))
        inspire_queries = _source(monkeypatch, "inspire", [GW_PAPER])
        result = _fetch(tmp_path / "papers.json")
        assert result.exit_code != 0
        assert isinstance(result.exception, KeyError)
        assert inspire_queries == []

    def test_without_a_run_date_today_is_used(self, tmp_path, monkeypatch) -> None:
        """The scheduled run passes no date, so the window follows the UTC date of the run."""
        _source(monkeypatch, "arxiv", [])
        out = tmp_path / "papers.json"
        result = runner.invoke(app, ["digest", "fetch", "--out", str(out)])
        assert result.exit_code == 0, result.output
        assert WeeklyPapers.load(out).window == Window.for_run(dt.datetime.now(dt.UTC).date())

    def test_a_malformed_run_date_is_a_usage_error(self, tmp_path, monkeypatch) -> None:
        """A typo in the manual run's date input fails before anything is fetched."""
        queries = _source(monkeypatch, "arxiv", [])
        result = _fetch(tmp_path / "p.json", "--run-date", "19/10/2026")
        assert result.exit_code == 2
        assert queries == []
        assert not (tmp_path / "p.json").exists()


class TestFinalize:
    """`journal_club digest finalize`."""

    def _finalize(self, tmp_path, papers, digest_text: str | None):
        digest = tmp_path / "digest.md"
        if digest_text is not None:
            digest.write_text(digest_text, encoding="utf-8")
        out = tmp_path / "issue.md"
        args = ["digest", "finalize", "--papers", str(papers), "--digest", str(digest), "--out", str(out)]
        return runner.invoke(app, args), out

    def test_an_arxiv_week_is_written_without_a_note(self, tmp_path) -> None:
        """The usual case: the digest goes through unchanged."""
        papers = tmp_path / "papers.json"
        _write_week(papers, "arXiv")
        result, out = self._finalize(tmp_path, papers, "2610.00001 is great.\n")
        assert result.exit_code == 0, result.output
        assert out.read_text(encoding="utf-8") == "2610.00001 is great.\n"

    def test_an_inspire_week_says_so(self, tmp_path) -> None:
        """Readers are told the week came from the fallback and may be incomplete."""
        papers = tmp_path / "papers.json"
        _write_week(papers, "INSPIRE-HEP")
        result, out = self._finalize(tmp_path, papers, "2610.00001 is great.\n")
        assert result.exit_code == 0, result.output
        assert out.read_text(encoding="utf-8") == f"2610.00001 is great.\n\n---\n\n_{FALLBACK_NOTE}_\n"

    def test_a_missing_digest_fails(self, tmp_path) -> None:
        """If Claude wrote nothing, nothing is published."""
        papers = tmp_path / "papers.json"
        _write_week(papers, "arXiv")
        result, out = self._finalize(tmp_path, papers, None)
        assert result.exit_code == 2
        assert not out.exists()

    def test_an_invented_paper_fails(self, tmp_path) -> None:
        """The check that keeps hallucinated citations out of the issue."""
        papers = tmp_path / "papers.json"
        _write_week(papers, "arXiv")
        result, out = self._finalize(tmp_path, papers, "2610.00001 and 2610.99999\n")
        assert result.exit_code == 2
        assert not out.exists()


def test_the_digest_group_is_listed_in_the_help() -> None:
    """The top-level help shows the command the workflow calls."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "digest" in result.output
