"""
HubSpot API integration for A/B workflow feature
Handles all direct HubSpot calls
"""
import logging
import requests
from config import HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID
from .models import EmailStats

log = logging.getLogger("email-staging")


def _headers() -> dict:
    """HubSpot API headers"""
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def get_email_details(email_id: str) -> dict:
    """
    Fetch email details from HubSpot
    Returns: email name, subject, from address, etc.
    """
    try:
        resp = requests.get(
            f"https://api.hubapi.com/marketing/v3/emails/{email_id}",
            headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"[AB-WF] Failed to get email {email_id}: {e}")
        return {}


def get_list_details(list_id: str) -> dict:
    """
    Fetch list details from HubSpot
    Returns: list name, contact count, etc.
    """
    try:
        resp = requests.get(
            f"https://api.hubapi.com/crm/v3/objects/lists/{list_id}",
            headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"[AB-WF] Failed to get list {list_id}: {e}")
        return {}


def search_emails_by_name(name_contains: str) -> list:
    """
    Search for emails in HubSpot by name
    Returns list of emails matching the name pattern
    """
    try:
        resp = requests.get(
            "https://api.hubapi.com/marketing/v3/emails",
            headers=_headers(),
            params={
                "limit": 50,
                "name__icontains": name_contains,
                "orderBy": "-createdAt"
            }
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])
    except Exception as e:
        log.error(f"[AB-WF] Failed to search emails: {e}")
        return []


def search_lists_by_name(name_contains: str) -> list:
    """
    Search for lists in HubSpot by name
    Returns list of lists matching the name pattern
    """
    try:
        resp = requests.get(
            "https://api.hubapi.com/crm/v3/objects/lists",
            headers=_headers(),
            params={
                "limit": 50,
                "properties": ["name", "listSize", "listDescription"],
            }
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        # Client-side filter by name
        if name_contains:
            results = [
                r for r in results
                if name_contains.lower() in r.get("properties", {}).get("name", "").lower()
            ]

        return results
    except Exception as e:
        log.error(f"[AB-WF] Failed to search lists: {e}")
        return []


def get_email_stats(email_id: str) -> EmailStats:
    """
    Fetch email open/click stats from HubSpot
    """
    try:
        resp = requests.get(
            f"https://api.hubapi.com/marketing/v3/emails/{email_id}",
            headers=_headers(),
            params={"properties": ["sent", "opened", "clicked", "converted"]}
        )
        resp.raise_for_status()
        email_data = resp.json()

        # Get stats from email object
        sent = email_data.get("sent", {}).get("count", 0)
        opens = email_data.get("opened", {}).get("count", 0)
        clicks = email_data.get("clicked", {}).get("count", 0)
        conversions = email_data.get("converted", {}).get("count", 0)

        # Calculate rates
        open_rate = (opens / sent * 100) if sent > 0 else 0
        click_rate = (clicks / sent * 100) if sent > 0 else 0
        conversion_rate = (conversions / sent * 100) if sent > 0 else 0

        return EmailStats(
            sent=sent,
            opens=opens,
            clicks=clicks,
            conversions=conversions,
            open_rate=open_rate,
            click_rate=click_rate,
            conversion_rate=conversion_rate
        )
    except Exception as e:
        log.error(f"[AB-WF] Failed to get email stats for {email_id}: {e}")
        return EmailStats()


def create_hubspot_workflow(name: str, variant_a_id: str, variant_b_id: str) -> dict:
    """
    Create a workflow in HubSpot for A/B testing
    Note: In production, this would use HubSpot's workflow API
    For now, we'll return a mock workflow ID
    """
    log.info(f"[AB-WF] Creating HubSpot workflow: {name}")

    # TODO: Implement actual HubSpot workflow creation via API
    # This is a placeholder - actual implementation requires HubSpot Workflows API

    return {
        "workflow_id": f"wf_{variant_a_id}_{variant_b_id}",
        "name": name,
        "variant_a_id": variant_a_id,
        "variant_b_id": variant_b_id,
        "created": True
    }


def trigger_workflow_execution(
    workflow_id: str,
    list_id: str,
    variant_a_id: str,
    variant_b_id: str,
    test_duration_hours: int = 24
) -> dict:
    """
    Trigger a workflow execution for A/B testing
    """
    log.info(f"[AB-WF] Triggering workflow {workflow_id} with emails {variant_a_id} and {variant_b_id}")

    # TODO: Implement actual workflow execution
    # This is a placeholder

    return {
        "execution_id": f"exec_{workflow_id}_{list_id}",
        "status": "running",
        "started_at": "2026-07-25T10:00:00Z",
        "will_complete_at": f"2026-07-25T{test_duration_hours}:00:00Z"
    }


def get_workflow_results(workflow_id: str, variant_a_id: str, variant_b_id: str) -> dict:
    """
    Fetch A/B test results from HubSpot workflow
    """
    log.info(f"[AB-WF] Fetching results for workflow {workflow_id}")

    # Get stats for both variants
    variant_a_stats = get_email_stats(variant_a_id)
    variant_b_stats = get_email_stats(variant_b_id)

    # Determine winner based on open rate
    variant_a_wins = variant_a_stats.open_rate > variant_b_stats.open_rate
    winner = "A" if variant_a_wins else "B"
    winner_id = variant_a_id if variant_a_wins else variant_b_id

    # Calculate confidence (simplified)
    # In production, use Chi-square test
    total_opens = variant_a_stats.opens + variant_b_stats.opens
    if total_opens > 100:  # Arbitrary threshold
        confidence = 94.0
    else:
        confidence = 60.0

    return {
        "variant_a_stats": {
            "sent": variant_a_stats.sent,
            "opens": variant_a_stats.opens,
            "clicks": variant_a_stats.clicks,
            "open_rate": round(variant_a_stats.open_rate, 2),
            "click_rate": round(variant_a_stats.click_rate, 2),
        },
        "variant_b_stats": {
            "sent": variant_b_stats.sent,
            "opens": variant_b_stats.opens,
            "clicks": variant_b_stats.clicks,
            "open_rate": round(variant_b_stats.open_rate, 2),
            "click_rate": round(variant_b_stats.click_rate, 2),
        },
        "winner": winner,
        "winner_email_id": winner_id,
        "confidence": confidence,
    }
