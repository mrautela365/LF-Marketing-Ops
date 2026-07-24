"""
Pure-logic tests for master_list.py — no HubSpot/network calls.
Run: pytest backend/audience_builder/test_master_list.py -v
"""
import pytest

import audience_tools
from audience_builder.master_list import (
    build_in_list_or_branch,
    build_master_list_name,
    compose_master_list_from_ids,
)


class TestBuildInListOrBranch:
    def test_single_id(self):
        branch = build_in_list_or_branch(["123"])
        assert branch["filterBranchType"] == "OR"
        assert len(branch["filterBranches"]) == 1
        and_branch = branch["filterBranches"][0]
        assert and_branch["filterBranchType"] == "AND"
        assert and_branch["filters"] == [
            {"filterType": "IN_LIST", "listId": "123", "operator": "IN_LIST"}
        ]

    def test_multiple_ids_preserve_order(self):
        branch = build_in_list_or_branch(["111", "222", "333"])
        ids = [b["filters"][0]["listId"] for b in branch["filterBranches"]]
        assert ids == ["111", "222", "333"]

    def test_dedup(self):
        branch = build_in_list_or_branch(["111", "222", "111", "222"])
        ids = [b["filters"][0]["listId"] for b in branch["filterBranches"]]
        assert ids == ["111", "222"]

    def test_blank_and_whitespace_ids_skipped(self):
        branch = build_in_list_or_branch(["111", "", "  ", "222"])
        ids = [b["filters"][0]["listId"] for b in branch["filterBranches"]]
        assert ids == ["111", "222"]

    def test_empty_input(self):
        branch = build_in_list_or_branch([])
        assert branch["filterBranches"] == []

    def test_non_string_ids_coerced(self):
        branch = build_in_list_or_branch([111, 222])
        ids = [b["filters"][0]["listId"] for b in branch["filterBranches"]]
        assert ids == ["111", "222"]


class TestBuildMasterListName:
    def test_with_brand_and_event(self):
        name = build_master_list_name(brand_short="CNCF", event_name="KubeCon NA",
                                       event_dates=["2026-08-15"])
        assert name == "26Q3 - CNCF - KubeCon NA - Master"

    def test_quarter_boundaries(self):
        assert build_master_list_name(brand_short="LF", event_name="Event",
                                       event_dates=["2026-01-01"]).startswith("26Q1")
        assert build_master_list_name(brand_short="LF", event_name="Event",
                                       event_dates=["2026-04-01"]).startswith("26Q2")
        assert build_master_list_name(brand_short="LF", event_name="Event",
                                       event_dates=["2026-12-31"]).startswith("26Q4")

    def test_missing_brand_no_double_dash(self):
        name = build_master_list_name(event_name="KubeCon NA", event_dates=["2026-08-15"])
        assert " -  - " not in name
        assert name == "26Q3 - KubeCon NA - Master"

    def test_missing_event_name_no_double_dash(self):
        name = build_master_list_name(brand_short="CNCF", event_dates=["2026-08-15"])
        assert " -  - " not in name
        assert name == "26Q3 - CNCF - Master"

    def test_no_dates_falls_back_to_today_quarter(self):
        name = build_master_list_name(brand_short="CNCF", event_name="KubeCon NA")
        assert name.endswith("CNCF - KubeCon NA - Master")
        assert name[2] == "Q"

    def test_nothing_provided_still_returns_generic_name(self):
        name = build_master_list_name()
        assert name.endswith("Audience - Master")
        assert name[2] == "Q"


class TestComposeMasterListNameCollision:
    def test_retries_with_timestamp_on_name_collision(self, monkeypatch):
        calls = []

        def fake_create(name, filter_branch):
            calls.append(name)
            if len(calls) == 1:
                raise RuntimeError("HubSpot 400: a list with this name already exists")
            return {"listId": "999", "name": name, "size": 42, "hubspot_url": "https://example.com"}

        monkeypatch.setattr(audience_tools, "hubspot_create_list", fake_create)

        result = compose_master_list_from_ids(["111", "222"], name="Existing Name")

        assert len(calls) == 2
        assert calls[0] == "Existing Name"
        assert calls[1] != "Existing Name"
        assert calls[1].startswith("Existing Name (")
        assert result["name"] == calls[1]
        assert result["list_id"] == "999"

    def test_reraises_non_collision_errors(self, monkeypatch):
        def fake_create(name, filter_branch):
            raise RuntimeError("HubSpot 500: internal error")

        monkeypatch.setattr(audience_tools, "hubspot_create_list", fake_create)

        with pytest.raises(RuntimeError, match="internal error"):
            compose_master_list_from_ids(["111"], name="Whatever")
