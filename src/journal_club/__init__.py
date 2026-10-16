"""Top-level package for journal_club: tooling for the group's journal club."""

from __future__ import annotations

# PEP 810: defer importlib.metadata (loaded by version.py) on 3.15+.
# Ignored on 3.13/3.14 where the lazy import machinery does not exist.
__lazy_modules__ = ["journal_club.version"]

from journal_club.version import __version__

__all__ = ["__version__"]
