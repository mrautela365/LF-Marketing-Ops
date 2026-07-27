"""
Deep analysis of KeycloakCon + ArgoCon Japan emails.
Extracts HTML, identifies structure patterns, and creates template data.
"""
import json
import logging
from html.parser import HTMLParser
import hubspot_tools

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Email IDs to analyze by stage
EMAILS_TO_ANALYZE = {
    "CFP Launch": [
        "209236098821",  # CNCF Foundation
        "210638080306",  # Last Chance CFP
    ],
    "Schedule Announcement": [
        "212761246058",  # Schedules Announced
    ],
    "Registration / Pricing Push": [
        "214701049921",  # More Sessions / Pricing Ends
    ],
    "Discount Offer": [
        "216185138264",  # Alumni Discount
        "216270210681",  # ArgoCD Discount
    ],
    "Final Countdown": [
        "216822129827",  # Last Chance to Register
    ],
}

class HTMLAnalyzer(HTMLParser):
    """Extract key HTML elements from email content."""

    def __init__(self):
        super().__init__()
        self.in_subject = False
        self.in_preview = False
        self.images = []
        self.buttons = []
        self.text_blocks = []
        self.links = []
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "img":
            self.images.append({
                "src": attrs_dict.get("src", ""),
                "alt": attrs_dict.get("alt", ""),
                "width": attrs_dict.get("width", ""),
                "height": attrs_dict.get("height", ""),
            })
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and not href.startswith("#"):
                self.links.append(href)

    def handle_data(self, data):
        text = data.strip()
        if text and len(text) > 2:
            self.current_text.append(text)

    def handle_endtag(self, tag):
        if tag == "p" and self.current_text:
            text = " ".join(self.current_text)
            if len(text) > 10:
                self.text_blocks.append(text)
            self.current_text = []

def analyze_email(email_id: str) -> dict:
    """Get full email content and structure."""
    try:
        raw = hubspot_tools._get(f"/marketing/v3/emails/{email_id}")
        content_info = hubspot_tools.get_email_content_text(email_id)

        return {
            "id": email_id,
            "name": raw.get("name", ""),
            "subject": raw.get("subject", ""),
            "preview": content_info.get("preview_text", ""),
            "from_name": (raw.get("from") or {}).get("fromName", ""),
            "body_html": content_info.get("body_html", ""),
            "body_text": content_info.get("body_text", ""),
            "sections": content_info.get("sections", []),
        }
    except Exception as e:
        log.error(f"Error analyzing {email_id}: {e}")
        return {"id": email_id, "error": str(e)}

def extract_email_structure(email_data: dict) -> dict:
    """Extract key structural elements from email."""
    html = email_data.get("body_html", "")
    text = email_data.get("body_text", "")

    # Parse HTML
    parser = HTMLAnalyzer()
    try:
        parser.feed(html)
    except:
        pass

    # Detect key sections
    structure = {
        "subject": email_data.get("subject", ""),
        "preview": email_data.get("preview", ""),
        "from_name": email_data.get("from_name", ""),
        "has_hero_image": len(parser.images) > 0,
        "hero_image": parser.images[0] if parser.images else None,
        "image_count": len(parser.images),
        "cta_count": len(parser.links),
        "main_ctas": extract_ctas(html),
        "text_sections": parser.text_blocks[:5],  # First 5 text blocks
        "tone": detect_tone(text),
        "key_elements": {
            "emojis": "Yes" if any(ord(c) > 127 for c in email_data.get("subject", "")) else "No",
            "urgency_words": detect_urgency_words(text),
            "social_proof": "Yes" if any(w in text.lower() for w in ["attendees", "speakers", "registrations"]) else "No",
        }
    }

    return structure

def extract_ctas(html: str) -> list:
    """Extract call-to-action buttons and links."""
    import re
    ctas = []

    # Look for button text patterns
    button_patterns = [
        r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>([^<]+(?:Register|Submit|Speak|Sponsor|Schedule|Save|Learn|View|View|Download)[^<]*)</a>',
        r'>([^<]*(?:Register|Submit|Speak|Sponsor|View)[^<]*)<',
    ]

    for pattern in button_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                ctas.append(match[1] if len(match) > 1 else match[0])
            else:
                ctas.append(match)

    return list(set(ctas))[:5]  # Top 5 unique CTAs

