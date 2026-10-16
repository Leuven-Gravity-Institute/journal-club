"""Fetching from the arXiv API: every page, every paper, and failures that are survived or surfaced."""

from __future__ import annotations

import datetime as dt
import urllib.error
import urllib.parse

import pytest
from builders import atom_entry, atom_feed, http_error, scripted_get

from journal_club.digest.arxiv import PAGE_SIZE, REQUEST_INTERVAL_S, ArxivError, build_query, fetch_papers, parse_feed
from journal_club.digest.http import FetchError, backoff_s
from journal_club.digest.window import Window

pytestmark = pytest.mark.unit


def _params(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


class TestBuildQuery:
    """The search query."""

    def test_the_query_spans_whole_days_of_the_window(self) -> None:
        """Both ends are inclusive: from 00:00 on the first day to 23:59 on the last."""
        query = build_query(Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)))
        assert query.endswith("AND submittedDate:[202610090000 TO 202610152359]")

    def test_the_categories_are_alternatives(self) -> None:
        """Categories are OR-ed inside parentheses, so the date range applies to all of them."""
        query = build_query(Window(dt.date(2026, 10, 9), dt.date(2026, 10, 9)), ("gr-qc", "astro-ph.HE"))
        assert query.startswith("(cat:gr-qc OR cat:astro-ph.HE) AND ")


class TestParseFeed:
    """Reading one page of the Atom feed."""

    def test_an_entry_is_read_into_an_unversioned_paper(self) -> None:
        """The version suffix is dropped and whitespace in the title and abstract is collapsed."""
        total, papers = parse_feed(atom_feed(7, atom_entry("2610.01234", "Black  holes\n  merging")))
        assert total == 7
        [paper] = papers
        assert paper.arxiv_id == "2610.01234"
        assert paper.title == "Black holes merging"
        assert paper.abstract == "An abstract. continued"
        assert paper.authors == ("A. Author", "B. Author")
        assert paper.author_count == 2
        assert paper.primary_category == "gr-qc"
        assert paper.categories == ("gr-qc", "astro-ph.HE")
        assert paper.published == "2026-10-08T17:59:59Z"

    def test_an_error_entry_is_raised_rather_than_read_as_a_paper(self) -> None:
        """The API reports a bad query as an entry; reading it as a paper would publish the error."""
        error = "<entry><id>http://arxiv.org/api/errors#bad</id><summary>malformed query</summary></entry>"
        with pytest.raises(ArxivError, match="malformed query"):
            parse_feed(atom_feed(1, error))

    def test_a_long_author_list_is_capped(self) -> None:
        """A collaboration paper keeps its first authors and its true author count."""
        _, [paper] = parse_feed(atom_feed(1, atom_entry("2610.01234", authors=1816)))
        assert paper.authors == ("A. Author", "B. Author", "Author 3")
        assert paper.author_count == 1816

    @pytest.mark.parametrize(
        "body",
        [
            "<html><body>Rate exceeded</body></html>",
            "not xml at all",
            atom_feed(1).replace("<opensearch:totalResults>1", "<opensearch:totalResults>many"),
            atom_feed(1).replace("<opensearch:totalResults>1</opensearch:totalResults>", ""),
        ],
    )
    def test_a_response_that_is_not_a_feed_is_a_fetch_error(self, body: str) -> None:
        """An error page served with status 200 must reach the fallback, not crash past it."""
        with pytest.raises(ArxivError, match="not an API feed"):
            parse_feed(body)

    def test_missing_optional_elements_read_as_empty(self) -> None:
        """An entry without a primary category or authors still parses, rather than failing the week."""
        entry = "<entry><id>http://arxiv.org/abs/2610.01234v1</id><title>T</title><summary>S</summary></entry>"
        [paper] = parse_feed(atom_feed(1, entry))[1]
        assert (paper.primary_category, paper.authors, paper.published) == ("", (), "")

    def test_an_empty_feed_has_no_papers(self) -> None:
        """A quiet week is zero papers, not an error."""
        assert parse_feed(atom_feed(0)) == (0, [])


