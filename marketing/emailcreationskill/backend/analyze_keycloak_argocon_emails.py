"""
Analyze all KeycloakCon + ArgoCon Japan emails from HubSpot.
Extracts email content, identifies campaign stages, and creates templates.
"""
import json
import sys
import logging
from datetime import datetime
import hubspot_tools
from config import HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def search_all_emails_for_event(search_terms: list[str]) -> list[dict]:
    """Search HubSpot for emails matching any of the search terms."""
    all_emails = []

    for term in search_terms:
        log.info(f"Searching for emails with: {term}")
        try:
            data = hubspot_tools._get("/marketing/v3/emails", params={
                "limit": 100,
                "name__icontains": term,
                "orderBy": "-publishDate",
            })
            emails = [e for e in data.get("results", []) if e.get("state") == "PUBLISHED"]
            log.info(f"  Found {len(emails)} published emails")

            for email in emails:
                # Avoid duplicates
                if not any(e["id"] == email["id"] for e in all_emails):
                    all_emails.append(email)
        except Exception as e:
            log.error(f"  Error searching for '{term}': {e}")

    return all_emails

def get_email_full_content(email_id: str) -> dict:
    """Get complete email content including HTML."""
    try:
        content_data = hubspot_tools.get_email_content_text(email_id)
        raw_email = hubspot_tools._get(f"/marketing/v3/emails/{email_id}")

        return {
            "id": email_id,
            "name": raw_email.get("name", ""),
            "subject": raw_email.get("subject", ""),
            "preview_text": content_data.get("preview_text", ""),
            "body_html": content_data.get("body_html", ""),
            "body_text": content_data.get("body_text", ""),
            "sections": content_data.get("sections", []),
            "publish_date": raw_email.get("publishDate", ""),
            "from_name": (raw_email.get("from") or {}).get("fromName", ""),
            "from_address": (raw_email.get("from") or {}).get("replyTo", ""),
        }
    except Exception as e:
        log.error(f"Error getting content for {email_id}: {e}")
        return {"id": email_id, "error": str(e)}

def identify_stage(email_dict: dict) -> str:
    """
    Identify the campaign stage based on email name/subject.
    Stages: Save the Date, CFP Launch, Registration Open, Final Countdown, Event Week, Post-Event
    """
    name = (email_dict.get("name") or "").lower()
    subject = (email_dict.get("subject") or "").lower()
    combined = f"{name} {subject}"

    stage_indicators = {
        "Save the Date": ["save the date", "dates announced", "coming to", "officially here"],
        "CFP Launch": ["call for proposal", "cfp", "call for talk", "speak at"],
        "Registration Open": ["registration open", "register now", "early bird"],
        "Final Countdown": ["final call", "last chance", "closes", "48 hours", "2 days left"],
        "Event Week": ["welcome", "day 1", "badge pickup", "opening keynote"],
        "Post-Event": ["thank you", "survey", "recording", "session recording", "recap"],
    }

    for stage, keywords in stage_indicators.items():
        if any(kw in combined for kw in keywords):
            return stage

    return "Unknown"

def extract_event_data(emails: list[dict]) -> dict:
    """Extract event details from email content."""
    event_data = {
        "dates": [],
        "location": [],
        "event_name": "",
        "description": "",
        "key_topics": [],
        "ctas": [],
    }

    for email in emails:
        text = f"{email.get('body_text', '')} {email.get('subject', '')}"

        # Extract locations
        if "tokyo" in text.lower() or "japan" in text.lower():
            if "Tokyo, Japan" not in event_data["location"]:
                event_data["location"].append("Tokyo, Japan")

        # Extract event name
        if "keycloak" in text.lower() and "argocon" in text.lower():
            if not event_data["event_name"]:
                event_data["event_name"] = "KeycloakCon + ArgoCon Japan"
        elif "keycloak" in text.lower():
            if not event_data["event_name"]:
                event_data["event_name"] = "KeycloakCon Japan"
        elif "argocon" in text.lower():
            if not event_data["event_name"]:
                event_data["event_name"] = "ArgoCon Japan"

        # Extract key topics
        topics = ["Keycloak", "ArgoCD", "GitOps", "Identity", "Cloud Native", "Kubernetes"]
        for topic in topics:
            if topic.lower() in text.lower() and topic not in event_data["key_topics"]:
                event_data["key_topics"].append(topic)

        # Extract CTAs
        ctas = []
        if "register" in text.lower():
            ctas.append("Register")
        if "schedule" in text.lower():
            ctas.append("View Schedule")
        if "submit" in text.lower():
            ctas.append("Submit Talk")
        if "sponsor" in text.lower():
            ctas.append("Sponsor")

        for cta in ctas:
            if cta not in event_data["ctas"]:
                event_data["ctas"].append(cta)

    return event_data

