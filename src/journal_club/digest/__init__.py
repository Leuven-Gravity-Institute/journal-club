"""The weekly paper digest: fetch a week of gravitational-wave papers, and publish a summary of them.

The weekly workflow runs two steps around one where Claude summarises the papers:

1. ``journal_club digest fetch`` queries arXiv (or, if arXiv is unavailable, INSPIRE-HEP) for the week's
   :class:`~journal_club.digest.window.Window` and writes the gravitational-wave papers to a JSON file.
2. ``journal_club digest finalize`` checks the digest Claude wrote against that file and writes the issue
   body.
"""

from __future__ import annotations

from journal_club.digest.arxiv import ArxivError
from journal_club.digest.http import FetchError
from journal_club.digest.inspire import InspireError
from journal_club.digest.issue import DigestRejectedError, build_issue_body
from journal_club.digest.paper import ContextBudgetError, Paper, WeeklyPapers
from journal_club.digest.relevance import is_gravitational_wave
from journal_club.digest.window import Window

__all__ = [
    "ArxivError",
    "ContextBudgetError",
    "DigestRejectedError",
    "FetchError",
    "InspireError",
    "Paper",
    "WeeklyPapers",
    "Window",
    "build_issue_body",
    "is_gravitational_wave",
]
