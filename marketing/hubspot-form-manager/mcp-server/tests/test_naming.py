"""Unit tests for src/lib/naming.py — no API calls needed."""

import pytest
from src.lib.naming import derive_form_name, parse_name_parts, suggest_form_name


class TestParseNameParts:
    def test_standard_lf_events_name(self):
        parts = parse_name_parts("26Q1 - LF Events - MCP NA 2026")
        assert parts["quarter"] == "26Q1"
        assert parts["team"] == "LF Events"
        assert parts["event"] == "MCP NA"
        assert parts["year"] == "2026"

    def test_aaif_name(self):
        parts = parse_name_parts("26Q2 - AAIF - AI Summit Tokyo 2026")
        assert parts["quarter"] == "26Q2"
        assert parts["team"] == "AAIF"
        assert parts["event"] == "AI Summit Tokyo"
        assert parts["year"] == "2026"

    def test_nonstandard_name_returns_full_as_event(self):
        parts = parse_name_parts("Some Random Form Name")
        assert parts["quarter"] == ""
        assert parts["event"] == "Some Random Form Name"

    def test_extra_whitespace(self):
        parts = parse_name_parts("  26Q3  -  LF Events  -  OpenSSF Day  2026  ")
        assert parts["quarter"] == "26Q3"
        assert parts["team"] == "LF Events"
        assert parts["event"] == "OpenSSF Day"
        assert parts["year"] == "2026"


class TestDeriveFormName:
    def test_basic_derivation(self):
        result = derive_form_name("26Q1 - LF Events - MCP NA 2026", "CloudNativeCon Europe", "26Q2")
        assert result == "26Q2 - LF Events - CloudNativeCon Europe 2026"

    def test_different_team(self):
        result = derive_form_name("26Q1 - AAIF - AI Dev World 2026", "AI Summit Mumbai", "26Q3")
        assert result == "26Q3 - AAIF - AI Summit Mumbai 2026"

    def test_explicit_year_override(self):
        result = derive_form_name("26Q1 - LF Events - MCP NA 2026", "DockerCon", "27Q1", "2027")
        assert result == "27Q1 - LF Events - DockerCon 2027"

    def test_year_inferred_from_quarter(self):
        # No reference form year, no explicit year — infer from quarter prefix
        result = derive_form_name("No Standard - Format", "KubeCon", "27Q2")
        assert "2027" in result
        assert "KubeCon" in result

    def test_invalid_quarter_raises(self):
        with pytest.raises(ValueError, match="Invalid quarter format"):
            derive_form_name("26Q1 - LF Events - MCP NA 2026", "Event", "Q2-26")

    def test_preserves_team_spacing(self):
        result = derive_form_name("26Q1 - LF Events - MCP NA 2026", "New Event Name", "26Q4")
        assert result.startswith("26Q4 - LF Events - New Event Name")


class TestSuggestFormName:
    def test_basic(self):
        result = suggest_form_name("DockerCon 2026", "LF Events", "26Q2", "2026")
        assert result == "26Q2 - LF Events - DockerCon 2026 2026"

    def test_invalid_quarter(self):
        with pytest.raises(ValueError):
            suggest_form_name("Event", "Team", "invalid", "2026")
