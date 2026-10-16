"""The week of arXiv submissions a digest covers.

The window is a fixed week of *submissions*, lagged so that each one has been announced before it is
queried. arXiv announces Sunday to Thursday evenings (US Eastern) and its API only returns announced
papers, so a window ending at the moment of the run would miss the weekend's submissions this week and,
being past them, next week as well.

Every run belongs to the week of the Monday on or before it, and covers Friday to Thursday of the week
before that Monday: Thursday's late submissions are announced on Sunday evening, before Monday. So
consecutive weeks are covered with neither gap nor overlap, and a backup run later in the week (or a
manual re-run) builds the same digest as Monday's, with the same issue title.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

#: Full days between the last day of the window and the week's Monday, so every paper has been announced.
LAG_DAYS = 3
#: Days in a window.
WINDOW_DAYS = 7

#: The issue title of a window, as :attr:`Window.title` writes it.
_TITLE = re.compile(r"^Paper digest: (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class Window:
    """A range of submission dates, both ends inclusive.

    Attributes:
        first: The first submission day.
        last: The last submission day.
    """

    first: dt.date
    last: dt.date

    def __post_init__(self) -> None:
        """Reject a window that ends before it starts.

        Raises:
            ValueError: If *last* is before *first*.
        """
        if self.last < self.first:
            raise ValueError(f"the window ends ({self.last}) before it starts ({self.first})")

    @classmethod
    def for_run(cls, run_date: dt.date) -> Window:
        """Return the window covered by a digest built on *run_date*.

        Args:
            run_date: The UTC date the digest is built on.

        Returns:
            The :data:`WINDOW_DAYS` days ending :data:`LAG_DAYS` full days before the Monday on or before
            *run_date*.
        """
        monday = run_date - dt.timedelta(days=run_date.weekday())
        last = monday - dt.timedelta(days=LAG_DAYS + 1)
        return cls(first=last - dt.timedelta(days=WINDOW_DAYS - 1), last=last)

    @property
    def title(self) -> str:
        """The title of the digest issue for this window."""
        return f"Paper digest: {self.first.isoformat()} to {self.last.isoformat()}"

    @classmethod
    def from_title(cls, title: str) -> Window | None:
        """Return the window a digest issue's *title* names, the inverse of :attr:`title`.

        Args:
            title: An issue title.

        Returns:
            The window, or None if *title* is not a digest title: another issue, or one renamed by hand.
        """
        matched = _TITLE.match(title.strip())
        if matched is None:
            return None
        try:
            return cls(first=dt.date.fromisoformat(matched[1]), last=dt.date.fromisoformat(matched[2]))
        except ValueError:
            return None
