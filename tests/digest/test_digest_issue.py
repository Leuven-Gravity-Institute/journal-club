"""What the digest is allowed to publish: only fetched papers, every fetched paper, and nothing GitHub refuses."""

from __future__ import annotations

import pytest
from builders import make_paper

from journal_club.digest.issue import (
    MAX_ISSUE_BODY,
    DigestRejectedError,
    build_issue_body,
    cited_ids,
    superseded_issues,
)

pytestmark = pytest.mark.unit


class TestCitedIds:
    """Finding arXiv IDs in the digest."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("see 2610.01234", {"2610.01234"}),
            ("see 2610.01234v3", {"2610.01234"}),
            ("[x](https://arxiv.org/abs/2610.01234v1)", {"2610.01234"}),
            ("old-style 0704.1234 and 5-digit 2610.12345", {"0704.1234", "2610.12345"}),
            ("legacy gr-qc/0507014", {"gr-qc/0507014"}),
            ("legacy astro-ph/0612345v3, versioned", {"astro-ph/0612345"}),
            ("subject class math.GT/0309136", {"math.GT/0309136"}),
            ("https://arxiv.org/abs/hep-th/9711200v2", {"hep-th/9711200"}),
            ("a ratio 3/1234567 or a path src/1234567", set()),
            ("no IDs, 3.14159 or 12345.6789", set()),
        ],
    )
    def test_ids_are_found_with_versions_dropped(self, text: str, expected: set[str]) -> None:
        """A versioned citation counts as citing the paper; numbers that are not IDs do not."""
        assert cited_ids(text) == expected


class TestBuildIssueBody:
    """The issue body."""

    def test_a_complete_digest_is_published_as_written(self) -> None:
        """Nothing is added when every paper is already covered."""
        digest = "## Highlights\n\n- [2610.00001](https://arxiv.org/abs/2610.00001v1) is good.\n"
        assert build_issue_body([make_paper("2610.00001")], digest) == digest

    def test_a_paper_the_digest_left_out_is_appended(self) -> None:
        """The issue always lists the whole week, even when the summary skipped a paper."""
        papers = [make_paper("2610.00001"), make_paper("2610.00002", title="Missed")]
        body = build_issue_body(papers, "About 2610.00001.\n")
        assert body == ("About 2610.00001.\n\n## 📎 Also this week\n\n- [Missed](https://arxiv.org/abs/2610.00002)\n")

    def test_an_id_that_was_not_fetched_stops_the_digest(self) -> None:
        """An invented or out-of-window paper is never published, even alongside real ones."""
        with pytest.raises(DigestRejectedError, match=r"not fetched: 2610\.99999"):
            build_issue_body([make_paper("2610.00001")], "2610.00001 and 2610.99999v3")

    def test_a_legacy_id_that_was_not_fetched_stops_the_digest(self) -> None:
        """Every paper in a recent window has a new-style ID, so any legacy one was not fetched."""
        with pytest.raises(DigestRejectedError, match=r"not fetched: gr-qc/0507014"):
            build_issue_body([make_paper("2610.00001")], "2610.00001 builds on gr-qc/0507014v2.")

    @pytest.mark.parametrize("digest", ["", " \n\t"])
    def test_an_empty_digest_stops_the_digest(self, digest: str) -> None:
        """A failed summariser must not produce an issue that is only the fallback list."""
        with pytest.raises(DigestRejectedError, match="empty"):
            build_issue_body([make_paper("2610.00001")], digest)

    def test_mentions_are_defused(self) -> None:
        """Abstracts are untrusted; a quoted @handle must not ping anyone. Emails are defused too, harmlessly."""
        body = build_issue_body([make_paper("2610.00001")], "2610.00001, ping @someone and @org/team; mail a@b.c\n")
        assert "@someone" not in body
        assert "@org/team" not in body
        assert "@\u200bsomeone" in body
        assert "a@\u200bb.c" in body

    def test_a_body_at_the_limit_is_accepted(self) -> None:
        """The limit is inclusive."""
        digest = "2610.00001 " + "x" * (MAX_ISSUE_BODY - len("2610.00001 ") - 1)
        assert len(build_issue_body([make_paper("2610.00001")], digest)) == MAX_ISSUE_BODY

    def test_a_body_github_would_refuse_stops_the_digest(self) -> None:
        """Failing here gives a clear message instead of an opaque API error at the publish step."""
        with pytest.raises(DigestRejectedError, match="at most"):
            build_issue_body([make_paper("2610.00001")], "2610.00001 " + "x" * MAX_ISSUE_BODY)

    def test_a_note_closes_the_issue_after_the_appended_papers(self) -> None:
        """The fallback note is the last thing a reader sees, set apart from the digest."""
        papers = [make_paper("2610.00001"), make_paper("2610.00002", title="Missed")]
        body = build_issue_body(papers, "About 2610.00001.\n", note="From the fallback.")
        assert body.endswith("(https://arxiv.org/abs/2610.00002)\n\n> [!NOTE]\n> From the fallback.\n")

    def test_the_note_counts_towards_the_limit(self) -> None:
        """A digest that fits only without the note is still refused, rather than truncated by GitHub."""
        digest = "2610.00001 " + "x" * (MAX_ISSUE_BODY - len("2610.00001 ") - 1)
        with pytest.raises(DigestRejectedError, match="at most"):
            build_issue_body([make_paper("2610.00001")], digest, note="n")

    def test_an_empty_week_with_a_digest_is_published(self) -> None:
        """The workflow skips empty weeks, but the function itself has nothing to append."""
        assert build_issue_body([], "Nothing this week.\n") == "Nothing this week.\n"


class TestSupersededIssues:
    """Which open digests a new one closes, so that only the latest stays open."""

    NEW = "Paper digest: 2026-10-09 to 2026-10-15"

    def test_open_digests_for_earlier_weeks_are_closed_oldest_first(self) -> None:
        """The usual Monday: last week's digest (and any older one left open) is closed."""
        issues = [
            {"number": 12, "title": "Paper digest: 2026-10-02 to 2026-10-08"},
            {"number": 9, "title": "Paper digest: 2026-09-25 to 2026-10-01"},
            {"number": 13, "title": self.NEW},
        ]
        assert superseded_issues(issues, self.NEW) == [9, 12]

    def test_a_later_week_stays_open(self) -> None:
        """A manual run for a past week must not close the current digest."""
        issues = [{"number": 20, "title": "Paper digest: 2026-10-16 to 2026-10-22"}]
        assert superseded_issues(issues, self.NEW) == []

    def test_the_same_week_is_not_closed(self) -> None:
        """The new digest itself, or a duplicate of its week, is left for a person to sort out."""
        issues = [{"number": 13, "title": self.NEW}, {"number": 14, "title": self.NEW}]
        assert superseded_issues(issues, self.NEW) == []

    def test_issues_that_are_not_digests_are_ignored(self) -> None:
        """A renamed digest or an unrelated issue is never closed by the workflow."""
        issues = [
            {"number": 4, "title": "Paper digest: 2026-10-02 to 2026-10-08 (old layout)"},
            {"number": 6, "title": "Bug: fetch fails"},
        ]
        assert superseded_issues(issues, self.NEW) == []

    def test_numbers_given_as_strings_are_accepted(self) -> None:
        """`gh` returns numbers, but the function should not care how they were serialised."""
        assert superseded_issues([{"number": "12", "title": "Paper digest: 2026-10-02 to 2026-10-08"}], self.NEW) == [
            12
        ]

    def test_a_new_title_that_is_not_a_digest_is_refused(self) -> None:
        """Comparing against an unreadable title would close nothing or everything; refuse instead."""
        with pytest.raises(ValueError, match="not a digest title"):
            superseded_issues([], "Paper digest: soon")