def detect_tone(text: str) -> str:
    """Detect email tone."""
    text_lower = text.lower()

    if any(w in text_lower for w in ["urgency", "hurry", "limited", "closing", "last chance", "final", "deadline"]):
        return "Urgent"
    elif any(w in text_lower for w in ["excited", "thrilled", "looking forward", "amazing", "incredible"]):
        return "Excited"
    elif any(w in text_lower for w in ["join us", "connect", "community", "peers", "together"]):
        return "Community-focused"
    elif any(w in text_lower for w in ["save", "discount", "offer", "special", "deal"]):
        return "Promotion-focused"
    else:
        return "Informational"

def detect_urgency_words(text: str) -> list:
    """Find urgency-related keywords."""
    urgency_words = [
        "final", "last chance", "hurry", "limited", "deadline", "closes", "ends",
        "urgent", "alert", "immediately", "now", "today", "hours", "days"
    ]
    text_lower = text.lower()
    found = [w for w in urgency_words if w in text_lower]
    return found

def main():
    log.info("=" * 100)
    log.info("DEEP EMAIL STRUCTURE ANALYSIS — KeycloakCon + ArgoCon Japan 2026")
    log.info("=" * 100)

    templates = {}

    for stage, email_ids in EMAILS_TO_ANALYZE.items():
        log.info(f"\n{stage}")
        log.info("-" * 100)

        stage_emails = []
        for email_id in email_ids:
            log.info(f"  Analyzing {email_id}...")
            email_data = analyze_email(email_id)

            if "error" not in email_data:
                structure = extract_email_structure(email_data)
                stage_emails.append({
                    "id": email_id,
                    "name": email_data.get("name"),
                    "structure": structure
                })

                # Log key findings
                log.info(f"    Subject: {structure['subject'][:60]}...")
                log.info(f"    Tone: {structure['tone']}")
                log.info(f"    CTAs: {', '.join(structure['main_ctas'][:3])}")
                log.info(f"    Urgency: {', '.join(structure['key_elements']['urgency_words']) if structure['key_elements']['urgency_words'] else 'None'}")
                log.info(f"    Hero Image: {'Yes' if structure['has_hero_image'] else 'No'}")
            else:
                log.error(f"    Error: {email_data['error']}")

        if stage_emails:
            templates[stage] = {
                "count": len(stage_emails),
                "emails": stage_emails,
                "template_patterns": extract_stage_patterns(stage_emails)
            }

    # Save detailed templates
    output = {
        "event": {
            "name": "KeycloakCon + ArgoCon Japan 2026",
            "location": "Yokohama, Japan",
            "date": "July 28, 2026",
            "key_topics": ["Keycloak", "ArgoCD", "Identity", "GitOps", "Kubernetes"]
        },
        "stages": templates
    }

    with open("keycloak_argocon_templates.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log.info("\n" + "=" * 100)
    log.info("✅ Template analysis saved to keycloak_argocon_templates.json")
    log.info("=" * 100)

def extract_stage_patterns(stage_emails: list) -> dict:
    """Extract common patterns across emails in a stage."""
    if not stage_emails:
        return {}

    # Aggregate data from all emails in the stage
    all_tones = [e["structure"]["tone"] for e in stage_emails]
    all_ctas = []
    for e in stage_emails:
        all_ctas.extend(e["structure"]["main_ctas"])
    all_urgency = []
    for e in stage_emails:
        all_urgency.extend(e["structure"]["key_elements"]["urgency_words"])

    return {
        "dominant_tone": max(set(all_tones), key=all_tones.count) if all_tones else "Unknown",
        "common_ctas": list(set(all_ctas)),
        "common_urgency_words": list(set(all_urgency)),
        "avg_cta_count": sum(len(e["structure"]["main_ctas"]) for e in stage_emails) / len(stage_emails) if stage_emails else 0,
        "has_hero_image_standard": any(e["structure"]["has_hero_image"] for e in stage_emails),
    }

if __name__ == "__main__":
    main()
