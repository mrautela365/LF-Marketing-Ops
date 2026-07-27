"""
Email Content Analysis and Optimization Module

Analyzes generated email content using Claude AI to identify improvements
in: subject line effectiveness, CTA optimization, tone, urgency, length,
formatting, personalization, and email marketing best practices.
"""

import os
import json
from anthropic import Anthropic
from typing import Dict, List, Any

client = Anthropic()

def analyze_and_improve_email(
    email_subject: str,
    email_body: str,
    email_preview: str,
    event_data: Dict[str, Any] = None,
    event_type: str = "General Event"
) -> Dict[str, Any]:
    """
    Analyze email content and generate improvement recommendations.

    Args:
        email_subject: Email subject line
        email_body: Email body HTML content
        email_preview: Email preview text
        event_data: Event context (name, dates, location, etc.)
        event_type: Type of event (CFP Launch, Schedule Announcement, etc.)

    Returns:
        {
            "analysis": {
                "subject_line": {...},
                "cta": {...},
                "tone": {...},
                "engagement": {...},
                "formatting": {...},
                "personalization": {...}
            },
            "improvements": [
                {
                    "category": "subject_line",
                    "issue": "Subject line is too long",
                    "recommendation": "Shorten to under 50 chars",
                    "improved_version": "New subject line",
                    "impact": "Higher open rates (est. +5-10%)"
                },
                ...
            ],
            "improved_email": {
                "subject": "Improved subject",
                "preview": "Improved preview",
                "body": "Improved HTML body"
            },
            "overall_score": 7.5,
            "summary": "Email is well-structured but CTA could be stronger..."
        }
    """

    context = f"""
Event Type: {event_type}
Event Data: {json.dumps(event_data or {})}

Current Email:
Subject: {email_subject}
Preview: {email_preview}
Body: {email_body[:2000]}...  [Content truncated for analysis]
"""

    analysis_prompt = f"""Analyze this marketing email for optimization opportunities:

{context}

Provide a detailed analysis in JSON format with:

1. **subject_line** analysis:
   - effectiveness (1-10 score)
   - length (current vs recommended)
   - issues (generic, lacks urgency, no emoji/power words, etc.)
   - improved_version (specific suggestion)

2. **cta** (Call-to-Action) analysis:
   - clarity (1-10)
   - placement (multiple CTAs, position in email)
   - urgency_level (high/medium/low)
   - improved_version (specific suggestion)

3. **tone** analysis:
   - current_tone (formal, casual, urgent, friendly, etc.)
   - appropriate_for_audience (yes/no + why)
   - improvements_needed (specific suggestions)

4. **engagement** analysis:
   - opening_hook_strength (1-10)
   - personalization_level (none/basic/strong)
   - emotional_appeal (1-10)
   - improvements (specific changes)

5. **formatting** analysis:
   - readability (1-10)
   - visual_hierarchy (issues)
   - mobile_friendly (yes/no + issues)
   - improvements (specific changes)

6. **personalization** analysis:
   - current_level (none/basic/strong)
   - opportunities (missing personalization angles)
   - improved_version (example of more personalized version)

Return JSON with:
{
  "analysis": {
    "subject_line": {...},
    "cta": {...},
    "tone": {...},
    "engagement": {...},
    "formatting": {...},
    "personalization": {...}
  },
  "improvements": [
    {
      "category": "category_name",
      "issue": "specific issue found",
      "recommendation": "what to improve",
      "improved_version": "specific improved text or version",
      "impact": "expected positive impact on metrics"
    },
    ...
  ],
  "improved_email": {
    "subject": "improved subject line",
    "preview": "improved preview text",
    "body": "improved email body with HTML"
  },
  "overall_score": 7.5,
  "summary": "2-3 sentence summary of main improvements and overall assessment"
}

Focus on practical, implementable improvements. Be specific with examples.
For HTML body, preserve the structure but improve content, CTAs, and formatting.
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": analysis_prompt
                }
            ]
        )

        result_text = response.content[0].text

        # Extract JSON from response
        try:
            # Try to find JSON block
            if "```json" in result_text:
                json_start = result_text.find("```json") + 7
                json_end = result_text.find("```", json_start)
                json_str = result_text[json_start:json_end].strip()
            elif "```" in result_text:
                json_start = result_text.find("```") + 3
                json_end = result_text.find("```", json_start)
                json_str = result_text[json_start:json_end].strip()
            else:
                json_str = result_text

            analysis_result = json.loads(json_str)
            return analysis_result

        except json.JSONDecodeError:
            # If JSON parsing fails, return structured error response
            return {
                "error": "Failed to parse analysis response",
                "raw_response": result_text,
                "analysis": {},
                "improvements": [],
                "improved_email": {
                    "subject": email_subject,
                    "preview": email_preview,
                    "body": email_body
                },
                "overall_score": 0,
                "summary": "Analysis could not be completed"
            }

    except Exception as e:
        return {
            "error": str(e),
            "analysis": {},
            "improvements": [],
            "improved_email": {
                "subject": email_subject,
                "preview": email_preview,
                "body": email_body
            },
            "overall_score": 0,
            "summary": f"Error during analysis: {str(e)}"
        }


def optimize_subject_line(subject: str, event_type: str = "General") -> Dict[str, Any]:
    """
    Specifically optimize a subject line using Claude.

    Returns:
        {
            "original": "original subject",
            "improvements": [
                {
                    "version": "improved subject",
                    "strategy": "what makes this better",
                    "estimated_lift": "5-10%"
                },
                ...
            ]
        }
    """

    prompt = f"""Analyze and improve this email subject line for {event_type}:

