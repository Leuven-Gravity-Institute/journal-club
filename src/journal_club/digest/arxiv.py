"""Fetching papers from the arXiv API, the primary source.

Which papers exist is decided here, from the API, and never by the summariser: a model asked to "find
recent papers" can invent one or misdate it.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable

from journal_club.digest.http import FetchError, backoff_s, get_with_retries, http_get
from journal_club.digest.paper import Paper, cap_authors
from journal_club.digest.relevance import CATEGORIES
from journal_club.digest.window import Window

logger = logging.getLogger("journal_club")

#: How the papers file and the issue name this source.
SOURCE = "arXiv"
API_URL = "https://export.arxiv.org/api/query"

#: arXiv asks API clients to wait three seconds between requests.
REQUEST_INTERVAL_S = 3.0
#: Results requested per page.
PAGE_SIZE = 500

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivError(FetchError):
    """The arXiv API could not deliver a complete answer."""


def build_query(window: Window, categories: tuple[str, ...] = CATEGORIES) -> str:
    """Return the arXiv ``search_query`` for papers in *categories* submitted within *window*.

    Args:
        window: The submission dates, both inclusive.
        categories: The arXiv categories to search.

    Returns:
        The query string, unencoded.
    """
    listed = " OR ".join(f"cat:{category}" for category in categories)
    return f"({listed}) AND submittedDate:[{window.first:%Y%m%d}0000 TO {window.last:%Y%m%d}2359]"


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path, _NS)
    if found is None or found.text is None:
        return ""
    return " ".join(found.text.split())


def parse_feed(xml: str) -> tuple[int, list[Paper]]:
    """Return the total result count and the papers in one page of an arXiv API Atom feed.

    Args:
        xml: The response body.

    Returns:
        The query's total number of results, and this page's papers.

    Raises:
        ArxivError: If the response is not an API feed (e.g. an error page served with status 200), or the
            feed reports an error, which the API does as an entry rather than a status.
    """
    try:
        root = ET.fromstring(xml)  # noqa: S314 -- the response comes from arXiv over HTTPS
    except ET.ParseError as error:
        raise ArxivError(f"arXiv sent a response that is not an API feed: {error}") from error
    # Checked rather than defaulted: well-formed HTML parses too, and reading it as "0 results" would quietly
    # skip the week instead of falling back.
    count = _text(root, "opensearch:totalResults")
    if root.tag != f"{{{_NS['atom']}}}feed" or not count.isdigit():
        raise ArxivError(f"arXiv sent a response that is not an API feed (root {root.tag!r}, count {count!r})")
    total = int(count)
    papers = []
    for entry in root.findall("atom:entry", _NS):
        entry_id = _text(entry, "atom:id")
        if "/api/errors" in entry_id:
            raise ArxivError(f"arXiv rejected the query: {_text(entry, 'atom:summary')}")
        primary = entry.find("arxiv:primary_category", _NS)
        authors, author_count = cap_authors(_text(author, "atom:name") for author in entry.findall("atom:author", _NS))
        papers.append(
            Paper(
                arxiv_id=re.sub(r"v\d+$", "", entry_id.rsplit("/abs/", 1)[-1]),
                title=_text(entry, "atom:title"),
                authors=authors,
                author_count=author_count,
                abstract=_text(entry, "atom:summary"),
                primary_category=primary.get("term", "") if primary is not None else "",
                categories=tuple(category.get("term", "") for category in entry.findall("atom:category", _NS)),
                published=_text(entry, "atom:published"),
            )
        )
    return total, papers


def _page_url(query: str, start: int) -> str:
    params = {
        "search_query": query,
        "start": start,
        "max_results": PAGE_SIZE,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def _fetch_page(
    url: str, start: int, *, get: Callable[[str], str], sleep: Callable[[float], None], retries: int
) -> tuple[int, list[Paper]]:
    total = 0
    for attempt in range(retries + 1):
        if attempt:
            sleep(backoff_s(attempt - 1))
        elif start:
            sleep(REQUEST_INTERVAL_S)
        total, page = parse_feed(get_with_retries(url, get=get, sleep=sleep, retries=retries))
        if page or start >= total:
            return total, page
        logger.warning("arXiv returned an empty page at offset %d of %d; retrying", start, total)
    raise ArxivError(
        f"arXiv returned an empty page at offset {start} of {total} results {retries + 1} times; "
        f"refusing to publish a digest that would silently miss the rest of the week."
    )


def fetch_papers(
    query: str,
    *,
    get: Callable[[str], str] = http_get,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = 4,
) -> list[Paper]:
    """Return every paper matching *query*, following the API's pagination.

    The API now and then answers a page with no entries even though more remain; that page is retried
    rather than taken as the end, or the digest would silently drop the rest of the week. Rate limiting
    (HTTP 429), server errors and network failures are retried as :func:`~journal_club.digest.http.get_with_retries`
    describes.

    Args:
        query: An arXiv ``search_query``.
        get: Fetches a URL and returns the body; replaced in tests.
        sleep: Waits between requests; replaced in tests.
        retries: How many times to retry a page that came back empty or failed before giving up.

    Returns:
        The papers, de-duplicated by arXiv ID, in the order the API returned them.

    Raises:
        ArxivError: If a page within the reported total stays empty after *retries* retries.
        urllib.error.URLError: If a request still fails after *retries* retries, or fails with a status
            that retrying cannot fix.
        TimeoutError: If a request still times out after *retries* retries.
    """
    papers: dict[str, Paper] = {}
    start = 0
    while True:
        total, page = _fetch_page(_page_url(query, start), start, get=get, sleep=sleep, retries=retries)
        for paper in page:
            papers.setdefault(paper.arxiv_id, paper)
        start += len(page)
        if not page or start >= total:
            return list(papers.values())
