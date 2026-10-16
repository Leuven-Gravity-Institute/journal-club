"""Turning the summariser's digest into the body of the weekly issue.

The digest is held to the papers that were fetched: an arXiv ID that was not fetched stops publication,
and a fetched paper the digest left out is appended, so the issue always lists every paper in the window.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from journal_club.digest.paper import Paper
from journal_club.digest.window import Window

#: GitHub refuses an issue body longer than this many characters.
MAX_ISSUE_BODY = 65536

#: An arXiv identifier, optionally versioned: new-style (``2610.01234``) or legacy (``gr-qc/0507014``,
#: ``math.GT/0309136``). Only new-style IDs can be fetched for a recent window, but a legacy one must still be
#: recognised, or a digest citing an older paper would get past the check. Legacy numbers are ``YYMMNNN``
#: from 1991 to 2007, which keeps paths such as ``src/1234567`` from counting.
_ARXIV_ID = re.compile(
    r"\b(\d{4}\.\d{4,5}|[a-z]+(?:-[a-z]+)?(?:\.[A-Z]{2})?/(?:9[1-9]|0[0-7])(?:0[1-9]|1[0-2])\d{3})(?:v\d+)?\b"
)
#: An @-mention. Abstracts are untrusted text, and a digest that quoted ``@someone`` would ping them.
_MENTION = re.compile(r"@(?=[\w-])")


class DigestRejectedError(ValueError):
    """The digest cannot be published as an issue."""


def cited_ids(text: str) -> set[str]:
    """Return the unversioned arXiv IDs that occur in *text*.

    Args:
        text: Any text.

    Returns:
        The IDs, without version suffixes.
    """
    return set(_ARXIV_ID.findall(text))


def build_issue_body(papers: Iterable[Paper], digest: str, *, note: str | None = None) -> str:
    """Return the issue body: *digest*, held to *papers* and completed with any paper it left out.

    Args:
        papers: The papers that were fetched.
        digest: The Markdown the summariser wrote.
        note: A closing remark for the readers, e.g. that the papers came from the fallback source.

    Returns:
        The issue body.

    Raises:
        DigestRejectedError: If the digest is empty, cites an arXiv ID that was not fetched, or is too
            long for a GitHub issue.
    """
    papers = list(papers)
    if not digest.strip():
        raise DigestRejectedError("the digest is empty")
    cited = cited_ids(digest)
    unknown = sorted(cited - {paper.arxiv_id for paper in papers})
    if unknown:
        raise DigestRejectedError(
            f"the digest cites arXiv IDs that were not fetched: {', '.join(unknown)}. "
            f"They are either invented or outside the window; refusing to publish them."
        )
    body = digest.rstrip() + "\n"
    missing = [paper for paper in papers if paper.arxiv_id not in cited]
    if missing:
        lines = [f"- [{paper.title}]({paper.url})" for paper in missing]
        body += "\n## 📎 Also this week\n\n" + "\n".join(lines) + "\n"
    if note:
        # A GitHub alert, so the caveat stands out from the digest above it.
        body += f"\n> [!NOTE]\n> {note}\n"
    body = _MENTION.sub("@\u200b", body)
    if len(body) > MAX_ISSUE_BODY:
        raise DigestRejectedError(f"the issue body is {len(body)} characters; GitHub accepts at most {MAX_ISSUE_BODY}")
    return body


def superseded_issues(open_issues: Iterable[dict], title: str) -> list[int]:
    """Return the open digest issues that the digest titled *title* supersedes.

    A digest supersedes those for earlier weeks only. Comparing weeks rather than creation order means a
    manual run for a past week does not close the current digest, and a duplicate for the same week is
    left for a person to sort out.

    Args:
        open_issues: The open issues, as ``gh issue list --json number,title`` returns them.
        title: The new digest's title.

    Returns:
        The issue numbers to close, oldest week first.

    Raises:
        ValueError: If *title* is not a digest title.
    """
    new = Window.from_title(title)
    if new is None:
        raise ValueError(f"{title!r} is not a digest title")
    older = []
    for issue in open_issues:
        window = Window.from_title(issue["title"])
        if window is not None and window.first < new.first:
            older.append((window.first, int(issue["number"])))
    return [number for _, number in sorted(older)]
