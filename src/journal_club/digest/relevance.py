"""Which papers count as gravitational-wave science.

Each source is queried for the arXiv categories in :data:`CATEGORIES`, a wide net; the keyword filter then
keeps the papers about gravitational waves. Edit the tuples below to widen or narrow what reaches the
digest.
"""

from __future__ import annotations

import re

from journal_club.digest.paper import Paper

#: arXiv categories queried. Gravitational-wave papers are spread across these.
CATEGORIES = ("gr-qc", "astro-ph.HE", "astro-ph.CO", "astro-ph.IM", "physics.ins-det")

#: Phrases that mark a paper as gravitational-wave science, matched case-insensitively against the title
#: and abstract.
GW_PHRASES = (
    r"gravitational[- ]?waves?",
    r"gravitational radiation",
    r"binary black holes?",
    r"binary neutron stars?",
    r"black[- ]hole (binary|binaries)",
    r"neutron[- ]star (binary|binaries)",
    r"compact[- ](binary|binaries)",
    r"compact[- ]object mergers?",
    r"kilonova(e|s)?",
    r"quasi-?normal modes?",
    r"ringdown",
    r"inspiral",
    r"post-Newtonian",
    r"numerical relativity",
    r"extreme[- ]mass[- ]ratio",
    r"Einstein Telescope",
    r"Cosmic Explorer",
    r"pulsar timing",
    r"tidal deformabilit(y|ies)",
    r"waveforms?",
)

#: Detector and collaboration names, matched case-sensitively as whole words, so that e.g. a surname
#: "Lisa" or "pta" inside a word does not count. Virgo is left out: "Virgo cluster" is common in
#: astro-ph.CO, and a Virgo detector paper says "gravitational wave" anyway.
GW_ACRONYMS = ("LIGO", "KAGRA", "LVK", "LISA", "TianQin", "Taiji", "DECIGO", "NANOGrav", "EPTA", "IPTA", "PTA")

_GW_PHRASE = re.compile("|".join(GW_PHRASES), re.IGNORECASE)
_GW_ACRONYM = re.compile(r"\b(" + "|".join(GW_ACRONYMS) + r")\b")


def is_gravitational_wave(paper: Paper) -> bool:
    """Return whether *paper*'s title or abstract marks it as gravitational-wave science.

    Args:
        paper: The paper.

    Returns:
        True if a phrase from :data:`GW_PHRASES` or an acronym from :data:`GW_ACRONYMS` occurs.
    """
    text = f"{paper.title}\n{paper.abstract}"
    return bool(_GW_PHRASE.search(text) or _GW_ACRONYM.search(text))
