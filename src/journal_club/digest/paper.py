"""Papers, and the file that hands a week of them from the fetch step to the summariser.

That file is the whole of what Claude reads, so it is kept small on purpose. Author lists are cut to the
first :data:`MAX_LISTED_AUTHORS` names (a collaboration paper can list well over a thousand), and
:meth:`WeeklyPapers.save` refuses to write a week larger than :data:`MAX_PAPERS` papers or
:data:`MAX_PAPERS_FILE_CHARS` characters. Refusing, rather than trimming, is deliberate: a week that large
means the keyword filter or the sources changed, and a person should look before it is summarised.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from journal_club.digest.window import Window

#: Authors kept per paper. The digest names the first author; the rest only cost context.
MAX_LISTED_AUTHORS = 3
#: The most papers a week may hold. A normal week has about 80 gravitational-wave papers.
MAX_PAPERS = 200
#: The longest the papers file may be, in characters. A normal week is about 150,000 (roughly 40,000
#: tokens), so this allows about two and a half times that.
MAX_PAPERS_FILE_CHARS = 400_000


class ContextBudgetError(ValueError):
    """A week of papers is too large to hand to the summariser."""


def cap_authors(names: Iterable[str]) -> tuple[tuple[str, ...], int]:
    """Return the first :data:`MAX_LISTED_AUTHORS` of *names*, and how many there were in all.

    Args:
        names: The author names, in order.

    Returns:
        The names kept, and the full count.
    """
    names = tuple(names)
    return names[:MAX_LISTED_AUTHORS], len(names)


@dataclass(frozen=True)
class Paper:
    """One arXiv paper.

    Attributes:
        arxiv_id: The unversioned arXiv identifier, e.g. ``2610.01234``.
        title: The title, with whitespace collapsed.
        authors: The first :data:`MAX_LISTED_AUTHORS` author names, in order; see :func:`cap_authors`.
        author_count: How many authors the paper has in all.
        abstract: The abstract, with whitespace collapsed.
        primary_category: The primary arXiv category, e.g. ``gr-qc``.
        categories: Every category the paper is listed in, primary included.
        published: When the first version was submitted, as an ISO 8601 timestamp (arXiv) or date (INSPIRE).
    """

    arxiv_id: str
    title: str
    authors: tuple[str, ...]
    author_count: int
    abstract: str
    primary_category: str
    categories: tuple[str, ...]
    published: str

    def __post_init__(self) -> None:
        """Hold the author list to its cap, so an uncapped list cannot reach the summariser.

        Raises:
            ValueError: If more than :data:`MAX_LISTED_AUTHORS` authors are listed, or *author_count* is
                fewer than the authors listed.
        """
        if len(self.authors) > MAX_LISTED_AUTHORS:
            raise ValueError(
                f"{self.arxiv_id} lists {len(self.authors)} authors; use cap_authors() to keep at most "
                f"{MAX_LISTED_AUTHORS}"
            )
        if self.author_count < len(self.authors):
            raise ValueError(f"{self.arxiv_id} counts {self.author_count} authors but lists {len(self.authors)}")

    @property
    def url(self) -> str:
        """The paper's abstract page on arXiv."""
        return f"https://arxiv.org/abs/{self.arxiv_id}"

    def to_dict(self) -> dict:
        """Return the paper as a JSON-ready dictionary, including its :attr:`url`.

        Returns:
            The fields, plus ``url``.
        """
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": list(self.authors),
            "author_count": self.author_count,
            "abstract": self.abstract,
            "primary_category": self.primary_category,
            "categories": list(self.categories),
            "published": self.published,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Paper:
        """Return the paper *data* describes, as written by :meth:`to_dict`.

        Args:
            data: The dictionary; a ``url`` key is accepted and ignored, since it is derived.

        Returns:
            The paper.
        """
        return cls(
            arxiv_id=data["arxiv_id"],
            title=data["title"],
            authors=tuple(data["authors"]),
            author_count=data["author_count"],
            abstract=data["abstract"],
            primary_category=data["primary_category"],
            categories=tuple(data["categories"]),
            published=data["published"],
        )


@dataclass(frozen=True)
class WeeklyPapers:
    """The papers in one digest window.

    Attributes:
        window: The submission dates covered.
        papers: The papers, in the order they were fetched.
        source: Which source they were fetched from, e.g. ``arXiv`` or ``INSPIRE-HEP``.
    """

    window: Window
    papers: tuple[Paper, ...]
    source: str

    def to_json(self) -> str:
        """Return the papers file's contents.

        The file also carries the issue title, so that the workflow reads it rather than rebuilding it.

        Returns:
            The JSON text.
        """
        document = {
            "title": self.window.title,
            "window": {"first": self.window.first.isoformat(), "last": self.window.last.isoformat()},
            "source": self.source,
            "papers": [paper.to_dict() for paper in self.papers],
        }
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        """Write the papers to *path* as JSON, for the summariser to read, if they fit the context budget.

        Args:
            path: Where to write. Nothing is written if the week is refused.

        Raises:
            ContextBudgetError: If the week holds more than :data:`MAX_PAPERS` papers, or the file would be
                longer than :data:`MAX_PAPERS_FILE_CHARS` characters.
        """
        if len(self.papers) > MAX_PAPERS:
            raise ContextBudgetError(
                f"{len(self.papers)} papers is more than the {MAX_PAPERS} a digest may summarise; check the "
                f"keyword filter and the sources before raising MAX_PAPERS"
            )
        text = self.to_json()
        if len(text) > MAX_PAPERS_FILE_CHARS:
            raise ContextBudgetError(
                f"the papers file would be {len(text):,} characters, more than the {MAX_PAPERS_FILE_CHARS:,} the "
                f"summariser may read; check for unusually long records before raising MAX_PAPERS_FILE_CHARS"
            )
        path.write_text(text, encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WeeklyPapers:
        """Read papers written by :meth:`save`.

        Args:
            path: The JSON file.

        Returns:
            The papers and their window.
        """
        document = json.loads(path.read_text(encoding="utf-8"))
        window = Window(
            first=dt.date.fromisoformat(document["window"]["first"]),
            last=dt.date.fromisoformat(document["window"]["last"]),
        )
        return cls(
            window=window,
            papers=tuple(Paper.from_dict(paper) for paper in document["papers"]),
            source=document["source"],
        )
