"""
Maps the simplified field spec used in the web UI / MCP tools
to the HubSpot Marketing v3 Forms API fieldGroups schema.
"""

from __future__ import annotations

from typing import Any

# Map of simple field type names → HubSpot fieldType + objectTypeId
_FIELD_TYPE_MAP: dict[str, dict[str, str]] = {
    "text": {"fieldType": "single_line_text", "objectTypeId": "0-1"},
    "email": {"fieldType": "email", "objectTypeId": "0-1"},
    "phone": {"fieldType": "phone_number", "objectTypeId": "0-1"},
    "textarea": {"fieldType": "multi_line_text", "objectTypeId": "0-1"},
    "select": {"fieldType": "dropdown", "objectTypeId": "0-1"},
    "checkbox": {"fieldType": "single_checkbox", "objectTypeId": "0-1"},
    "number": {"fieldType": "number", "objectTypeId": "0-1"},
    "country": {"fieldType": "dropdown", "objectTypeId": "0-1"},
    "date": {"fieldType": "date", "objectTypeId": "0-1"},
}

# Well-known HubSpot internal field names that map to built-in contact properties
_BUILTIN_NAMES: dict[str, str] = {
    "first name": "firstname",
    "firstname": "firstname",
    "last name": "lastname",
    "lastname": "lastname",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "company": "company",
    "country": "country",
    "country/region": "country",
    "job title": "jobtitle",
    "jobtitle": "jobtitle",
    "website": "website",
    "message": "message",
}


def _resolve_property_name(label: str, field_type: str) -> str:
    """
    Return the HubSpot internal property name for a field.
    Built-in fields use known names; custom fields are slugified.
    """
    normalized = label.strip().lower()
    if normalized in _BUILTIN_NAMES:
        return _BUILTIN_NAMES[normalized]
    # Slugify: lowercase, replace spaces/special chars with underscores
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug


def build_field_groups(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert a list of simplified field specs to HubSpot v3 Forms API fieldGroups.

    Input field spec:
      {
        "name": "First Name",       # human label
        "type": "text",             # one of keys in _FIELD_TYPE_MAP
        "required": true,
        "options": ["A", "B"]       # only for select/dropdown fields
      }

    Returns HubSpot fieldGroups:
      [
        {
          "groupType": "default_group",
          "richTextType": "text",
          "fields": [{ "objectTypeId": "0-1", "name": ..., "fieldType": ..., "required": ... }]
        }
      ]
    """
    hs_fields = []
    for field in fields:
        label: str = field.get("name", "").strip()
        field_type: str = field.get("type", "text").lower()
        required: bool = bool(field.get("required", False))
        options: list[str] = field.get("options", [])

        type_info = _FIELD_TYPE_MAP.get(field_type, _FIELD_TYPE_MAP["text"])
        property_name = _resolve_property_name(label, field_type)

        hs_field: dict[str, Any] = {
            "objectTypeId": type_info["objectTypeId"],
            "name": property_name,
            "label": label,
            "fieldType": type_info["fieldType"],
            "required": required,
            "hidden": False,
        }

        # Email fields require a validation block; add an empty one for all fields
        # to satisfy HubSpot's schema validation
        if type_info["fieldType"] == "email":
            hs_field["validation"] = {
                "blockedEmailDomains": [],
                "useDefaultBlockList": False,
            }

        if options:
            hs_field["options"] = [
                {"label": opt, "value": opt.lower().replace(" ", "_")} for opt in options
            ]

        hs_fields.append(hs_field)

    if not hs_fields:
        return []

    return [
        {
            "groupType": "default_group",
            "richTextType": "text",
            "fields": hs_fields,
        }
    ]
