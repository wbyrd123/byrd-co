"""Byrd & CO — Match-reasons regression tests.

Ensures every dimension the UI now renders as a chip is populated correctly by
`match_lenders()`, in particular the state/geography check the broker cited:
"they must lend in the state where the property is located".
"""
import sys
sys.path.insert(0, "/app/backend")
from server import match_lenders   # noqa: E402


def _scen(**overrides):
    base = {
        "property_info": {"property_type": "Industrial", "state": "TX"},
        "loan_request": {"loan_amount": 5_000_000},
        "financials": {},
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def _find(matches, lid):
    return next(m for m in matches if m["lender"]["id"] == lid)


class TestGeographyReason:
    def test_lender_out_of_state_gets_miss_chip(self):
        scen = _scen()
        lender = {"id": "L1", "name": "CA Only",
                  "property_types": ["Industrial"], "geography": ["CA"],
                  "min_loan": 1_000_000, "max_loan": 25_000_000}
        m = _find(match_lenders(scen, [lender]), "L1")
        assert any("not in TX" in x for x in m["misses"])
        assert m["verdict"] in ("miss", "partial")

    def test_lender_in_state_gets_fit_chip(self):
        scen = _scen()
        lender = {"id": "L2", "name": "TX Bank",
                  "property_types": ["Industrial"], "geography": ["TX"],
                  "min_loan": 1_000_000, "max_loan": 25_000_000}
        m = _find(match_lenders(scen, [lender]), "L2")
        assert any("lends in TX" in x for x in m["fits"])

    def test_nationwide_matches_any_state(self):
        scen = _scen()
        lender = {"id": "L3", "name": "Nationwide LLC",
                  "property_types": ["Industrial"], "geography": ["NATIONWIDE"],
                  "min_loan": 1_000_000, "max_loan": 25_000_000}
        m = _find(match_lenders(scen, [lender]), "L3")
        assert any("lends in TX" in x for x in m["fits"])

    def test_no_state_declared_no_geo_reason(self):
        """Deal with a state, but the lender has no geography declared. We DO NOT want
        a false 'not in TX' miss — should skip that dimension silently."""
        scen = _scen()
        lender = {"id": "L4", "name": "Undeclared",
                  "property_types": ["Industrial"], "geography": [],
                  "min_loan": 1_000_000, "max_loan": 25_000_000}
        m = _find(match_lenders(scen, [lender]), "L4")
        assert not any("in TX" in x or "not in TX" in x for x in m["fits"] + m["misses"])


class TestFullChipBundle:
    def test_specialist_gets_full_fit_bundle(self):
        """The card the broker sees for a full-fit specialist should include: top-level
        property type, sub-type specialty, geography, and size."""
        scen = {
            "property_info": {"property_type": "Industrial",
                              "property_subtype": "Manufacturing Heavy Industrial",
                              "state": "TX"},
            "loan_request": {"loan_amount": 5_000_000},
            "financials": {},
        }
        lender = {"id": "L", "name": "Heavy Iron", "property_types": ["Industrial"],
                  "property_subtypes": ["Manufacturing Heavy Industrial"],
                  "geography": ["TX"], "min_loan": 1_000_000, "max_loan": 25_000_000}
        m = _find(match_lenders(scen, [lender]), "L")
        assert m["verdict"] == "fit"
        joined = " ".join(m["fits"]).lower()
        assert "industrial" in joined                        # top-level type
        assert "manufacturing heavy industrial" in joined    # specialty
        assert "tx" in joined                                # state
        assert "size fits" in joined                         # size band
