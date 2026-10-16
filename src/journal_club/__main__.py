"""Main entry point for the journal_club package."""

from __future__ import annotations

if __name__ == "__main__":
    from journal_club.utils.log import setup_logger

    setup_logger(print_version=True)
