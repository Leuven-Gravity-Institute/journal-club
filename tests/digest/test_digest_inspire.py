"""The INSPIRE-HEP fallback: the same window and fields as arXiv, every page, and no silent truncation."""

from __future__ import annotations

import datetime as dt
import urllib.error
import urllib.parse

import pytest
from builders import http_error, inspire_page, inspire_record, scripted_get

from journal_club.digest.http import FetchError, backoff_s
from journal_club.digest.inspire import (
    API_URL,
    FIELDS,
    PAGE_SIZE,
    REQUEST_INTERVAL_S,
    InspireError,
    build_query,
    fetch_papers,
    paper_from_record,
)
from journal_club.digest.window import Window

pytestmark = pytest.mark.unit

#: The form INSPIRE's own `next` links take: note the slash before the query.
NEXT = "https://inspirehep.net/api/literature/?sort=mostrecent&q=x&size=250&page=2"


def _params(url: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


class TestBuildQuery:
    """The INSPIRE search."""

    def test_the_query_covers_the_window_inclusively(self) -> None:
        """`de` is the first-submission date; INSPIRE's `a->b` range includes both ends."""
        query = build_query(Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)))
        assert query.endswith(") and de 2026-10-09->2026-10-15")

    def test_the_categories_are_alternatives(self) -> None:
        """Categories are or-ed inside parentheses, so the date range applies to all of them."""
        query = build_query(Window(dt.date(2026, 10, 9), dt.date(2026, 10, 9)), ("gr-qc", "astro-ph.HE"))
        assert query.startswith("(arxiv_eprints.categories:gr-qc or arxiv_eprints.categories:astro-ph.HE) and ")


class TestPaperFromRecord:
    """Reading one INSPIRE record into a paper."""

    def test_a_record_is_read_as_arxiv_would_give_it(self) -> None:
        """Same ID, categories (primary first), collapsed whitespace and "First Last" names as the arXiv path."""
        paper = paper_from_record(inspire_record("2610.01234", title="Black  holes\n merging")["metadata"])
        assert paper is not None
        assert paper.arxiv_id == "2610.01234"
        assert paper.url == "https://arxiv.org/abs/2610.01234"
        assert paper.title == "Black holes merging"
        assert paper.abstract == "An abstract. continued"
        assert paper.authors == ("A. Author", "B. Author")
        assert paper.author_count == 2
        assert paper.primary_category == "gr-qc"
        assert paper.categories == ("gr-qc", "astro-ph.HE")
        assert paper.published == "2026-10-08"

    def test_a_long_author_list_is_capped(self) -> None:
        """A collaboration paper keeps its first authors, in arXiv's name order, and its true author count."""
        metadata = inspire_record()["metadata"]
        metadata["authors"] = [{"full_name": f"Author{index}, A."} for index in range(1816)]
        paper = paper_from_record(metadata)
        assert paper is not None
        assert paper.authors == ("A. Author0", "A. Author1", "A. Author2")
        assert paper.author_count == 1816

    def test_a_record_without_an_arxiv_eprint_is_skipped(self) -> None:
        """The digest cites papers by arXiv ID, so a journal-only record cannot be used."""
        assert paper_from_record(inspire_record(None)["metadata"]) is None

    def test_the_arxiv_title_and_abstract_are_preferred(self) -> None:
        """INSPIRE also stores the journal's versions; the digest summarises the preprint."""
        metadata = inspire_record()["metadata"]
        metadata["titles"] = [{"source": "APS", "title": "Journal title"}, {"source": "arXiv", "title": "Preprint"}]
        metadata["abstracts"] = [{"source": "APS", "value": "Journal."}, {"source": "arXiv", "value": "Preprint."}]
        paper = paper_from_record(metadata)
        assert paper is not None
        assert (paper.title, paper.abstract) == ("Preprint", "Preprint.")

    def test_another_source_is_used_when_arxiv_has_none(self) -> None:
        """A record with only a journal title still gets a title rather than an empty string."""
        metadata = inspire_record()["metadata"]
        metadata["titles"] = [{"source": "APS", "title": "Journal title"}]
        paper = paper_from_record(metadata)
        assert paper is not None
        assert paper.title == "Journal title"

    def test_missing_optional_fields_read_as_empty(self) -> None:
        """A sparse record still parses, rather than failing the week."""
        paper = paper_from_record({"arxiv_eprints": [{"value": "2610.01234"}]})
        assert paper is not None
        assert (paper.title, paper.abstract, paper.authors, paper.primary_category, paper.published) == (
            "",
            "",
            (),
            "",
            "",
        )

    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            ("Zhou, Zi-An", "Zi-An Zhou"),
            ("van den Broeck, Chris", "Chris van den Broeck"),
            ("LIGO Scientific Collaboration", "LIGO Scientific Collaboration"),
            ("Trailing,", "Trailing,"),
        ],
    )
    def test_names_are_written_first_name_first(self, full_name: str, expected: str) -> None:
        """Matching arXiv's order keeps "first author et al." the same whichever source was used."""
        metadata = inspire_record()["metadata"]
        metadata["authors"] = [{"full_name": full_name}]
        paper = paper_from_record(metadata)
        assert paper is not None
        assert paper.authors == (expected,)


