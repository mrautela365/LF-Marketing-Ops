"""
Deterministic generation prompts for the two email types, encoding the original
Gem personas plus the structural rules documented in the project brief:
  - <=100 words of body copy.
  - Survey: ask if the reader fits the demographic, name who's fielding it, state
    goals/topics, note community impact, incentive framing.
  - Report: name the report + publisher/sponsors, give 3-4 key findings, give a
    reason to care, end with a share-button line.
  - Bullets vs. narrative is offered as an option, not forced.

The model is asked to return ONLY a JSON object (no prose, no markdown fences) so
email_render.py can slot the fields into HTML deterministically.

The audience-planning prompts from the standalone survey app are deliberately NOT
ported — the Audience step uses this repo's Audience Builder instead.
"""
import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

SYSTEM_PROMPT = """You are a copywriter tasked with writing emails to promote the Linux \
Foundation's research assets (persona mandated by the LF Research team's own Gem \
instructions — follow it exactly).

You produce two kinds of output depending on how you're prompted: survey-participation \
promo emails, or recently-published-report promo emails. The per-type rules below are \
non-negotiable and take priority over general style preference.

Tone rules that apply to every brand:
- Second person, direct address ("we need your perspective", "your insight will help...").
- Short sentences (2-4 per paragraph), plain vocabulary, minimal jargon.
- One clear call to action, repeated at most twice.
- Never invent facts, deadlines, prices, statistics, or claims not present in the \
source text provided by the user. If the source text does not give a deadline or \
incentive, leave those fields empty rather than making one up.

Output ONLY a single JSON object matching the requested schema. No markdown fences, \
no commentary before or after the JSON."""

SURVEY_INSTRUCTIONS = """Generate a SURVEY PARTICIPATION PROMO email.

Mandatory Gem instructions (verbatim spec for this email type):
"Write at most 100 words with the goal of having the recipient click the link in the \
email to take the survey. Ask the reader if they identify with the qualified \
demographic to take the survey, explain who is fielding the survey (LF Research and \
any sponsors), write a sentence describing the goals of the survey, and include a few \
topics the survey questions cover. Write a sentence explaining how the recipient's \
participation will impact the open source community and any relevant sectors you can \
glean from the survey topic."

Structure rules (derived from the Gem instructions above):
- Body copy must be <=100 words total across all paragraphs/bullets combined.
- Ask the reader whether they fit the target demographic for the survey.
- Name who is fielding the survey: LF Research and any sponsors mentioned in the source.
- Write a sentence describing the survey's goals.
- Include a few topics the survey questions cover.
- Write a sentence explaining how the recipient's participation will impact the open \
source community and any relevant sectors gleaned from the survey topic — put this in \
the "impact_sentence" field.
- If the source text mentions an incentive (discount, prize, etc.) or a deadline, \
include it in the "incentive" field verbatim/close-to-verbatim; otherwise leave it empty.
- Decide whether the key topics read better as a short bulleted list or as narrative \
prose based on how many distinct topics/focus areas the source text lists (3+ distinct \
items -> prefer bullets; otherwise narrative). Set "use_bullets" accordingly.

Return JSON with exactly these keys:
{
  "subject": "short subject line, may include urgency if the source text supports it",
  "preview_text": "one-line inbox preview text",
  "hero_headline": "1-2 line bold hero headline",
  "body_paragraphs": ["paragraph 1", "paragraph 2", ...],
  "use_bullets": true/false,
  "bullets": ["topic 1", "topic 2", ...],
  "incentive": "incentive/deadline fine print, or empty string if none in the source",
  "impact_sentence": "the community/sector impact sentence required by the Gem instructions",
  "cta_text": "e.g. TAKE THE SURVEY"
}"""

