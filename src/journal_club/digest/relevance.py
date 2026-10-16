"""Which papers count as gravitational-wave science.

Each source is queried for the arXiv categories in :data:`CATEGORIES`, a wide net; the keyword filter then
keeps the papers about gravitational waves. Edit the tuples below to widen or narrow what reaches the
digest.

Terms come in two strengths. A strong term (:data:`GW_PHRASES`, :data:`GW_ACRONYMS`) is enough on its own. A
weak term (:data:`WEAK_GW_PHRASES`) is gravitational-wave vocabulary that other fields use too -- lightning
"waveforms", the "compact binary" phase of stellar evolution -- so it counts only together with a second,
different weak term, or with gravity named in the text ("gravitational", "graviton").
"""

from __future__ import annotations

import re

from journal_club.digest.paper import Paper

#: arXiv categories queried. Gravitational-wave papers are spread across these.
CATEGORIES = ("gr-qc", "astro-ph.HE", "astro-ph.CO", "astro-ph.IM", "physics.ins-det")

#: Phrases that mark a paper as gravitational-wave science on their own, matched case-insensitively against
#: the title and abstract. "Gravitational wave function(s)" is the quantum-cosmology term, not a wave, and
#: the parameterized post-Newtonian (PPN) formalism is a solar-system and lensing test, not binary dynamics.
GW_PHRASES = (
    r"gravitational[- ]?waves?(?![- ]?functions?\b)",
    r"gravitational radiation",
    r"binary black holes?",
    r"binary neutron stars?",
    r"black[- ]hole (binary|binaries)",
    r"neutron[- ]star (binary|binaries)",
    r"compact[- ]object mergers?",
    r"kilonova(e|s)?",
    r"quasi-?normal modes?",
    r"ringdown",
    r"numerical relativity",
    r"(?<!parameterized )(?<!parametrized )(?<!parameterised )(?<!parametrised )post-Newtonian",
    r"\bsirens?\b",
    r"extreme[- ]mass[- ]ratio",
    r"Einstein Telescope",
    r"Cosmic Explorer",
    r"pulsar timing",
    r"tidal deformabilit(y|ies)",
)

#: Phrases that point to gravitational-wave science but are used elsewhere too, matched case-insensitively.
#: "Inspiral" matches the noun only, not a star "inspiralling" through a companion's envelope.
WEAK_GW_PHRASES = (
    r"waveforms?",
    r"inspirals?\b",
    r"compact[- ](binary|binaries)",
)

#: Gravity named outright, which turns a single weak term into a match.
GRAVITY_NAMED = r"\bgravit(ational|ons?)\b"

#: Detector and collaboration names, matched case-sensitively as whole words, so that e.g. a surname
#: "Lisa" or "pta" inside a word does not count. Virgo is left out: "Virgo cluster" is common in
#: astro-ph.CO, and a Virgo detector paper says "gravitational wave" anyway.
GW_ACRONYMS = (
    "LIGO",
    "KAGRA",
    "LVK",
    "GWTC",
    "LISA",
    "TianQin",
    "Taiji",
    "DECIGO",
    "NANOGrav",
    "EPTA",
    "IPTA",
    "PTA",
)

_GW_PHRASE = re.compile("|".join(GW_PHRASES), re.IGNORECASE)
_GW_ACRONYM = re.compile(r"\b(" + "|".join(GW_ACRONYMS) + r")\b")
_WEAK_GW_PHRASES = tuple(re.compile(phrase, re.IGNORECASE) for phrase in WEAK_GW_PHRASES)
_GRAVITY_NAMED = re.compile(GRAVITY_NAMED, re.IGNORECASE)


def is_gravitational_wave(paper: Paper) -> bool:
    """Return whether *paper*'s title or abstract marks it as gravitational-wave science.

    Args:
        paper: The paper.

    Returns:
        True if a strong term occurs, two different weak terms do, or one weak term does with gravity named.
    """
    text = f"{paper.title}\n{paper.abstract}"
    if _GW_PHRASE.search(text) or _GW_ACRONYM.search(text):
        return True
    weak = sum(1 for phrase in _WEAK_GW_PHRASES if phrase.search(text))
    return weak >= 2 or (weak == 1 and _GRAVITY_NAMED.search(text) is not None)
