"""Fetching papers from INSPIRE-HEP, the fallback when the arXiv API is unavailable.

INSPIRE indexes arXiv's ``gr-qc`` and most of its gravitational-wave astrophysics within a day, and
records each paper's arXiv ID, categories and first-submission date, so it can stand in for the arXiv API
with the same window and the same keyword filter. It does not index every arXiv paper, so a week fetched
from here may miss a few; the issue says when that happened.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from collections.abc import Callable

from journal_club.digest.http import FetchError, get_with_retries, http_get
from journal_club.digest.paper import Paper, cap_authors
from journal_club.digest.relevance import CATEGORIES
from journal_club.digest.window import Window

logger = logging.getLogger("journal_club")

#: How the papers file and the issue name this source.
SOURCE = "INSPIRE-HEP"
API_URL = "https://inspirehep.net/api/literature"

#: INSPIRE allows a burst of requests per few seconds per client; one a second stays well inside it.
REQUEST_INTERVAL_S = 1.0
#: Records requested per page.
PAGE_SIZE = 250
#: Only the fields a :class:`~journal_club.digest.paper.Paper` needs, to keep the responses small. The full
#: author list is still requested, because a paper records how many authors it has.
FIELDS = "arxiv_eprints,titles,abstracts,authors.full_name,preprint_date"


class InspireError(FetchError):
    """INSPIRE-HEP could not deliver a complete answer."""


def build_query(window: Window, categories: tuple[str, ...] = CATEGORIES) -> str:
    """Return the INSPIRE search for papers in *categories* first submitted within *window*.

    ``de`` is INSPIRE's earliest date of a record, which for an arXiv preprint is its first submission;
    both ends of the range are inclusive.

    Args:
        window: The submission dates, both inclusive.
        categories: The arXiv categories to search.

    Returns:
        The query string, unencoded.
    """
    listed = " or ".join(f"arxiv_eprints.categories:{category}" for category in categories)
    return f"({listed}) and de {window.first.isoformat()}->{window.last.isoformat()}"


def _first(items: list[dict], key: str, *, prefer_source: str = "arXiv") -> str:
    """Return *key* of the entry from *prefer_source*, else of the first entry, else an empty string."""
    for item in items:
        if item.get("source") == prefer_source and item.get(key):
            return item[key]
    return next((item[key] for item in items if item.get(key)), "")


def _display_name(full_name: str) -> str:
    """Return INSPIRE's ``"Last, First"`` as arXiv writes it, ``"First Last"``."""
    last, comma, first = full_name.partition(", ")
    return f"{first} {last}" if comma and first else full_name


def paper_from_record(metadata: dict) -> Paper | None:
    """Return the paper an INSPIRE literature record describes.

    Args:
        metadata: The record's ``metadata`` object.

    Returns:
        The paper, or None if the record has no arXiv identifier and so cannot be cited in the digest.
    """
    eprints = metadata.get("arxiv_eprints") or []
    if not eprints or not eprints[0].get("value"):
        return None
    categories = tuple(eprints[0].get("categories") or ())
    authors, author_count = cap_authors(
        _display_name(author.get("full_name", "")) for author in metadata.get("authors") or []
    )
    return Paper(
        arxiv_id=eprints[0]["value"],
        title=" ".join(_first(metadata.get("titles") or [], "title").split()),
        authors=authors,
        author_count=author_count,
        abstract=" ".join(_first(metadata.get("abstracts") or [], "value").split()),
        # INSPIRE lists the primary category first, as arXiv does.
        primary_category=categories[0] if categories else "",
        categories=categories,
        published=metadata.get("preprint_date", ""),
    )


def _is_api_url(url: str) -> bool:
    """Return whether *url* is a search on :data:`API_URL`; INSPIRE's own links add a trailing slash."""
    link, api = urllib.parse.urlsplit(url), urllib.parse.urlsplit(API_URL)
    return (link.scheme, link.netloc, link.path.rstrip("/")) == (api.scheme, api.netloc, api.path)


def _page_url(query: str) -> str:
    params = {"q": query, "size": PAGE_SIZE, "sort": "mostrecent", "fields": FIELDS}
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def fetch_papers(
    query: str,
    *,
    get: Callable[[str], str] = http_get,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = 4,
) -> list[Paper]:
    """Return every arXiv paper matching the INSPIRE *query*, following the API's pagination.

    Args:
        query: An INSPIRE search, e.g. from :func:`build_query`.
        get: Fetches a URL and returns the body; replaced in tests.
        sleep: Waits between requests; replaced in tests.
        retries: How many times to retry a failed request before giving up.

    Returns:
        The papers, de-duplicated by arXiv ID, in the order INSPIRE returned them. Records without an arXiv
        identifier are skipped.

    Raises:
        InspireError: If a response is not a search result, the pages end before the reported total, or a
            page links outside the API.
        urllib.error.URLError: If a request still fails after *retries* retries, or fails with a status
            that retrying cannot fix.
        TimeoutError: If a request still times out after *retries* retries.
    """
    papers: dict[str, Paper] = {}
    url: str | None = _page_url(query)
    seen = 0
    total = 0
    while url is not None:
        if seen:
            sleep(REQUEST_INTERVAL_S)
        body = get_with_retries(url, get=get, sleep=sleep, retries=retries)
        try:
            document = json.loads(body)
            hits = document["hits"]["hits"]
            total = int(document["hits"]["total"])
        except (ValueError, KeyError, TypeError) as error:
            raise InspireError(f"INSPIRE sent a response that is not a search result: {error!r}") from error
        seen += len(hits)
        for hit in hits:
            paper = paper_from_record(hit.get("metadata", {}))
            if paper is not None:
                papers.setdefault(paper.arxiv_id, paper)
        url = document.get("links", {}).get("next") if hits and seen < total else None
        if url is not None and not _is_api_url(url):
            raise InspireError(f"INSPIRE linked the next page outside its API: {url}")
    if seen < total:
        raise InspireError(
            f"INSPIRE returned {seen} of {total} records; refusing to publish a digest that would silently "
            f"miss the rest of the week."
        )
    return list(papers.values())
