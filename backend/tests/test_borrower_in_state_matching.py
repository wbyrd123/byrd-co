"""Byrd & CO — Lender matching wired for `borrower_in_state_required`.

Verifies the new geography-of-borrower check that some community banks require
(borrower must live in the same state the bank lends in). The check reads the
first sponsor's `state` field and falls back to the property state when no
sponsor state has been captured yet.

Scope:
  * lender does NOT require borrower in state → flag has no effect
  * lender requires + sponsor state matches      → adds a fit reason
  * lender requires + sponsor state DIFFERS      → adds a red miss reason,
                                                    demoting the lender's score
  * lender requires + no sponsor state captured  → falls back to property state
"""
import sys
sys.path.insert(0, "/app/backend")
import server  # noqa: E402


TX_BANK = {
    "id": "l-tx", "name": "Small Town TX Bank",
    "geography": ["TX"], "property_types": ["Multifamily"],
    "min_loan": 500_000, "max_loan": 5_000_000,
    "borrower_in_state_required": True,
}
NATIONAL = {
    "id": "l-nat", "name": "National Lender",
    "geography": ["NATIONWIDE"], "property_types": ["Multifamily"],
    "min_loan": 500_000, "max_loan": 5_000_000,
    "borrower_in_state_required": False,
}


def _scen(prop_state, sponsor_state=None, loan_amount=1_000_000):
    s = {
        "property_info": {"state": prop_state, "property_type": "Multifamily"},
        "loan_request": {"loan_amount": loan_amount},
    }
    if sponsor_state is not None:
        s["sponsors"] = [{"name": "Test Sponsor", "state": sponsor_state}]
    return s


def _match(scen, lender):
    return next(m for m in server.match_lenders(scen, [lender]) if m["lender"]["id"] == lender["id"])


class TestBorrowerInStateMatching:

    def test_lender_without_flag_ignores_borrower_state(self):
        m = _match(_scen("TX", "NY"), NATIONAL)
        # National lender doesn't require in-state — no reason mentioning "borrower in"
        assert not any("borrower in" in r.lower() for r in m["fits"] + m["misses"])
        assert m["verdict"] == "fit"

    def test_sponsor_in_bank_state_becomes_fit(self):
        m = _match(_scen("TX", "TX"), TX_BANK)
        assert any("borrower in TX" in r for r in m["fits"])
        assert not any("requires borrower" in r for r in m["misses"])
        assert m["verdict"] == "fit"

    def test_sponsor_out_of_state_becomes_hard_miss(self):
        m = _match(_scen("TX", "NY"), TX_BANK)
        assert any("requires borrower in TX" in r and "NY" in r for r in m["misses"])
        assert m["verdict"] == "partial"

    def test_multi_state_bank_only_needs_one_match(self):
        bank = {**TX_BANK, "geography": ["TX", "OK", "LA"]}
        # Sponsor in LA → fits
        m = _match({**_scen("TX", "LA")}, bank)
        assert any("borrower in LA" in r for r in m["fits"])
        # Sponsor in NY → miss
        m2 = _match({**_scen("TX", "NY")}, bank)
        assert any("requires borrower in" in r and "NY" in r for r in m2["misses"])

    def test_no_sponsor_state_falls_back_to_property_state(self):
        # No sponsors at all — property state is TX, matches bank's TX geography
        m = _match(_scen("TX"), TX_BANK)
        assert any("borrower in TX" in r for r in m["fits"])
        assert not any("requires borrower" in r for r in m["misses"])

    def test_multi_sponsor_takes_first_state_captured(self):
        scen = {
            "property_info": {"state": "TX", "property_type": "Multifamily"},
            "loan_request": {"loan_amount": 1_000_000},
            "sponsors": [
                {"name": "Sponsor A"},                  # no state
                {"name": "Sponsor B", "state": "NY"},   # this one wins
                {"name": "Sponsor C", "state": "TX"},   # never reached
            ],
        }
        m = _match(scen, TX_BANK)
        # Should treat borrower as NY → miss
        assert any("requires borrower in TX" in r and "NY" in r for r in m["misses"])