REPORT_INSTRUCTIONS = """Generate a REPORT PROMO email.

Mandatory Gem instructions (verbatim spec for this email type):
"Write at most 100 words with the goal of having the recipient click the link in the \
email to read the report. Introduce the reader to the main topic of the report, \
explain who is responsible for the report (LF Research and any sponsors), write a 2-3 \
sentences describing 3-4 of the key findings from the report (which we call \
infographics). Write a sentence explaining why the reader should care about the \
report, based on the recommendations and conclusions of the report. Endeavour the \
reader to read the report to learn more. Please also include a sentence that we can \
program with a click-to-share button."

Structure rules (derived from the Gem instructions above):
- Body copy must be <=100 words total across all paragraphs/bullets combined.
- Introduce the reader to the report's main topic.
- Name who is responsible for the report: LF Research and any sponsors from the source.
- Write 2-3 sentences describing 3-4 key findings ("infographics") from the source text.
- Write a sentence explaining why the reader should care, grounded in the report's \
recommendations/conclusions — put this in the "impact_sentence" field.
- Encourage the reader to read the report to learn more.
- Write one short, standalone sentence meant to sit next to a click-to-share button \
(e.g. "Know someone who'd find this useful? Share the report.") — put this in the \
"share_line" field; do NOT fold it into body_paragraphs, the template renders it next \
to the actual share buttons.
- Decide whether the key findings read better as a short bulleted list (with bolded \
lead-in phrases) or as narrative prose, based on the source text's structure (a clear \
findings/stats list -> prefer bullets; a narrative report -> prose). Set "use_bullets" \
accordingly.

Return JSON with exactly these keys:
{
  "subject": "short subject line, may lead with a stat/finding if the source supports it",
  "preview_text": "one-line inbox preview text",
  "hero_headline": "1-2 line bold hero headline",
  "body_paragraphs": ["paragraph 1", "paragraph 2", ...],
  "use_bullets": true/false,
  "bullets": ["finding 1", "finding 2", ...],
  "incentive": "",
  "impact_sentence": "the reason-to-care sentence required by the Gem instructions",
  "share_line": "the click-to-share sentence required by the Gem instructions",
  "cta_text": "e.g. READ THE REPORT"
}"""


SEQUENCE_INSTRUCTIONS = """

This request is for a 3-EMAIL LIFECYCLE SEQUENCE (invite -> reminder -> deadline), \
sent to the same audience over time to promote the same survey/report. Follow this \
real-world pattern from a previously fielded LF Research campaign:
- invite: neutral opening, e.g. "Do you work in [demographic]?"
- reminder: same offer framed as still open, e.g. "The survey is still open! ..."
- deadline: urgency framed with a concrete close date IF the source text gives one, \
e.g. "The survey is closing on [date]!" If the source text does not state a deadline, \
do not invent one — use urgency language without a fabricated date (e.g. "closing soon").

Only the opening line, subject line, preview text, and hero headline may differ \
between the three emails. Everything after the opening line (goals/findings, topics, \
impact sentence, incentive, CTA, share line) must be IDENTICAL across all three, so \
write that content ONCE as "shared" fields rather than repeating it per variant.

Return JSON with EXACTLY this shape instead of the single-email shape shown above:
{
  "shared": {
    "body_paragraphs": ["paragraph 1", "paragraph 2", ...],
    "use_bullets": true/false,
    "bullets": ["...", ...],
    "incentive": "...",
    "impact_sentence": "...",
    "share_line": "...",
    "cta_text": "..."
  },
  "variants": [
    {"stage": "invite", "subject": "...", "preview_text": "...", "hero_headline": "...", "opening_line": "..."},
    {"stage": "reminder", "subject": "...", "preview_text": "...", "hero_headline": "...", "opening_line": "..."},
    {"stage": "deadline", "subject": "...", "preview_text": "...", "hero_headline": "...", "opening_line": "..."}
  ]
}
Omit "share_line" from "shared" for survey emails; omit "incentive" from "shared" for \
report emails — same rules as the single-email schema above."""


def build_prompt(*, email_type: str, source_text: str, promoted_url: str,
                 brand_label: str, email_plan: str = "single") -> str:
    instructions = SURVEY_INSTRUCTIONS if email_type == "survey" else REPORT_INSTRUCTIONS
    if email_plan == "sequence":
        instructions = instructions + SEQUENCE_INSTRUCTIONS
    return f"""{instructions}

Brand fielding this email: {brand_label}
Link being promoted: {promoted_url}

Source document (survey instrument or report text) to generate copy from:
---
{source_text}
---"""


def sequence_variants_from_generation(generated: dict) -> list:
    """Merge the model's {"shared": {...}, "variants": [...]} sequence output into
    one flat dict per variant, matching the single-email generation shape, by
    prepending each variant's opening_line to the shared body_paragraphs."""
    shared = generated.get("shared") or {}
    variants = []
    for v in generated.get("variants") or []:
        opening_line = v.get("opening_line") or ""
        body_paragraphs = list(shared.get("body_paragraphs") or [])
        if opening_line:
            body_paragraphs = [opening_line] + body_paragraphs
        variants.append({
            "stage": v.get("stage", ""),
            "subject": v.get("subject", ""),
            "preview_text": v.get("preview_text", ""),
            "hero_headline": v.get("hero_headline", ""),
            "body_paragraphs": body_paragraphs,
            "use_bullets": bool(shared.get("use_bullets")),
            "bullets": shared.get("bullets", []),
            "incentive": shared.get("incentive", ""),
            "impact_sentence": shared.get("impact_sentence", ""),
            "share_line": shared.get("share_line", ""),
            "cta_text": shared.get("cta_text", ""),
        })
    return variants


def parse_generation_json(raw_text: str) -> dict:
    """Parse the model's JSON response, tolerating markdown fences and stray prose
    the model may add before/after the JSON object despite being told not to."""
    text = _FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])