class TestFetchPapers:
    """Paging through the search."""

    def test_the_first_request_asks_for_the_query_and_the_needed_fields(self, no_sleep) -> None:
        """Asking only for the fields used keeps the responses small."""
        get, urls = scripted_get(inspire_page(0))
        fetch_papers("de 2026-10-09->2026-10-15", get=get, sleep=no_sleep)
        params = _params(urls[0])
        assert urls[0].startswith(f"{API_URL}?")
        assert params["q"] == "de 2026-10-09->2026-10-15"
        assert params["fields"] == FIELDS
        assert params["size"] == str(PAGE_SIZE)

    def test_every_page_is_read_by_following_next(self, no_sleep) -> None:
        """The second request is exactly the `next` link INSPIRE gave."""
        get, urls = scripted_get(
            inspire_page(3, inspire_record("2610.00001"), inspire_record("2610.00002"), next_url=NEXT),
            inspire_page(3, inspire_record("2610.00003")),
        )
        papers = fetch_papers("q", get=get, sleep=no_sleep)
        assert [paper.arxiv_id for paper in papers] == ["2610.00001", "2610.00002", "2610.00003"]
        assert urls[1] == NEXT

    def test_records_without_arxiv_ids_are_skipped_but_counted(self, no_sleep) -> None:
        """They count towards the total, so skipping them is not mistaken for missing pages."""
        get, _ = scripted_get(inspire_page(2, inspire_record("2610.00001"), inspire_record(None)))
        assert [paper.arxiv_id for paper in fetch_papers("q", get=get, sleep=no_sleep)] == ["2610.00001"]

    def test_a_paper_repeated_across_pages_is_kept_once(self, no_sleep) -> None:
        """Pages can shift when a record is added mid-fetch; the digest must not list a paper twice."""
        get, _ = scripted_get(
            inspire_page(2, inspire_record("2610.00001"), next_url=NEXT),
            inspire_page(2, inspire_record("2610.00001")),
        )
        assert len(fetch_papers("q", get=get, sleep=no_sleep)) == 1

    def test_requests_after_the_first_are_spaced_out(self) -> None:
        """One request a second stays inside INSPIRE's rate limit."""
        get, _ = scripted_get(
            inspire_page(2, inspire_record("2610.00001"), next_url=NEXT), inspire_page(2, inspire_record("2610.00002"))
        )
        waits: list[float] = []
        fetch_papers("q", get=get, sleep=waits.append)
        assert waits == [REQUEST_INTERVAL_S]

    def test_an_empty_week_is_an_empty_list(self, no_sleep) -> None:
        """A quiet week is zero papers, not an error."""
        get, _ = scripted_get(inspire_page(0))
        assert fetch_papers("q", get=get, sleep=no_sleep) == []

    def test_pages_that_end_before_the_total_stop_the_digest(self, no_sleep) -> None:
        """A missing `next` link mid-search would otherwise publish part of the week as all of it."""
        get, _ = scripted_get(inspire_page(5, inspire_record("2610.00001")))
        with pytest.raises(InspireError, match="1 of 5") as raised:
            fetch_papers("q", get=get, sleep=no_sleep)
        assert isinstance(raised.value, FetchError)

    def test_an_empty_page_before_the_total_stops_the_digest(self, no_sleep) -> None:
        """An empty page is not followed further, and the shortfall is reported."""
        get, _ = scripted_get(inspire_page(5, next_url=NEXT))
        with pytest.raises(InspireError, match="0 of 5"):
            fetch_papers("q", get=get, sleep=no_sleep)

    @pytest.mark.parametrize(
        "link",
        [
            "https://example.org/api/literature/?page=2",
            "http://inspirehep.net/api/literature/?page=2",
            "https://inspirehep.net/api/authors/?page=2",
            "https://inspirehep.net.example.org/api/literature/?page=2",
        ],
    )
    def test_a_next_link_outside_the_api_is_refused(self, link: str, no_sleep) -> None:
        """The response decides the next URL, so it is held to the host, scheme and path it came from."""
        get, urls = scripted_get(inspire_page(2, inspire_record("2610.00001"), next_url=link))
        with pytest.raises(InspireError, match="outside"):
            fetch_papers("q", get=get, sleep=no_sleep)
        assert len(urls) == 1

    def test_rate_limiting_is_retried_through_the_shared_helper(self) -> None:
        """INSPIRE's 429s are waited out like arXiv's."""
        get, _ = scripted_get(http_error(429), inspire_page(1, inspire_record("2610.00001")))
        waits: list[float] = []
        assert len(fetch_papers("q", get=get, sleep=waits.append)) == 1
        assert waits == [backoff_s(0)]

    def test_rate_limiting_that_persists_surfaces(self, no_sleep) -> None:
        """Once the retries are spent the error is raised, and the CLI reports both sources failed."""
        get, _ = scripted_get(*[http_error(503)] * 2)
        with pytest.raises(urllib.error.HTTPError):
            fetch_papers("q", get=get, sleep=no_sleep, retries=1)

    @pytest.mark.parametrize("body", ["<html>Bad gateway</html>", "{}", '{"hits": {"hits": []}}', "[]"])
    def test_a_malformed_response_is_an_error_not_an_empty_week(self, body: str, no_sleep) -> None:
        """A proxy error page must not read as "no papers this week", nor crash past the CLI's handling."""
        get, _ = scripted_get(body)
        with pytest.raises(InspireError, match="not a search result"):
            fetch_papers("q", get=get, sleep=no_sleep)
