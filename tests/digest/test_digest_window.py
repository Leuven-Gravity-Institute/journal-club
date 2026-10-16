"""The submission window: consecutive weekly runs must cover consecutive weeks, with neither gap nor overlap."""

from __future__ import annotations

import datetime as dt

import pytest

from journal_club.digest.window import LAG_DAYS, WINDOW_DAYS, Window

pytestmark = pytest.mark.unit


class TestForRun:
    """Which dates a run on a given day covers."""

    def test_a_monday_run_covers_friday_to_thursday_of_the_week_before(self) -> None:
        """Monday 2026-10-19: Thursday 10-15's late submissions were announced Sunday evening, before the run."""
        assert Window.for_run(dt.date(2026, 10, 19)) == Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15))

    @pytest.mark.parametrize("weeks", range(60))
    def test_consecutive_weekly_runs_tile_time(self, weeks: int) -> None:
        """Over sixty weeks, across a year boundary and a leap day, each window starts the day after the last."""
        monday = dt.date(2027, 10, 4) + dt.timedelta(weeks=weeks)
        previous = Window.for_run(monday - dt.timedelta(weeks=1))
        current = Window.for_run(monday)
        assert current.first == previous.last + dt.timedelta(days=1)
        assert (current.last - current.first).days == WINDOW_DAYS - 1

    @pytest.mark.parametrize("weekday", range(7))
    def test_every_day_of_a_week_builds_that_weeks_digest(self, weekday: int) -> None:
        """A Tuesday backup run or a Friday manual re-run gives Monday's window, and so Monday's issue title."""
        monday = dt.date(2026, 10, 19)
        assert Window.for_run(monday + dt.timedelta(days=weekday)) == Window.for_run(monday)

    @pytest.mark.parametrize("weekday", range(7))
    def test_every_paper_in_the_window_has_been_announced_by_the_run(self, weekday: int) -> None:
        """The window ends at least the lag before the run, whichever day the run is on."""
        run_date = dt.date(2026, 10, 19) + dt.timedelta(days=weekday)
        assert (run_date - Window.for_run(run_date).last).days >= LAG_DAYS + 1

    def test_a_sunday_belongs_to_the_week_before(self) -> None:
        """Sunday's Monday is six days earlier, so the week rolls over on Monday, as the schedule does."""
        assert Window.for_run(dt.date(2026, 10, 25)) == Window.for_run(dt.date(2026, 10, 19))
        assert Window.for_run(dt.date(2026, 10, 26)) != Window.for_run(dt.date(2026, 10, 19))


class TestWindow:
    """The window value itself."""

    def test_a_window_cannot_end_before_it_starts(self) -> None:
        """A reversed window would query nothing and publish an empty digest without complaint."""
        with pytest.raises(ValueError, match="ends"):
            Window(dt.date(2026, 10, 15), dt.date(2026, 10, 9))

    def test_a_single_day_window_is_allowed(self) -> None:
        """Both ends are inclusive, so first == last is one day, not an empty range."""
        day = dt.date(2026, 10, 9)
        assert Window(day, day).first == day

    def test_the_title_names_both_ends(self) -> None:
        """The title is what the workflow uses to avoid opening a second issue for the same week."""
        assert Window(dt.date(2026, 10, 9), dt.date(2026, 10, 15)).title == "Paper digest: 2026-10-09 to 2026-10-15"


class TestFromTitle:
    """Reading the window back from an issue title, to find the digests a new one supersedes."""

    @pytest.mark.parametrize("weeks", range(-3, 4))
    def test_the_title_round_trips(self, weeks: int) -> None:
        """`from_title` is the inverse of `title`, whatever the week."""
        window = Window.for_run(dt.date(2026, 10, 19) + dt.timedelta(weeks=weeks))
        assert Window.from_title(window.title) == window

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """A title pasted with a stray space still names its week."""
        assert Window.from_title(" Paper digest: 2026-10-09 to 2026-10-15 \n") == Window(
            dt.date(2026, 10, 9), dt.date(2026, 10, 15)
        )

    @pytest.mark.parametrize(
        "title",
        [
            "Paper digest: 2026-10-02 to 2026-10-08 (old layout)",
            "Re: Paper digest: 2026-10-02 to 2026-10-08",
            "Paper digest: 2026-10-02",
            "Paper digest: 2026-13-02 to 2026-13-08",
            "Paper digest: 2026-10-08 to 2026-10-02",
            "Bug: fetch fails",
            "",
        ],
    )
    def test_other_titles_are_not_digests(self, title: str) -> None:
        """A renamed digest, another issue, an impossible date or a reversed week is left alone."""
        assert Window.from_title(title) is None
