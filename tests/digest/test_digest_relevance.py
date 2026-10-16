"""Which papers count as gravitational-wave science.

The cases come from real weeks: the "dropped" ones all reached a digest under the first keyword filter.
"""

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
        "Kilonovae from neutron star mergers",
        "Science with the Einstein Telescope",
        "Ringdown tests of general relativity",
        "Puncture evolution in numerical relativity",
    ],
)
def test_strong_terms_are_enough_on_their_own(title: str) -> None:
    """Each family of strong phrases and acronyms keeps the papers it is there for."""
    assert is_gravitational_wave(make_paper(title=title, abstract=""))


@pytest.mark.parametrize(
    "abstract",
    [
        # A spectral-siren population paper that never writes "gravitational wave".
        "The joint compact-binary mass plane. Applied to GWTC-5.0, ... spectral-siren cosmology.",
        "Dark sirens with galaxy catalogues.",
        # Post-Newtonian theory is binary dynamics, the heart of waveform modelling.
        "We derive the equations of motion for the binary up to second post-Newtonian order.",
        "Post-Newtonian secular dynamics of hierarchical triples.",
        # One weak term, with gravity named: gravitational amplitudes and their waveforms.
        "Gravitational scattering amplitudes and the leading high-energy collinear waveform.",
        "Graviton exchange and the inspiral of two bodies.",
        # Two different weak terms.
        "Eccentric waveforms for the inspiral of comparable-mass systems.",
    ],
)
def test_papers_without_the_words_gravitational_wave_are_still_kept(abstract: str) -> None:
    """Population, siren and post-Newtonian papers often never say "gravitational wave"."""
    assert is_gravitational_wave(make_paper(title="A title", abstract=abstract))


@pytest.mark.parametrize(
    ("title", "abstract"),
    [
        # "waveforms" of lightning.
        (
            "BOLT: Imaging Lightning and Terrestrial Gamma-ray Flashes",
            "firmware modifications to acquire and stream multi-second waveforms.",
        ),
        # The quantum-cosmology "wave function", spelt with "gravitational" in front.
        (
            "Connected Geometries in Gravitational Path Integrals",
            "the normalization of gravitational wave functions can be substantially alleviated",
        ),
        ("No-boundary proposals", "the gravitational-wave function of the universe"),
        # The PPN parameter from lensing, in each spelling.
        ("Testing GR with Binary Lens Microlensing", "measure the parameterized post-Newtonian (PPN) parameter"),
        ("Solar-system tests", "bounds on the parametrized post-Newtonian parameters"),
        ("Solar-system tests", "bounds on the parameterised post-Newtonian parameters"),
        # Stellar evolution: a star "inspiralling" through a wind, and the "compact binary" formation phase.
        (
            "Unravelling the Nature of AT 2025abao",
            "a poorly understood phase in compact binary formation ... companion inspiralling through the wind",
        ),
        # Other fields' vocabulary.
        ("Galaxy kinematics in the Virgo cluster", ""),
        ("The lisa-shaped galaxy", ""),
        ("Adaptive optics for telescopes", ""),
        ("LIGOs", ""),
        ("CNN-based position reconstruction", "using the digitised detector waveforms"),
    ],
)
def test_other_papers_are_dropped(title: str, abstract: str) -> None:
    """A single weak term without gravity named, or another field's homonym, does not count."""
    assert not is_gravitational_wave(make_paper(title=title, abstract=abstract))


def test_the_abstract_is_searched_as_well_as_the_title() -> None:
    """Many GW papers have titles that do not say so."""
    assert is_gravitational_wave(make_paper(title="Neutron star crusts", abstract="... ringdown of the remnant ..."))


def test_a_strong_term_elsewhere_overrides_a_homonym() -> None:
    """Excluding "gravitational wave function" must not drop a paper that also means gravitational waves."""
    abstract = "the gravitational wave function of the universe predicts a gravitational-wave background"
    assert is_gravitational_wave(make_paper(title="A title", abstract=abstract))
