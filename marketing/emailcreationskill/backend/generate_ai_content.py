"""
AI Content Generator — Uses Claude to generate email content and hero images.

Generates:
  - Email body content (using LLM)
  - Hero images (using image generation or prompts)
  - Subject lines (optimized for tone/stage)

This is called automatically during A/B testing (Variation B generation).
"""
import logging
import json
from config import CLAUDE_MODEL, ANTHROPIC_API_KEY
import anthropic
import ai_email_templates as templates

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

def generate_email_content(stage: str, event_data: dict) -> dict:
    """
    Generate email content for a given stage using Claude.

    Args:
        stage: One of the AI_STAGE_TEMPLATES keys (e.g., "CFP Launch", "Final Countdown")
        event_data: Dict with keys like event_name, location, dates, early_price, etc.

    Returns:
        {
            "subject": "Generated subject line",
            "preview": "Preview text (preheader)",
            "body": "Full email body content",
            "tone": "Detected tone",
            "key_takeaway": "Main message"
        }
    """
    if not _client:
        log.warning("Claude API not configured. Using template-only mode.")
        return generate_email_content_template_only(stage, event_data)

    template = templates.get_ai_template(stage)
    if not template:
        return {"error": f"Template not found for stage: {stage}"}

    # Fill prompt with event data
    content_prompt = templates.fill_template_placeholders(
        template["content_prompt"],
        event_data
    )
    # AI Template variant (Variant A) style rules — urgency/FOMO, specific copy,
    # clear CTA, bullets over paragraphs, no em dashes. Overrides any conflicting
    # "no urgency" wording in the per-stage content_prompt above.
    content_prompt = f"{content_prompt}\n\n{templates.AI_VARIANT_STYLE_RULES}"

    # Generate subject line
    subject = templates.strip_em_dashes(generate_subject_line(template, event_data))

    try:
        log.info(f"Generating {stage} email content for {event_data.get('event_name')}")

        # Call Claude to generate email body
        message = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": content_prompt
                }
            ]
        )

        body = templates.strip_em_dashes(message.content[0].text if message.content else "")

        return {
            "stage": stage,
            "subject": subject,
            "preview": templates.fill_template_placeholders(
                template["preview_pattern"],
                event_data
            ),
            "body": body,
            "tone": template["tone"],
            "urgency_level": template["urgency_level"],
            "cta_strategy": template["cta_strategy"],
            "key_takeaway": extract_key_takeaway(body, template),
        }

    except Exception as e:
        log.error(f"Error generating content: {e}")
        return {
            "error": str(e),
            "stage": stage,
            "subject": subject,
            "body": "Unable to generate content. Please contact support."
        }

def generate_subject_line(template: dict, event_data: dict) -> str:
    """Generate an optimized subject line from template pattern."""
    pattern = template.get("subject_pattern", "")
    if not pattern:
        return "You're Invited to [EVENT_NAME]"

    # Use template examples as fallback
    examples = template.get("subject_examples", [])
    if examples:
        base_subject = examples[0]
    else:
        base_subject = pattern

    # Fill placeholders
    subject = templates.fill_template_placeholders(base_subject, event_data)

    return subject[:60]  # Email subject line length limit

def generate_hero_image_prompt(stage: str, event_data: dict) -> dict:
    """
    Generate a detailed image generation prompt for the hero image.

    Returns:
        {
            "prompt": "Detailed image generation prompt",
            "size": "600x200",
            "style": "Modern, professional",
        }
    """
    template = templates.get_ai_template(stage)
    if not template:
        return {"error": f"Template not found for stage: {stage}"}

    image_prompt = templates.fill_template_placeholders(
        template["image_prompt"],
        event_data
    )

    return {
        "stage": stage,
        "prompt": image_prompt,
        "size": "600x200",
        "style": template.get("tone", "Modern"),
        "keywords": event_data.get("key_topics", []),
    }

def generate_hero_image_url(stage: str, event_data: dict) -> str:
    """
    Generate a hero image using Claude's vision capabilities or external API.

    For now, returns a prompt that can be used with:
      - DALL-E (via API)
      - Midjourney
      - Stable Diffusion
      - Other image generation services

    TODO: Integrate with actual image generation API
    """
    if not _client:
        log.warning("Image generation not available.")
        return None

    image_prompt_data = generate_hero_image_prompt(stage, event_data)
    image_prompt = image_prompt_data["prompt"]

    log.info(f"Generated image prompt for {stage} email")

    # TODO: Call actual image generation API (DALL-E, etc.)
    # For now, return the prompt for manual use or external service
    return {
        "type": "prompt",
        "prompt": image_prompt,
        "instructions": "Use this prompt with your image generation service (DALL-E, Midjourney, etc.)",
    }

def extract_key_takeaway(body: str, template: dict) -> str:
    """Extract the main message/takeaway from generated content."""
    # For now, use the first sentence or CTA strategy
    lines = body.split("\n")
    for line in lines:
        if len(line.strip()) > 20:
            return line.strip()[:100]

    return template.get("tone", "Important update about the event")

