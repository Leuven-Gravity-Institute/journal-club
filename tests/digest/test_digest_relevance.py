"""Which papers count as gravitational-wave science."""

from __future__ import annotations

import pytest
from builders import make_paper

from journal_club.digest.relevance import is_gravitational_wave

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "title",
    [
        "Gravitational-wave constraints on primordial black holes",
        "Gravitational waves from supernovae",
        "Detected by LIGO and Virgo",
        "A stochastic background in NANOGrav data",
        "LISA sources",
        "Quasinormal modes of Kerr black holes",
        "Quasi-normal modes of Kerr black holes",
        "Black-hole binaries in AGN discs",
        "Compact binaries with eccentricity",
        "Kilonovae from neutron star mergers",
        "Science with the Einstein Telescope",
    ],
)
def test_gravitational_wave_papers_are_kept(title: str) -> None:
    """Each family of phrases and acronyms keeps the papers it is there for."""
    assert is_gravitational_wave(make_paper(title=title, abstract=""))


@pytest.mark.parametrize(
    "title",
    [
        "Galaxy kinematics in the Virgo cluster",
        "The lisa-shaped galaxy",
        "Adaptive optics for telescopes",
        "LIGOs",
    ],
)
def test_other_papers_are_dropped(title: str) -> None:
    """Acronyms count only as whole, case-sensitive words; "Virgo" alone does not count."""
    assert not is_gravitational_wave(make_paper(title=title, abstract=""))


def test_the_abstract_is_searched_as_well_as_the_title() -> None:
    """Many GW papers have titles that do not say so."""
    assert is_gravitational_wave(make_paper(title="Neutron star crusts", abstract="... inspiral of ..."))
