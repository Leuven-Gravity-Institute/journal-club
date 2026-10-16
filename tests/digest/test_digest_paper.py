"""Papers, and the JSON file that hands a week of them from the fetch step to the summariser."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace

import pytest
from builders import make_paper

from journal_club.digest.paper import (
    MAX_LISTED_AUTHORS,
    MAX_PAPERS,
    MAX_PAPERS_FILE_CHARS,
    ContextBudgetError,
    Paper,
    WeeklyPapers,
    cap_authors,
)
from journal_club.digest.window import Window

pytestmark = pytest.mark.unit


class TestPaper:
    """One paper."""

    def test_the_url_is_the_unversioned_abstract_page(self) -> None:
        """Linking the unversioned page means a reader lands on the latest version."""
        assert make_paper("2610.01234").url == "https://arxiv.org/abs/2610.01234"

    def test_a_paper_survives_a_round_trip_through_a_dict(self) -> None:
        """Tuples go out as lists and come back as tuples, so the loaded paper compares equal."""
        paper = make_paper()
        assert Paper.from_dict(json.loads(json.dumps(paper.to_dict()))) == paper

    def test_the_dict_carries_the_url_for_the_summariser(self) -> None:
        """The prompt tells Claude to link each paper's `url`, so it must be in the file."""
        assert make_paper("2610.01234").to_dict()["url"] == "https://arxiv.org/abs/2610.01234"


class TestAuthors:
    """Keeping author lists short."""

    @pytest.mark.parametrize("count", [0, 1, MAX_LISTED_AUTHORS, MAX_LISTED_AUTHORS + 1, 1816])
    def test_the_first_authors_are_kept_and_all_are_counted(self, count: int) -> None:
        """A 1816-author collaboration paper keeps its first few names and its true author count."""
        names = [f"Author {index}" for index in range(count)]
        kept, total = cap_authors(names)
        assert kept == tuple(names[:MAX_LISTED_AUTHORS])
        assert total == count

    def test_cap_authors_takes_any_iterable(self) -> None:
        """The parsers hand it generators."""
        assert cap_authors(name for name in ["A", "B", "C", "D", "E"]) == (("A", "B", "C"), 5)

    def test_an_uncapped_author_list_is_refused(self) -> None:
        """A parser that forgot to cap would otherwise put the whole list in front of Claude."""
        with pytest.raises(ValueError, match="cap_authors"):
            replace(make_paper(), authors=("A", "B", "C", "D"), author_count=4)

    def test_a_count_below_the_listed_authors_is_refused(self) -> None:
        """Whether to write "et al." is decided from the count, so it must not undercount."""
        with pytest.raises(ValueError, match="counts 1"):
            replace(make_paper(), authors=("A", "B"), author_count=1)

    def test_the_count_survives_a_round_trip(self) -> None:
        """The prompt tells Claude to read `author_count`, so it must be in the file."""
        paper = replace(make_paper(), authors=("A", "B", "C"), author_count=1816)
        assert paper.to_dict()["author_count"] == 1816
        assert Paper.from_dict(paper.to_dict()) == paper


class TestContextBudget:
    """The hard limit on what reaches the summariser."""

    def _week(self, *papers: Paper) -> WeeklyPapers:
        return WeeklyPapers(window=Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)), papers=papers, source="arXiv")

    def test_a_week_of_max_papers_is_written(self, tmp_path) -> None:
        """The limit is inclusive."""
        path = tmp_path / "papers.json"
        self._week(*(make_paper(f"2610.{index:05d}") for index in range(MAX_PAPERS))).save(path)
        assert len(WeeklyPapers.load(path).papers) == MAX_PAPERS

    def test_one_paper_more_is_refused_and_nothing_is_written(self, tmp_path) -> None:
        """Refused rather than trimmed: a week that size means something changed upstream."""
        path = tmp_path / "papers.json"
        with pytest.raises(ContextBudgetError, match=f"{MAX_PAPERS + 1} papers"):
            self._week(*(make_paper(f"2610.{index:05d}") for index in range(MAX_PAPERS + 1))).save(path)
        assert not path.exists()

    def test_a_file_over_the_character_limit_is_refused_and_nothing_is_written(self, tmp_path) -> None:
        """A few papers can still be too large, e.g. if a source starts returning full texts as abstracts."""
        path = tmp_path / "papers.json"
        week = self._week(make_paper(abstract="x" * MAX_PAPERS_FILE_CHARS))
        with pytest.raises(ContextBudgetError, match="characters"):
            week.save(path)
        assert not path.exists()

    def test_a_file_at_the_character_limit_is_written(self, tmp_path) -> None:
        """The limit is inclusive, and measured on exactly the text that is written."""
        path = tmp_path / "papers.json"
        overhead = len(self._week(make_paper(abstract="")).to_json())
        week = self._week(make_paper(abstract="x" * (MAX_PAPERS_FILE_CHARS - overhead)))
        week.save(path)
        assert len(path.read_text(encoding="utf-8")) == MAX_PAPERS_FILE_CHARS

    def test_a_normal_week_is_well_inside_the_limit(self) -> None:
        """80 papers with full-length abstracts use well under half the budget, so the gate only trips on outliers."""
        abstract = "x" * 1920  # arXiv's abstract limit
        week = self._week(*(make_paper(f"2610.{index:05d}", abstract=abstract) for index in range(80)))
        assert len(week.to_json()) < MAX_PAPERS_FILE_CHARS / 2


class TestWeeklyPapers:
    """The papers file."""

    def test_saving_and_loading_gives_back_the_same_week(self, tmp_path) -> None:
        """What `finalize` checks against must be exactly what `fetch` found."""
        week = WeeklyPapers(
            window=Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)),
            papers=(make_paper("2610.00001"), make_paper("2610.00002", title="Ünïcode tïtle")),
            source="INSPIRE-HEP",
        )
        path = tmp_path / "papers.json"
        week.save(path)
        assert WeeklyPapers.load(path) == week

    def test_the_file_carries_the_issue_title(self, tmp_path) -> None:
        """The workflow reads the title from the file instead of rebuilding it in shell."""
        path = tmp_path / "papers.json"
        WeeklyPapers(window=Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)), papers=(), source="arXiv").save(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["title"] == "Paper digest: 2026-10-09 to 2026-10-15"
        assert document["papers"] == []
        assert document["source"] == "arXiv"