def generate_email_content_template_only(stage: str, event_data: dict) -> dict:
    """Fallback: Generate content using only template patterns (no AI)."""
    template = templates.get_ai_template(stage)
    if not template:
        return {"error": f"Template not found for stage: {stage}"}

    subject = templates.fill_template_placeholders(
        template["subject_pattern"],
        event_data
    )

    # Create placeholder body from template info
    body_parts = [
        f"📧 {template['purpose']}",
        "",
        f"Event: {event_data.get('event_name', 'Event')}",
        f"Location: {event_data.get('location', 'Location')}",
        f"Date: {event_data.get('dates', 'TBD')}",
        "",
        f"Tone: {template['tone']}",
        f"Urgency Level: {template['urgency_level']}/10",
        "",
        "CTAs:",
        "\n".join([f"  • {cta}" for cta in template['cta_strategy']]),
        "",
        f"Note: {template.get('footer_note', 'Thanks for registering!')}",
    ]

    return {
        "stage": stage,
        "subject": subject,
        "preview": templates.fill_template_placeholders(
            template["preview_pattern"],
            event_data
        ),
        "body": "\n".join(body_parts),
        "tone": template["tone"],
        "urgency_level": template["urgency_level"],
        "cta_strategy": template["cta_strategy"],
        "mode": "template-only (no AI)",
    }

# ── Integration Helper ──────────────────────────────────────────────────────

def generate_variation_b_email(stage: str, event_data: dict) -> dict:
    """
    Complete flow to generate Variation B email for A/B testing.

    Returns:
        {
            "variation": "B",
            "stage": "CFP Launch",
            "subject": "Generated subject",
            "preview": "Generated preview",
            "body": "Generated body content",
            "html": "<html>...</html>" (ready for HubSpot),
            "image_prompt": {...} (for hero image),
            "metadata": {...}
        }
    """
    try:
        # Generate content
        content = generate_email_content(stage, event_data)

        # Generate image prompt
        image_data = generate_hero_image_prompt(stage, event_data)

        # Wrap in HTML template (simplified)
        html = wrap_in_html(
            subject=content.get("subject"),
            body=content.get("body"),
            image_prompt=image_data.get("prompt"),
            cta_strategy=content.get("cta_strategy", []),
        )

        return {
            "variation": "B",
            "stage": stage,
            "subject": content.get("subject"),
            "preview": content.get("preview"),
            "body": content.get("body"),
            "html": html,
            "image_prompt": image_data,
            "tone": content.get("tone"),
            "urgency_level": content.get("urgency_level"),
            "generated_at": json.dumps({"timestamp": str(__import__('datetime').datetime.now())}),
            "success": "error" not in content,
        }

    except Exception as e:
        log.error(f"Error generating Variation B: {e}")
        return {
            "variation": "B",
            "error": str(e),
            "success": False,
        }

def wrap_in_html(subject: str, body: str, image_prompt: str = None, cta_strategy: list = None) -> str:
    """
    Wrap generated content in a basic HTML email template.

    Note: This is a simplified version. In production, use HubSpot's template system.
    """
    cta_html = ""
    if cta_strategy:
        cta_buttons = "\n".join([
            f'<a href="#" class="cta-button">{cta}</a>'
            for cta in cta_strategy[:3]
        ])
        cta_html = f"<div class='cta-section'>\n{cta_buttons}\n</div>"

    hero_html = ""
    if image_prompt:
        hero_html = f"""
        <div class='hero-section'>
            <p style='font-size: 10px; color: #999;'>
                [Hero Image: {image_prompt[:100]}...]
            </p>
        </div>
        """

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
        .container {{ max-width: 600px; margin: 0 auto; }}
        .header {{ background: #f5f5f5; padding: 20px; }}
        .content {{ padding: 20px; }}
        .cta-button {{
            display: inline-block;
            background: #0066cc;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 4px;
            margin: 10px 5px 10px 0;
        }}
        .cta-section {{ margin: 20px 0; }}
        .footer {{ background: #f5f5f5; padding: 20px; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{subject}</h1>
        </div>
        {hero_html}
        <div class="content">
            {body.replace(chr(10), '<br>')}
        </div>
        {cta_html}
        <div class="footer">
            <p>This is an automated email. Please do not reply directly.</p>
        </div>
    </div>
</body>
</html>
"""
    return html

# ── Example Usage ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example event data
    example_event = {
        "event_name": "PyTorch Conference Europe",
        "location": "Amsterdam, Netherlands",
        "dates": "September 12-14, 2026",
        "month": "September",
        "early_price": "$799",
        "regular_price": "$999",
        "savings_amount": "$200",
        "discount_price": "$599",
        "deadline_date": "August 15, 2026",
        "days_left": 25,
        "time_left": "25 days",
        "key_topics": ["PyTorch", "AI/ML", "Distributed Training", "MLOps"],
        "session_count": "150+",
        "speaker_count": "50+",
    }

    # Generate content for each stage
    for stage in templates.get_ai_stage_names():
        log.info(f"\n--- {stage} ---")
        result = generate_email_content(stage, example_event)
        if "error" not in result:
            log.info(f"Subject: {result.get('subject')}")
            log.info(f"Tone: {result.get('tone')}")
        else:
            log.error(f"Error: {result.get('error')}")
