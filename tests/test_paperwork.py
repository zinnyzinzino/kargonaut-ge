"""The paperwork agent's Python side, scored against the answer keys (no Gemini).

The Georgian demo set (demo_documents/ge) is in the repository; the anonymized US test set is private and
only exists on the owner's computer, so its loads are added when present and skipped otherwise.
"""
import pytest

import run_paperwork_eval as paper
from paperwork.addresses import compare_addresses, same_company
from paperwork.ship_readings import SHIPPED


@pytest.mark.parametrize("a, b, want", paper.ADDRESS_CASES,
                         ids=[f"{i}-{want}" for i, (_, _, want) in enumerate(paper.ADDRESS_CASES)])
def test_address_comparison(a, b, want):
    """ "Ln" = "Lane", ZIP+4 with or without a dash, a cut-off name: not mistakes. A different street is."""
    got = compare_addresses(a, b)
    assert got["result"] == want, got["reasons"]


@pytest.mark.parametrize("a, b, want", paper.COMPANY_CASES,
                         ids=[f"{i}-{'same' if want else 'different'}" for i, (_, _, want) in enumerate(paper.COMPANY_CASES)])
def test_company_comparison(a, b, want):
    assert same_company(a, b) == want


def test_every_answer_key_load_is_checked_right():
    """Each load's must_flag problems are caught, with no false alarms (6 Georgian demo loads, + 4 US if present)."""
    assert paper.run_pairs(verbose=False) == 0


def test_planted_mistakes_are_caught():
    """Mistakes planted into clean documents (another carrier, another address, ...) are all reported."""
    assert paper.run_planted() == 0


def test_georgian_and_english_give_the_same_findings():
    assert paper.run_wording_test() == 0


def test_shipped_readings_match_the_answer_keys(tmp_path):
    """What ships with the app (Gemini's saved readings of the demo documents) scores 100% against the
    answer keys: the deployed demo never shows a reading the eval didn't check. No Gemini calls."""
    failures = paper.run_gemini(tmp_path, None, allow_calls=False, verbose=False, only_set="ge", shipped=SHIPPED)
    assert failures == 0
