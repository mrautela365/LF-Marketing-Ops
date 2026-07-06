"""Unit tests for src/lib/form_builder.py — no API calls needed."""

from src.lib.form_builder import build_field_groups


class TestBuildFieldGroups:
    def test_empty_fields_returns_empty(self):
        result = build_field_groups([])
        assert result == []

    def test_single_email_field(self):
        result = build_field_groups([{"name": "Email", "type": "email", "required": True}])
        assert len(result) == 1
        group = result[0]
        assert group["groupType"] == "default_group"
        field = group["fields"][0]
        assert field["name"] == "email"
        assert field["fieldType"] == "email"
        assert field["required"] is True
        assert field["label"] == "Email"

    def test_builtin_first_name_mapping(self):
        result = build_field_groups([{"name": "First Name", "type": "text", "required": True}])
        field = result[0]["fields"][0]
        assert field["name"] == "firstname"

    def test_builtin_last_name_mapping(self):
        result = build_field_groups([{"name": "Last Name", "type": "text", "required": False}])
        field = result[0]["fields"][0]
        assert field["name"] == "lastname"
        assert field["required"] is False

    def test_country_field_maps_to_dropdown(self):
        result = build_field_groups([{"name": "Country", "type": "country", "required": True}])
        field = result[0]["fields"][0]
        assert field["fieldType"] == "dropdown"
        assert field["name"] == "country"

    def test_multiple_fields_in_single_group(self):
        fields = [
            {"name": "First Name", "type": "text", "required": True},
            {"name": "Last Name", "type": "text", "required": True},
            {"name": "Email", "type": "email", "required": True},
            {"name": "Company", "type": "text", "required": False},
        ]
        result = build_field_groups(fields)
        assert len(result) == 1
        assert len(result[0]["fields"]) == 4

    def test_select_field_with_options(self):
        result = build_field_groups([{
            "name": "Job Title",
            "type": "select",
            "required": False,
            "options": ["Engineer", "Manager", "Director"],
        }])
        field = result[0]["fields"][0]
        assert field["fieldType"] == "dropdown"
        assert len(field["options"]) == 3
        assert field["options"][0]["label"] == "Engineer"
        assert field["options"][0]["value"] == "engineer"

    def test_custom_field_is_slugified(self):
        result = build_field_groups([{"name": "Special Project Name", "type": "text", "required": False}])
        field = result[0]["fields"][0]
        assert field["name"] == "special_project_name"

    def test_unknown_type_defaults_to_text(self):
        result = build_field_groups([{"name": "Mystery Field", "type": "unknown_type", "required": False}])
        field = result[0]["fields"][0]
        assert field["fieldType"] == "single_line_text"
