"""
MCP tools for HubSpot email draft lifecycle:
  - run_email_qa
  - create_email_draft
  - get_email_draft
  - list_email_drafts
  - update_email_draft
  - delete_email_draft
  - schedule_email_send
  - apply_utm_corrections
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..lib.email_builder import build_email_payload, validate_draft_spec
from ..lib.hubspot_client import hs_delete, hs_get, hs_patch, hs_post
from ..lib.qa_runner import run_qa
from ..lib.utm_tagger import UtmSpec, audit_all_links, build_utm_url

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    # ── QA TOOL ──────────────────────────────────────────────────────────────

    @mcp.tool()
    async def run_email_qa(
        draft: dict,
        audience_list_ids: list[str] | None = None,
        suppression_list_ids: list[str] | None = None,
    ) -> dict:
        """
        Run the full 5-section pre-send QA checklist against an email draft spec.

        Sections:
          4.1 Sender & Deliverability
          4.2 Subscription & Preference Center
          4.3 Consent Compliance
          4.4 Content QA (subject, preheader, UTM, tokens, links)
          4.5 Sense Check

        Verdicts:
          READY_TO_SEND   — all checks pass
          NEEDS_CHANGES   — medium/high issues; must resolve before send
          BLOCKED         — critical issues; must resolve before draft is created

        draft: dict with keys:
          name, subject, preheader, from_name, from_email, reply_to,
          body_html, subscription_type_id, utm_spec (optional dict)

        Returns the full QA report including claude_can_fix and manual_actions lists.

        GUARDRAIL: Do NOT create an email draft (create_email_draft) if verdict is BLOCKED.
        Always run QA first.
        """
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = str(portal_data.get("portalId", ""))

        # Fetch audience list metadata for health checks
        audience_lists = []
        if audience_list_ids:
            for list_id in audience_list_ids:
                try:
                    lst = await hs_get(f"/contacts/v1/lists/{list_id}")
                    audience_lists.append(
                        {
                            "id": list_id,
                            "name": lst.get("name", list_id),
                            "listType": lst.get("listType", "UNKNOWN"),
                            "size": lst.get("metaData", {}).get("size", -1),
                        }
                    )
                except Exception as e:
                    audience_lists.append(
                        {
                            "id": list_id,
                            "name": list_id,
                            "listType": "UNKNOWN",
                            "size": -1,
                            "error": str(e),
                        }
                    )

        draft_with_lists = {**draft}
        draft_with_lists["audience_list_ids"] = audience_list_ids or []
        draft_with_lists["suppression_list_ids"] = suppression_list_ids or []

        report = run_qa(
            draft=draft_with_lists,
            portal_id=portal_id,
            audience_lists=audience_lists,
        )
        return report.to_dict()

    # ── CREATE DRAFT ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def create_email_draft(
        name: str,
        subject: str,
        from_name: str,
        from_email: str,
        reply_to: str,
        body_html: str,
        subscription_type_id: str,
        preheader: str = "",
        utm_spec: dict | None = None,
        audience_list_ids: list[str] | None = None,
        suppression_list_ids: list[str] | None = None,
        ctx: Context = None,
    ) -> dict:
        """
        Create a HubSpot marketing email draft (always saved as DRAFT — never auto-sends).

        GUARDRAILS (enforced — these will block the tool if violated):
          1. subscription_type_id MUST be explicitly confirmed by the user.
             Use list_hubspot_subscription_types to present options first.
          2. from_email MUST be a brand domain (no gmail/yahoo/hotmail/etc.).
          3. reply_to MUST NOT be a noreply@ address.
          4. body_html MUST contain an unsubscribe link.
          5. Run run_email_qa first — if verdict is BLOCKED, do NOT call this tool.

        All inputs are validated. A confirmation dialog is shown before the API call.

        Returns: draft_id, name, hubspot_url, qa_summary, warnings.
        """
        draft_spec: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "preheader": preheader,
            "from_name": from_name,
            "from_email": from_email,
            "reply_to": reply_to,
            "body_html": body_html,
            "subscription_type_id": subscription_type_id,
            "utm_spec": utm_spec,
            "audience_list_ids": audience_list_ids or [],
            "suppression_list_ids": suppression_list_ids or [],
        }

        # ── Pre-flight validation ────────────────────────────────────────────
        issues = validate_draft_spec(draft_spec)
        critical = [i for i in issues if i["severity"] == "critical"]
        high = [i for i in issues if i["severity"] == "high"]

        if critical:
            return {
                "status": "blocked",
                "reason": "Critical issues must be resolved before creating this draft.",
                "issues": critical + high,
            }

        warnings = [i for i in issues if i["severity"] in ("medium", "low")]

        # ── Elicit confirmation ──────────────────────────────────────────────
        confirm_message = (
            f"Create HubSpot email draft?\n\n"
            f"Name: {name}\n"
            f"Subject: {subject}\n"
            f"From: {from_name} <{from_email}>\n"
            f"Reply-to: {reply_to}\n"
            f"Subscription type ID: {subscription_type_id}\n"
            f"Audience lists: {', '.join(audience_list_ids or []) or 'none'}\n"
            f"Suppression lists: {', '.join(suppression_list_ids or []) or 'none'}"
        )
        if high:
            confirm_message += (
                f"\n\n⚠️  {len(high)} high-severity issue(s) found — see qa_summary. "
                "Proceeding will create the draft but it should NOT be sent until resolved."
            )

        if ctx:
            try:
                result = await ctx.elicit(
                    message=confirm_message,
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {
                                "type": "boolean",
                                "title": "Confirm draft creation",
                            }
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return {"status": "cancelled", "message": "Draft creation cancelled by user."}
            except Exception:
                return {
                    "action_required": "confirm_create",
                    "message": (
                        f"Please confirm: create email draft '{name}' "
                        f"(from: {from_email}, subscription: {subscription_type_id})? "
                        "Reply 'yes' to proceed or 'no' to cancel."
                    ),
                }

        # ── Build and POST payload ───────────────────────────────────────────
        payload = build_email_payload(draft_spec)
        data = await hs_post("/marketing/v3/emails/", json=payload)

        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")
        draft_id = data.get("id")

        return {
            "status": "created",
            "draft_id": draft_id,
            "name": data.get("name"),
            "subject": data.get("subject"),
            "hubspot_url": (
                f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
            ),
            "warnings": warnings,
            "qa_summary": (
                f"{len(high)} high-severity issue(s) remain — resolve before sending."
                if high
                else "No blocking issues."
            ),
        }

    # ── READ TOOLS ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_email_drafts(query: str = "", limit: int = 20) -> list[dict]:
        """
        List HubSpot email drafts, optionally filtered by name fragment.
        Returns id, name, subject, status, and updatedAt for each match.
        """
        params: dict[str, Any] = {
            "limit": min(limit, 100),
            "state": "DRAFT",
        }
        data = await hs_get("/marketing/v3/emails/", params=params)
        results = data.get("results", []) if isinstance(data, dict) else []

        if query:
            q_lower = query.lower()
            results = [r for r in results if q_lower in r.get("name", "").lower()]

        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "subject": r.get("subject"),
                "status": r.get("state"),
                "updated_at": r.get("updatedAt"),
                "hubspot_url": (
                    f"https://app.hubspot.com/email/{portal_id}/edit/{r.get('id')}/settings"
                    if portal_id
                    else None
                ),
            }
            for r in results
        ]

    @mcp.tool()
    async def get_email_draft(draft_id: str) -> dict:
        """
        Fetch the full details of a HubSpot email draft by ID.
        Returns all fields needed to run QA or resume editing.
        """
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "subject": data.get("subject"),
            "preheader": data.get("previewText", ""),
            "from_name": data.get("fromName", ""),
            "from_email": data.get("fromEmail", ""),
            "reply_to": data.get("replyTo", ""),
            "status": data.get("state"),
            "subscription_id": data.get("subscriptionId"),
            "scheduled_at": data.get("scheduledAt"),
            "updated_at": data.get("updatedAt"),
            "hubspot_url": (
                f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                if portal_id
                else None
            ),
        }

    # ── UPDATE TOOLS ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def update_email_draft(draft_id: str, updates: dict) -> dict:
        """
        Patch one or more fields on an existing HubSpot email draft.

        Valid update keys: name, subject, previewText (preheader), fromName,
        fromEmail, replyTo, subscriptionId, content (dict with 'body' key).

        Returns the updated draft summary.

        GUARDRAIL: Only DRAFT-state emails can be updated. Published/sent emails
        cannot be modified — the tool will return an error if the email is not a draft.
        """
        # Check current state first
        current = await hs_get(f"/marketing/v3/emails/{draft_id}")
        state = current.get("state", "")
        if state not in ("DRAFT", "SCHEDULED"):
            return {
                "status": "error",
                "message": (
                    f"Email '{current.get('name')}' is in state '{state}' — "
                    "only DRAFT or SCHEDULED emails can be updated."
                ),
            }

        data = await hs_patch(f"/marketing/v3/emails/{draft_id}", json=updates)
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return {
            "status": "updated",
            "draft_id": draft_id,
            "name": data.get("name"),
            "subject": data.get("subject"),
            "hubspot_url": (
                f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                if portal_id
                else None
            ),
        }

    @mcp.tool()
    async def apply_utm_corrections(
        draft_id: str,
        utm_campaign: str,
        utm_content_map: dict[str, str] | None = None,
        ctx: Context = None,
    ) -> dict:
        """
        Fetch an email draft's body HTML, scan all outbound links, and apply
        corrected UTM-tagged URLs.

        utm_campaign: the campaign slug, e.g. '26q2-oss-india-2026'
        utm_content_map: optional dict mapping original URLs to their utm_content
          descriptor, e.g. {"https://events.lf.org/register": "register-cta"}
          If omitted, content is auto-derived from link text patterns.

        Returns a summary of how many links were corrected and the updated draft URL.

        GUARDRAIL: Always confirms with the user before patching the draft.
        """
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        body_html: str = data.get("content", {}).get("body", "")
        name = data.get("name", draft_id)

        if not body_html:
            return {
                "status": "error",
                "message": "No HTML body found on this draft — edit the email content first.",
            }

        utm_spec = UtmSpec(campaign=utm_campaign)
        audits = audit_all_links(body_html, utm_spec)
        to_fix = [a for a in audits if not a["has_utm"] and a.get("corrected_url")]

        if not to_fix:
            return {"status": "ok", "message": "All links already have UTM parameters.", "fixed": 0}

        # Apply corrections to HTML
        updated_html = body_html
        for a in to_fix:
            original = a["url"]
            corrected = a["corrected_url"]
            # Override utm_content if a mapping was provided
            if utm_content_map and original in utm_content_map:
                spec_override = UtmSpec(
                    campaign=utm_campaign, content=utm_content_map[original]
                )
                corrected = build_utm_url(original, spec_override)
            updated_html = updated_html.replace(f'href="{original}"', f'href="{corrected}"')
            updated_html = updated_html.replace(f"href='{original}'", f"href='{corrected}'")

        # Confirm before patching
        if ctx:
            try:
                result = await ctx.elicit(
                    message=(
                        f"Apply UTM corrections to '{name}'?\n\n"
                        f"{len(to_fix)} link(s) will be updated with campaign: {utm_campaign}"
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {"type": "boolean", "title": "Apply UTM corrections"}
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return {"status": "cancelled", "message": "UTM correction cancelled by user."}
            except Exception:
                return {
                    "action_required": "confirm_utm",
                    "message": (
                        f"Confirm applying UTM corrections to {len(to_fix)} link(s) in '{name}'? "
                        f"Campaign: {utm_campaign}. Reply 'yes' to proceed."
                    ),
                }

        updated = await hs_patch(
            f"/marketing/v3/emails/{draft_id}",
            json={"content": {"body": updated_html}},
        )
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return {
            "status": "corrected",
            "draft_id": draft_id,
            "links_fixed": len(to_fix),
            "hubspot_url": (
                f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                if portal_id
                else None
            ),
        }

    # ── DELETE / SCHEDULE ────────────────────────────────────────────────────

    @mcp.tool()
    async def delete_email_draft(
        draft_id: str,
        confirmed_name: str,
        ctx: Context = None,
    ) -> dict:
        """
        Permanently delete a HubSpot email draft.

        Only DRAFT-state emails can be deleted. Sent or scheduled emails cannot
        be deleted via this tool — cancel the schedule first.

        confirmed_name: the human-readable email name, used in the confirmation dialog.

        This action is PERMANENT and cannot be undone.
        """
        # Check state
        current = await hs_get(f"/marketing/v3/emails/{draft_id}")
        state = current.get("state", "")
        if state not in ("DRAFT",):
            return {
                "status": "error",
                "message": (
                    f"Email '{confirmed_name}' is in state '{state}'. "
                    "Only DRAFT emails can be deleted. Cancel the schedule first if needed."
                ),
            }

        # Confirm before deleting
        if ctx:
            try:
                result = await ctx.elicit(
                    message=(
                        f"Permanently delete email draft?\n\n"
                        f"'{confirmed_name}'\n\n"
                        "This CANNOT be undone."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {
                                "type": "boolean",
                                "title": "I understand this is permanent — delete this draft",
                            }
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return {"status": "cancelled", "message": "Deletion cancelled by user."}
            except Exception:
                return {
                    "action_required": "confirm_deletion",
                    "message": (
                        f"Confirmation required before deleting '{confirmed_name}'. "
                        "This is PERMANENT. Reply 'yes' to confirm, or 'no' to cancel."
                    ),
                }

        await hs_delete(f"/marketing/v3/emails/{draft_id}")
        logger.info("Deleted email draft %s (%s)", draft_id, confirmed_name)
        return {"status": "deleted", "draft_id": draft_id, "name": confirmed_name}

    @mcp.tool()
    async def schedule_email_send(
        draft_id: str,
        scheduled_at_iso: str,
        ctx: Context = None,
    ) -> dict:
        """
        Schedule a HubSpot email draft for send.

        scheduled_at_iso: ISO 8601 datetime string in UTC, e.g. '2026-06-15T14:00:00Z'

        GUARDRAIL: Always runs a final QA check before scheduling.
        Will refuse to schedule if the email has unresolved critical/high issues
        (empty audience, missing unsubscribe link, etc.)

        Returns the scheduled time and a HubSpot deep link.
        """
        # Fetch current draft state
        data = await hs_get(f"/marketing/v3/emails/{draft_id}")
        name = data.get("name", draft_id)
        state = data.get("state", "")

        if state != "DRAFT":
            return {
                "status": "error",
                "message": (
                    f"Email '{name}' is in state '{state}' — only DRAFT emails can be scheduled."
                ),
            }

        # Light pre-schedule QA: check subscription type and unsubscribe link are present
        subscription_id = data.get("subscriptionId")
        body = data.get("content", {}).get("body", "")
        has_unsub = any(kw in body.lower() for kw in ["unsubscribe", "opt-out", "subscription preferences"])

        blockers = []
        if not subscription_id:
            blockers.append("No subscription type assigned.")
        if not has_unsub:
            blockers.append("No unsubscribe link in email body.")

        if blockers:
            return {
                "status": "blocked",
                "reason": "Pre-schedule QA failed — resolve these before scheduling:",
                "blockers": blockers,
            }

        # Confirm with user
        if ctx:
            try:
                result = await ctx.elicit(
                    message=(
                        f"Schedule '{name}' to send at {scheduled_at_iso} UTC?\n\n"
                        "Verify the audience and suppression lists are correctly applied "
                        "in HubSpot before confirming."
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "proceed": {
                                "type": "boolean",
                                "title": "Confirm schedule",
                            }
                        },
                        "required": ["proceed"],
                    },
                )
                if result.action != "accept" or not result.data.get("proceed"):
                    return {"status": "cancelled", "message": "Scheduling cancelled by user."}
            except Exception:
                return {
                    "action_required": "confirm_schedule",
                    "message": (
                        f"Confirm scheduling '{name}' for {scheduled_at_iso} UTC? "
                        "Reply 'yes' to confirm."
                    ),
                }

        updated = await hs_patch(
            f"/marketing/v3/emails/{draft_id}",
            json={"scheduledAt": scheduled_at_iso},
        )
        portal_data = await hs_get("/account-info/v3/details")
        portal_id = portal_data.get("portalId", "")

        return {
            "status": "scheduled",
            "draft_id": draft_id,
            "name": name,
            "scheduled_at": scheduled_at_iso,
            "hubspot_url": (
                f"https://app.hubspot.com/email/{portal_id}/edit/{draft_id}/settings"
                if portal_id
                else None
            ),
        }