class TestPagination:
    """Following the API across pages."""

    def test_every_page_is_read(self, no_sleep) -> None:
        """Each request starts where the previous page ended."""
        get, urls = scripted_get(
            atom_feed(3, atom_entry("2610.00001"), atom_entry("2610.00002")), atom_feed(3, atom_entry("2610.00003"))
        )
        papers = fetch_papers("q", get=get, sleep=no_sleep)
        assert [paper.arxiv_id for paper in papers] == ["2610.00001", "2610.00002", "2610.00003"]
        assert [_params(url)["start"] for url in urls] == ["0", "2"]

    def test_each_request_carries_the_query_and_page_size(self, no_sleep) -> None:
        """Sorted by submission date so pages do not shift under the reader."""
        get, urls = scripted_get(atom_feed(0))
        fetch_papers("cat:gr-qc", get=get, sleep=no_sleep)
        params = _params(urls[0])
        assert params["search_query"] == "cat:gr-qc"
        assert params["max_results"] == str(PAGE_SIZE)
        assert params["sortBy"] == "submittedDate"

    def test_a_paper_repeated_across_pages_is_kept_once(self, no_sleep) -> None:
        """Pages can overlap when a paper is announced mid-fetch; the digest must not list it twice."""
        get, _ = scripted_get(
            atom_feed(3, atom_entry("2610.00001"), atom_entry("2610.00002")),
            atom_feed(3, atom_entry("2610.00002")),
        )
        papers = fetch_papers("q", get=get, sleep=no_sleep)
        assert [paper.arxiv_id for paper in papers] == ["2610.00001", "2610.00002"]

    def test_requests_after_the_first_are_spaced_out(self) -> None:
        """ArXiv asks for three seconds between requests; the first one need not wait."""
        get, _ = scripted_get(atom_feed(2, atom_entry("2610.00001")), atom_feed(2, atom_entry("2610.00002")))
        waits: list[float] = []
        fetch_papers("q", get=get, sleep=waits.append)
        assert waits == [REQUEST_INTERVAL_S]


class TestRetries:
    """Failures the fetch survives, and the ones it surfaces."""

    def test_an_empty_page_inside_the_total_is_retried(self, no_sleep) -> None:
        """Taking it as the end would silently drop the rest of the week."""
        get, _ = scripted_get(
            atom_feed(2, atom_entry("2610.00001")), atom_feed(2), atom_feed(2, atom_entry("2610.00002"))
        )
        papers = fetch_papers("q", get=get, sleep=no_sleep)
        assert [paper.arxiv_id for paper in papers] == ["2610.00001", "2610.00002"]

    def test_a_page_that_stays_empty_stops_the_digest(self, no_sleep) -> None:
        """After the retries, an incomplete week is an error, not a shorter digest."""
        get, urls = scripted_get(atom_feed(2, atom_entry("2610.00001")), *[atom_feed(2)] * 4)
        with pytest.raises(ArxivError, match="empty page at offset 1 of 2") as raised:
            fetch_papers("q", get=get, sleep=no_sleep, retries=3)
        assert len(urls) == 5
        assert isinstance(raised.value, FetchError), "the CLI falls back on any FetchError"

    def test_a_rate_limited_page_is_retried_through_the_shared_helper(self) -> None:
        """ArXiv's 429s are waited out with the backoff `journal_club.digest.http` defines."""
        get, _ = scripted_get(http_error(429), http_error(429), atom_feed(1, atom_entry("2610.00001")))
        waits: list[float] = []
        papers = fetch_papers("q", get=get, sleep=waits.append)
        assert [paper.arxiv_id for paper in papers] == ["2610.00001"]
        assert waits == [backoff_s(0), backoff_s(1)]

    def test_an_empty_page_is_retried_with_the_backoff(self) -> None:
        """The wait before re-asking for an empty page grows like any other retry."""
        get, _ = scripted_get(atom_feed(1), atom_feed(1), atom_feed(1, atom_entry("2610.00001")))
        waits: list[float] = []
        fetch_papers("q", get=get, sleep=waits.append)
        assert waits == [backoff_s(0), backoff_s(1)]

    def test_rate_limiting_that_persists_surfaces(self, no_sleep) -> None:
        """Once the retries are spent the HTTP error is raised, for the caller to fall back."""
        get, _ = scripted_get(*[http_error(429)] * 3)
        with pytest.raises(urllib.error.HTTPError):
            fetch_papers("q", get=get, sleep=no_sleep, retries=2)
