"""
/api/hubspot/* REST routes — called by the web UI.
These reuse the same underlying logic as the MCP tools.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ..lib.form_builder import build_field_groups
from ..lib.hubspot_client import hs_delete, hs_get, hs_patch, hs_post
from ..models.hubspot import (
    ApiResponse,
    CreateEmailRequest,
    CreateFormRequest,
    DeleteFormsRequest,
    UpdateFormDetailsRequest,
    UpdateNotificationsRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hubspot")


# ── READ ENDPOINTS ──────────────────────────────────────────────────────────

@router.get("/portal")
async def get_portal() -> ApiResponse:
    try:
        data = await hs_get("/account-info/v3/details")
        return ApiResponse(success=True, data={
            "portal_id": data.get("portalId"),
            "company_name": data.get("companyName", ""),
        })
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/forms/search")
async def search_forms(q: str = Query("", alias="q"), limit: int = 20) -> ApiResponse:
    try:
        params = {"limit": min(limit, 100)}
        data = await hs_get("/marketing/v3/forms/", params=params)
        results = data.get("results", []) if isinstance(data, dict) else []
        if q:
            q_lower = q.lower()
            results = [f for f in results if q_lower in f.get("name", "").lower()]
        return ApiResponse(success=True, data=[
            {"id": f.get("id"), "name": f.get("name"), "formType": f.get("formType")}
            for f in results
        ])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/forms/{form_id}")
async def get_form(form_id: str) -> ApiResponse:
    try:
        data = await hs_get(f"/marketing/v3/forms/{form_id}")
        return ApiResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/subscription-types")
async def get_subscription_types() -> ApiResponse:
    try:
        data = await hs_get("/communication-preferences/v3/definitions")
        definitions = data.get("subscriptionDefinitions", []) if isinstance(data, dict) else []
        return ApiResponse(success=True, data=[
            {"id": d.get("id"), "name": d.get("name"), "description": d.get("description", "")}
            for d in definitions if d.get("isActive", True)
        ])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/brands")
async def get_brands() -> ApiResponse:
    """
    Return a list of brand / business unit names for the Create Form dropdown.

    Resolution order:
      1. HubSpot Business Units API  (/business-units/v3/business-units/)
      2. HubSpot Teams API           (/settings/v3/users/teams)
      3. Unique team tokens parsed from existing form names  ([YYQ#] - <TEAM> - …)
    """
    # ── Attempt 1: Business Units (HubSpot Enterprise) ───────────────────────
    try:
        data = await hs_get("/business-units/v3/business-units/")
        units = data.get("results", []) if isinstance(data, dict) else []
        if units:
            names = sorted({u.get("name", "").strip() for u in units if u.get("name", "").strip()})
            if names:
                return ApiResponse(success=True, data={"brands": names, "source": "business_units"})
    except Exception:
        pass  # not on enterprise plan — try next

    # ── Attempt 2: Teams ──────────────────────────────────────────────────────
    try:
        data = await hs_get("/settings/v3/users/teams")
        teams = data.get("results", []) if isinstance(data, dict) else []
        if teams:
            names = sorted({t.get("name", "").strip() for t in teams if t.get("name", "").strip()})
            if names:
                return ApiResponse(success=True, data={"brands": names, "source": "teams"})
    except Exception:
        pass

    # ── Attempt 3: Parse team tokens from existing form names ─────────────────
    import re
    try:
        data = await hs_get("/marketing/v3/forms/", params={"limit": 100})
        forms = data.get("results", []) if isinstance(data, dict) else []
        # Capture the token between the first and second " - " separators
        pattern = re.compile(r"^\d{2}Q\d\s*-\s*(.+?)\s*-\s*.+$")
        teams_found: set[str] = set()
        for f in forms:
            m = pattern.match(f.get("name", ""))
            if m:
                token = m.group(1).strip()
                # Sanity-check: brand tokens should be short and look like real names
                # (drop anything over 50 chars or containing non-printable characters)
                if token and len(token) <= 50 and token.isprintable():
                    teams_found.add(token)
        if teams_found:
            return ApiResponse(
                success=True,
                data={"brands": sorted(teams_found), "source": "form_names"},
            )
    except Exception:
        pass

    # ── Nothing found — return empty list so UI falls back to free-text ────────
    return ApiResponse(success=True, data={"brands": [], "source": "none"})


@router.get("/properties")
async def get_contact_properties() -> ApiResponse:
    """
    Return all active HubSpot contact properties for the field picker.
    Maps HubSpot field types to the simplified types used by the form builder.
    """
    # Map HubSpot property types → form builder field types
    _type_map = {
        "string":          "text",
        "enumeration":     "select",
        "bool":            "checkbox",
        "number":          "number",
        "date":            "date",
        "datetime":        "date",
        "phone_number":    "phone",
    }
    # Map specific field-type overrides by fieldType key
    _fieldtype_map = {
        "email":              "email",
        "phone_number":       "phone",
        "textarea":           "textarea",
        "text":               "text",
        "select":             "select",
        "radio":              "select",
        "checkbox":           "checkbox",
        "booleancheckbox":    "checkbox",
        "number":             "number",
        "date":               "date",
    }
    try:
        data = await hs_get("/crm/v3/properties/contacts", params={"limit": 500})
        props = data.get("results", []) if isinstance(data, dict) else []
        results = []
        for p in props:
            if p.get("hidden") or p.get("calculated") or p.get("externalOptions"):
                continue
            hs_field_type = p.get("fieldType", "")
            hs_type       = p.get("type", "string")
            form_type = (
                _fieldtype_map.get(hs_field_type)
                or _type_map.get(hs_type)
                or "text"
            )
            results.append({
                "name":       p.get("name"),
                "label":      p.get("label"),
                "type":       form_type,
                "fieldType":  hs_field_type,
                "groupName":  p.get("groupName", ""),
            })
        # Sort: standard contact props first, then alphabetically by label
        results.sort(key=lambda x: (
            0 if x["groupName"] == "contactinformation" else 1,
            x["label"].lower()
        ))
        return ApiResponse(success=True, data=results)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/workflows/search")
async def search_workflows(q: str = Query("", alias="q")) -> ApiResponse:
    try:
        data = await hs_get("/automation/v4/flows/", params={"limit": 50})
        flows = data.get("results", []) if isinstance(data, dict) else []
        if q:
            q_lower = q.lower()
            flows = [f for f in flows if q_lower in f.get("name", "").lower()]
        return ApiResponse(success=True, data=[
            {"id": f.get("id"), "name": f.get("name")} for f in flows
        ])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── WRITE ENDPOINTS ──────────────────────────────────────────────────────────

@router.post("/forms/create")
async def create_form(req: CreateFormRequest) -> ApiResponse:
    """
    Full form creation: creates the HubSpot form, and optionally the autoresponder
    email and workflow enrollment in a single operation.
    """
    if not req.brand:
        return ApiResponse(
            success=False,
            error=(
                "Brand/business unit is required. "
                "Please specify the brand (e.g. LF Events, AAIF, OpenSSF) and try again."
            ),
        )

    if not req.subscription_type_id:
        return ApiResponse(
            success=False,
            error=(
                "Subscription type is required. "
                "Select a subscription type from the dropdown and try again."
            ),
        )


    try:
        # Step 1: Create the form
        field_groups = build_field_groups([f.model_dump() for f in req.fields])

        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Per the HubSpot legacy forms API schema, createdAt, updatedAt, and archived
        # are required top-level fields on every form create request.
        form_payload: dict = {
            "name": req.name,
            "formType": "hubspot",
            "archived": False,
            "createdAt": _now,
            "updatedAt": _now,
            "fieldGroups": field_groups,
            "configuration": {
                "language": "en",
                "postSubmitAction": {
                    "type": "thank_you",
                    "value": req.thank_you_message,
                },
                "notifyContactOwner": False,
                "createNewContactForNewEmail": False,
                "prePopulateKnownValues": True,
                **({"notifyRecipients": [str(e) for e in req.notification_emails]}
                   if req.notification_emails else {}),
            },
            "displayOptions": {
                "submitButtonText": req.submit_button_text,
            },
        }

        # Subscription type → legalConsentOptions
        if req.subscription_type_id:
            privacy_text = (
                req.privacy_text
                if getattr(req, "privacy_text", None)
                else (
                    f"<p>By submitting this form, I consent to receive marketing emails from "
                    f"{req.brand} regarding their events, training, "
                    f"research, developments, and related announcements. I understand that I "
                    f"can unsubscribe at any time using the links in the footers of the emails "
                    f"I receive. "
                    f"<a href='https://www.linuxfoundation.org/legal/privacy-policy' "
                    f"target='_blank' rel='nofollow noopener noreferrer'>Privacy Policy</a></p>"
                )
            )
            form_payload["legalConsentOptions"] = {
                "type": "legitimate_interest",
                "subscriptionTypeIds": [int(req.subscription_type_id)],
                "lawfulBasis": "lead",
                "privacyText": privacy_text,
            }

        form_data = await hs_post("/marketing/v3/forms/", json=form_payload)
        form_id = form_data.get("id")

        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        result: dict = {
            "form_id": form_id,
            "form_name": form_data.get("name"),
            "brand": req.brand,
            "hubspot_form_url": f"https://app.hubspot.com/forms/{portal_id}/editor/{form_id}",
            "email_id": None,
            "email_preview_url": None,
            "workflow_status": None,
        }

        # Step 2: Create autoresponder email (if requested)
        if req.autoresponder_subject and req.autoresponder_from_email:
            email_payload = {
                "name": f"Autoresponder — {req.name}",
                "subject": req.autoresponder_subject,
                "fromName": req.autoresponder_from_name or "",
                "replyTo": str(req.autoresponder_from_email),
                "emailBody": req.autoresponder_body_html or f"<p>Thank you for registering for {req.name}.</p>",
                "emailType": "AUTOMATED_EMAIL",
                "isTransactional": True,
            }
            email_data = await hs_post("/marketing/v3/emails/", json=email_payload)
            email_id = email_data.get("id")
            result["email_id"] = email_id
            result["email_preview_url"] = (
                f"https://app.hubspot.com/email/{portal_id}/edit/{email_id}/settings"
            )

        # Step 3: Enroll in workflow (if requested)
        if req.workflow_name_query:
            wf_data = await hs_get("/automation/v4/flows/", params={"limit": 50})
            flows = wf_data.get("results", []) if isinstance(wf_data, dict) else []
            q_lower = req.workflow_name_query.lower()
            matches = [f for f in flows if q_lower in f.get("name", "").lower()]
            if matches:
                wf = matches[0]
                try:
                    await hs_patch(
                        f"/automation/v4/flows/{wf['id']}/enrollmentCriteria",
                        json={"triggers": [{"type": "FORM_SUBMISSION", "formId": form_id}]},
                    )
                    result["workflow_status"] = f"Enrolled in: {wf.get('name')}"
                except Exception as we:
                    result["workflow_status"] = f"Manual enrollment needed — {wf.get('name')} (error: {we})"
            else:
                result["workflow_status"] = f"Workflow '{req.workflow_name_query}' not found"

        return ApiResponse(success=True, data=result)

    except Exception as e:
        logger.exception("Error creating HubSpot form")
        return ApiResponse(success=False, error=str(e))


@router.patch("/forms/{form_id}/update")
async def update_form_details(form_id: str, req: UpdateFormDetailsRequest) -> ApiResponse:
    """
    Update editable form details: name, submit button text, thank-you message,
    and/or notification email recipients.
    Only fields that are explicitly provided (not None) are sent to HubSpot.
    """
    try:
        patch: dict = {}

        if req.name is not None:
            patch["name"] = req.name

        if req.submit_button_text is not None:
            patch.setdefault("displayOptions", {})["submitButtonText"] = req.submit_button_text

        if req.thank_you_message is not None:
            patch.setdefault("configuration", {})["postSubmitAction"] = {
                "type": "thank_you",
                "value": req.thank_you_message,
            }

        if req.notification_emails is not None:
            patch.setdefault("configuration", {})["notifyRecipients"] = [
                str(e) for e in req.notification_emails
            ]

        if not patch:
            return ApiResponse(success=False, error="No fields to update were provided.")

        data = await hs_patch(f"/marketing/v3/forms/{form_id}", json=patch)
        return ApiResponse(success=True, data={
            "form_id": form_id,
            "name": data.get("name"),
        })
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.post("/forms/delete")
async def delete_forms(req: DeleteFormsRequest) -> ApiResponse:
    """
    Delete forms. The web UI is responsible for showing the confirmation dialog
    and sending confirmed=true. This endpoint trusts the web UI's confirmation.
    """
    results = []
    names = (
        req.confirmed_names
        if len(req.confirmed_names) == len(req.form_ids)
        else [""] * len(req.form_ids)
    )
    for form_id, name in zip(req.form_ids, names):
        try:
            await hs_delete(f"/marketing/v3/forms/{form_id}")
            results.append({"form_id": form_id, "name": name, "status": "deleted"})
        except Exception as e:
            status = "not_found" if "404" in str(e) else "error"
            results.append({"form_id": form_id, "name": name, "status": status, "error": str(e)})

    return ApiResponse(success=True, data=results)


@router.patch("/forms/notifications")
async def update_notifications(req: UpdateNotificationsRequest) -> ApiResponse:
    try:
        data = await hs_patch(
            f"/marketing/v3/forms/{req.form_id}",
            json={"notificationEmails": [str(e) for e in req.notification_emails]},
        )
        return ApiResponse(success=True, data={
            "form_id": req.form_id,
            "notification_emails": data.get("notificationEmails", []),
        })
    except Exception as e:
        return ApiResponse(success=False, error=str(e))