def main():
    log.info("=" * 80)
    log.info("ANALYZING KeycloakCon + ArgoCon Japan EMAILS")
    log.info("=" * 80)

    # Search for emails
    search_terms = ["KeycloakCon", "Keycloak", "ArgoCon", "Argocon"]
    all_emails = search_all_emails_for_event(search_terms)

    log.info(f"\nFound {len(all_emails)} total emails")

    if not all_emails:
        log.warning("No emails found! Check search terms or HubSpot access.")
        return

    # Filter for Japan-related emails
    japan_emails = [
        e for e in all_emails
        if "japan" in e.get("name", "").lower() or "japan" in e.get("subject", "").lower()
    ]

    log.info(f"Filtered to {len(japan_emails)} Japan-specific emails")

    # Get full content for each email
    log.info("\nExtracting full email content...")
    emails_with_content = []
    for email in japan_emails[:50]:  # Limit to first 50 to avoid API rate limits
        log.info(f"  Getting content for: {email.get('name')}")
        content = get_email_full_content(email["id"])
        if "error" not in content:
            stage = identify_stage(content)
            content["stage"] = stage
            content["publish_date"] = email.get("publishDate", "")
            emails_with_content.append(content)

    # Sort by date
    emails_with_content.sort(key=lambda e: e.get("publish_date", ""), reverse=False)

    log.info(f"\nSuccessfully extracted {len(emails_with_content)} emails")

    # Extract event data
    log.info("\nExtracting event data...")
    event_data = extract_event_data(emails_with_content)

    log.info("\n" + "=" * 80)
    log.info("ANALYSIS SUMMARY")
    log.info("=" * 80)
    log.info(f"Event Name: {event_data['event_name']}")
    log.info(f"Location: {', '.join(event_data['location'])}")
    log.info(f"Key Topics: {', '.join(event_data['key_topics'])}")
    log.info(f"CTAs Found: {', '.join(event_data['ctas'])}")

    # Group by stage
    log.info("\n" + "=" * 80)
    log.info("EMAILS BY STAGE")
    log.info("=" * 80)

    stages = {}
    for email in emails_with_content:
        stage = email.get("stage", "Unknown")
        if stage not in stages:
            stages[stage] = []
        stages[stage].append(email)

    for stage, stage_emails in sorted(stages.items()):
        log.info(f"\n{stage}: {len(stage_emails)} email(s)")
        for email in stage_emails:
            log.info(f"  - {email['name']}")
            log.info(f"    Subject: {email['subject']}")
            log.info(f"    Date: {email.get('publish_date', 'N/A')[:10]}")

    # Save detailed analysis to file
    output = {
        "event_data": event_data,
        "stages": {},
        "emails_by_stage": {}
    }

    for stage, stage_emails in stages.items():
        output["emails_by_stage"][stage] = []
        for email in stage_emails:
            output["emails_by_stage"][stage].append({
                "id": email["id"],
                "name": email["name"],
                "subject": email["subject"],
                "preview": email.get("preview_text", "")[:100],
                "publish_date": email.get("publish_date", ""),
                "from_name": email.get("from_name", ""),
            })

    output_file = "keycloak_argocon_analysis.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"\n✅ Analysis saved to {output_file}")
    log.info("\nNext steps:")
    log.info("1. Review the analysis JSON file")
    log.info("2. Each stage's emails will be analyzed for structure and content")
    log.info("3. Templates will be created based on the patterns")
    log.info("4. AI will generate new content using these templates")

if __name__ == "__main__":
    main()