Subject: {subject}

Generate 3-5 improved versions that:
1. Are under 60 characters
2. Use power words or urgency (if appropriate)
3. Are specific and benefit-focused
4. Are free of spam trigger words
5. Include emoji if relevant (but not excessive)

Return JSON:
{{
  "original": "{subject}",
  "improvements": [
    {{
      "version": "improved subject line",
      "strategy": "why this is better",
      "estimated_lift": "5-10%"
    }},
    ...
  ],
  "recommendation": "which version to use and why"
}}
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        result_text = response.content[0].text

        # Extract JSON
        if "```json" in result_text:
            json_start = result_text.find("```json") + 7
            json_end = result_text.find("```", json_start)
            json_str = result_text[json_start:json_end].strip()
        elif "```" in result_text:
            json_start = result_text.find("```") + 3
            json_end = result_text.find("```", json_start)
            json_str = result_text[json_start:json_end].strip()
        else:
            json_str = result_text

        return json.loads(json_str)

    except Exception as e:
        return {
            "error": str(e),
            "original": subject,
            "improvements": []
        }


def generate_cta_variants(
    current_cta_text: str,
    goal: str = "registration",
    urgency: str = "medium"
) -> Dict[str, Any]:
    """
    Generate optimized CTA (Call-to-Action) variants.

    Args:
        current_cta_text: Current CTA text
        goal: What the CTA should achieve (registration, download, sign-up, etc.)
        urgency: Urgency level (low, medium, high)

    Returns:
        {
            "original": "current CTA",
            "variants": [
                {
                    "text": "CTA text",
                    "strategy": "what makes this effective",
                    "effectiveness": "high/medium/low",
                    "best_for": "use case"
                },
                ...
            ]
        }
    """

    prompt = f"""Generate optimized Call-to-Action (CTA) variants.

Current CTA: {current_cta_text}
Goal: {goal}
Urgency Level: {urgency}

Create 4-5 CTA variants that:
1. Are action-oriented and specific
2. Use power words appropriate for urgency level
3. Include micro-copy hints (→, →, etc. if applicable)
4. Are 2-5 words maximum
5. Create clear value proposition

Return JSON:
{{
  "original": "{current_cta_text}",
  "goal": "{goal}",
  "variants": [
    {{
      "text": "CTA button text",
      "strategy": "why this works",
      "effectiveness": "high/medium/low",
      "best_for": "use case description"
    }},
    ...
  ],
  "recommendation": "which variant to use and why"
}}
"""

    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        result_text = response.content[0].text

        # Extract JSON
        if "```json" in result_text:
            json_start = result_text.find("```json") + 7
            json_end = result_text.find("```", json_start)
            json_str = result_text[json_start:json_end].strip()
        elif "```" in result_text:
            json_start = result_text.find("```") + 3
            json_end = result_text.find("```", json_start)
            json_str = result_text[json_start:json_end].strip()
        else:
            json_str = result_text

        return json.loads(json_str)

    except Exception as e:
        return {
            "error": str(e),
            "original": current_cta_text,
            "variants": []
        }


def format_analysis_report(analysis: Dict[str, Any]) -> str:
    """
    Format analysis results into a readable report for display.
    """

    report = []
    report.append("=" * 80)
    report.append("📊 EMAIL CONTENT ANALYSIS & OPTIMIZATION REPORT")
    report.append("=" * 80)
    report.append("")

    # Overall score
    if "overall_score" in analysis:
        score = analysis["overall_score"]
        report.append(f"📈 Overall Score: {score}/10")
        report.append("")

    # Summary
    if "summary" in analysis:
        report.append(f"📝 Summary:\n{analysis['summary']}")
        report.append("")

    # Improvements
    if "improvements" in analysis and analysis["improvements"]:
        report.append("✨ KEY IMPROVEMENTS IDENTIFIED:")
        report.append("-" * 80)

        for i, improvement in enumerate(analysis["improvements"], 1):
            category = improvement.get("category", "").replace("_", " ").title()
            issue = improvement.get("issue", "")
            recommendation = improvement.get("recommendation", "")
            impact = improvement.get("impact", "")
            improved = improvement.get("improved_version", "")

            report.append(f"\n{i}. {category}")
            report.append(f"   Issue: {issue}")
            report.append(f"   Recommendation: {recommendation}")
            if improved:
                report.append(f"   Improved Version: {improved}")
            if impact:
                report.append(f"   Impact: {impact}")

        report.append("")

    # Detailed analysis sections
    if "analysis" in analysis:
        report.append("📋 DETAILED ANALYSIS:")
        report.append("-" * 80)

        for section_name, section_data in analysis["analysis"].items():
            if section_data:
                report.append(f"\n{section_name.replace('_', ' ').title()}:")
                for key, value in section_data.items():
                    if key != "improved_version":
                        report.append(f"  • {key.replace('_', ' ').title()}: {value}")

    report.append("\n" + "=" * 80)

    return "\n".join(report)
