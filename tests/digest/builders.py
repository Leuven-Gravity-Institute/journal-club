"""Builders for papers and arXiv API responses, shared by the digest and CLI tests."""

from __future__ import annotations

import email.message
import json
import urllib.error
from collections.abc import Callable

from journal_club.digest.paper import Paper


def make_paper(arxiv_id: str = "2610.00001", title: str = "A title", abstract: str = "An abstract.") -> Paper:
    """Return a paper with every field filled in.

    Args:
        arxiv_id: The arXiv ID.
        title: The title.
        abstract: The abstract.

    Returns:
        The paper.
    """
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=("A. Author", "B. Author"),
        author_count=2,
        abstract=abstract,
        primary_category="gr-qc",
        categories=("gr-qc", "astro-ph.HE"),
        published="2026-10-08T17:59:59Z",
    )


def atom_entry(arxiv_id: str, title: str = "A title", abstract: str = "An abstract.", *, authors: int = 2) -> str:
    """Return one ``<entry>`` as the arXiv API writes it, for version 2 of *arxiv_id*.

    Args:
        arxiv_id: The unversioned arXiv ID.
        title: The title, written as given.
        abstract: The abstract; it is padded and wrapped the way the API does.
        authors: How many authors to list; the first two are "A. Author" and "B. Author".

    Returns:
        The XML fragment.
    """
    names = ["A. Author", "B. Author", *(f"Author {index}" for index in range(3, authors + 1))][:authors]
    author_xml = "".join(f"<author><name>{name}</name></author>" for name in names)
    return f"""
    <entry>
      <id>http://arxiv.org/abs/{arxiv_id}v2</id>
      <published>2026-10-08T17:59:59Z</published>
      <title>{title}</title>
      <summary>  {abstract}
        continued  </summary>
      {author_xml}
      <arxiv:primary_category term="gr-qc"/>
      <category term="gr-qc"/>
      <category term="astro-ph.HE"/>
    </entry>"""


def atom_feed(total: int, *entries: str) -> str:
    """Return an arXiv API response page.

    Args:
        total: The query's total result count, as the API reports it.
        *entries: The page's entries, from :func:`atom_entry`.

    Returns:
        The XML document.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <opensearch:totalResults>{total}</opensearch:totalResults>
      {"".join(entries)}
    </feed>"""


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    """Return the error ``urllib`` raises for an HTTP *code* response.

    Args:
        code: The HTTP status.
        retry_after: The ``Retry-After`` header, if the response carries one.

    Returns:
        The exception, not raised.
    """
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://export.arxiv.org/api/query", code, "error", headers, None)


def scripted_get(*responses: str | Exception) -> tuple[Callable[[str], str], list[str]]:
    """Return a fake ``get`` that plays *responses* in order, and the list of URLs it was called with.

    Args:
        *responses: Response bodies, or exceptions to raise in their place.

    Returns:
        The fake, and the URLs it has been asked for so far.
    """
    remaining = list(responses)
    urls: list[str] = []

    def get(url: str) -> str:
        urls.append(url)
        response = remaining.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    return get, urls


def inspire_record(
    arxiv_id: str | None = "2610.00001",
    *,
    title: str = "A title",
    categories: tuple[str, ...] = ("gr-qc", "astro-ph.HE"),
) -> dict:
    """Return one hit as INSPIRE's literature API writes it, limited to the fields the digest asks for.

    Args:
        arxiv_id: The arXiv ID, or None for a record with no arXiv eprint (e.g. a journal-only paper).
        title: The arXiv title.
        categories: The arXiv categories, primary first.

    Returns:
        The hit, with its ``metadata``.
    """
    metadata: dict = {
        "titles": [{"source": "arXiv", "title": title}],
        "abstracts": [{"source": "arXiv", "value": "An  abstract.\n continued"}],
        "authors": [{"full_name": "Author, A."}, {"full_name": "Author, B."}],
        "preprint_date": "2026-10-08",
    }
    if arxiv_id is not None:
        metadata["arxiv_eprints"] = [{"categories": list(categories), "value": arxiv_id}]
    return {"id": "1", "metadata": metadata}


def inspire_page(total: int, *hits: dict, next_url: str | None = None) -> str:
    """Return one page of INSPIRE's literature search.

    Args:
        total: The search's total hit count, as INSPIRE reports it.
        *hits: The page's hits, from :func:`inspire_record`.
        next_url: The link to the next page, which INSPIRE omits on the last one.

    Returns:
        The JSON document.
    """
    links = {"self": "https://inspirehep.net/api/literature?page=1"}
    if next_url is not None:
        links["next"] = next_url
    return json.dumps({"hits": {"hits": list(hits), "total": total}, "links": links})
