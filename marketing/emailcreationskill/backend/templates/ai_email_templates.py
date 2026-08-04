"""
Open Source Event Email Templates — 2025–2026 Standards (REFINED)

Follows community-driven, educational design standards used by:
- Linux Foundation, CNCF, OpenSSF, RISC-V
- GitHub, Google Cloud, AWS, HashiCorp
- Kubernetes, Observability, and infrastructure communities

REFINED FOR 2025-2026 B2B TECHNOLOGY & OPEN-SOURCE STANDARDS:
  • Single primary objective per email
  • 30–60 second reading experience
  • Information hierarchy enforced (headline → intro → CTA → content)
  • Community manager tone (not marketer)
  • Content density reduced (2-3 sentences, 25-60 words per paragraph)
  • One idea per section
  • 1 primary CTA, max 2 supporting CTAs
  • Scannable structure (headings, bullets, whitespace)
  • Mobile-first design
  • Accessible (WCAG)
  • No unnecessary sections (only relevant to stage)
  • Internal validation before returning

Writing Rules:
  • Paragraphs: 2–3 sentences, 25–60 words max
  • Bullets: 3–5 items, short phrases
  • CTAs: 1 primary, 0–2 secondary (max 3 total)
  • No marketing buzzwords, clickbait, or fake urgency
  • Authentic, educational, community-focused tone
"""

from datetime import datetime
import json
import re

# ── AI Template variant (Variant A) — mandatory style rules ──────────────────
# Applies ONLY to the "AI Template" variant generators (generate_ai_template_content
# in core/agent.py and generate_email_content in generate_ai_content.py). Does NOT
# apply to Variant B (reference-driven) or the pre-written messaging-variant
# strategies in email_templates.py.
AI_VARIANT_STYLE_RULES = """━━━ MANDATORY STYLE RULES — AI TEMPLATE VARIANT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
These rules OVERRIDE any "no urgency", "no fake urgency", "authentic, not
promotional", or "community manager tone" wording in the Content guidance above.
You are not a technical writer explaining an event — you are a senior lifecycle
marketer and conversion copywriter whose only objective is to maximize clicks on
the primary CTA. Redesign the email from the ground up around that objective;
do not default to a documentation-style rundown of the event just because that
information exists.

FACTUAL GUARDRAIL (non-negotiable, applies to every rule below):
Everything below is about psychology, structure, and wording, never about
inventing content. Only use the real facts given below (dates, prices,
deadlines, speakers, benefits, ticket tiers). Never invent a deadline, price,
speaker, statistic, capacity number, or scarcity claim that isn't provided.
When a real urgency angle doesn't exist yet for this stage, use this stage's
"Urgency & FOMO" guidance from INDUSTRY BEST PRACTICES below instead of
fabricating one.

1. URGENCY IS THE CENTRAL THEME, not a garnish. Every section should reinforce,
   in its own way, that acting today beats acting later — using whatever real
   facts apply (a real price increase, a real deadline, real limited capacity,
   funding/CFP review already underway, travel and visa lead time for
   international attendees). The reader should feel "I should do this now," not
   "I'll come back later." If no real deadline exists for this stage, lean on
   the stage's non-clock-based FOMO guidance (momentum, competitive scarcity,
   what-you'd-miss) instead of manufacturing a countdown.
2. CREATE GENUINE FOMO BY FRAMING LOSS, not by listing features. Every major
   section should implicitly or explicitly answer "what do I lose if I wait?"
   (a lower price, a funding/speaker slot, planning time, a chance to be in the
   room with this community). Use loss-aversion naturally, never in a way that
   reads as manipulative or that requires an invented fact to work.
3. WRITE TO PERSUADE, NOT TO INFORM. Do not write "Who Should Attend," "What's
   Included," or similar sections as a dry, documentation-style list of facts.
   Every sentence must move the reader toward the CTA. If a sentence or section
   doesn't build urgency, desire, credibility, or directly support the CTA, cut
   it or rewrite it, even if that means the section shrinks to one line or
   disappears. Real facts (audience segments, inclusions) must still be
   represented somewhere and never dropped, but woven into persuasive, benefit-
   or outcome-framed copy rather than presented as a flat bullet dump.
4. OPENING HOOK must NOT start by explaining what the event is. The reader
   already opened the email. Open instead with why TODAY matters and what
   happens if they wait: the real reason to act now, in 1-2 sentences, before
   any background on the event itself. Never lead with a vague label like "the
   flagship conference" or "the premier event."
5. CTA WORDING must fuse action with urgency, not just be an action verb.
   Prefer stage-appropriate variants like "Apply Before Prices Increase,"
   "Secure Funding Today," "Submit Your Talk Before the CFP Closes," "Register
   Before the Price Increase" over a plain "Register Now" or a generic "Explore
   [Event Name]"/"Learn More"/"Click Here." Match the verb to the stage's real
   goal (register vs. submit vs. sponsor vs. view agenda) and only reference a
   deadline/price change that is real and provided above.
6. CUT LOW-VALUE CONTENT. Remove or drastically shrink generic event
   descriptions, long explanatory sections (e.g. an "About the Scholarship"-
   style paragraph), and obvious, non-differentiating inclusions (coffee,
   recordings, a t-shirt) unless a specific inclusion genuinely removes a real
   objection to acting now. The email should end up shorter and more focused
   than a standard informational email, not padded to cover every scraped fact.
7. DESCRIBE OUTCOMES, NOT FEATURES. Instead of "network with professionals,"
   help the reader picture the payoff: who they'll meet, what they'll walk away
   knowing, what problem they'll be closer to solving. Ground every outcome
   claim in the real speakers/topics/description given below, never invented
   specifics.
8. CREDIBILITY should read naturally, not as a fabricated stat. Lean on real,
   already-true trust signals (a Linux Foundation / named-foundation event,
   named confirmed speakers, real sponsor/partner names, real past-edition
   facts if given) rather than inventing numbers or testimonials.
9. OPTIMIZE FOR A SUB-20-SECOND SCAN. Paragraphs max 2-3 short sentences.
   Prefer bullets (<ul><li>) over paragraphs for any list of 2+ items. Bold
   text is reserved for the single most critical deadline or price fact, not
   used decoratively. Put the highest-value message before the first CTA. Cut
   repetition. Every paragraph should do exactly one job: build urgency, build
   desire, build credibility, remove hesitation, or drive the CTA — if it does
   none of those, remove it.
10. EVERY SECTION MUST SERVE THE PRIMARY CTA. Do not include a section just
    because the source data exists for it. Reorder, merge, shrink, or drop
    sections freely if doing so makes the email more persuasive — completeness
    is not the goal, conversion is.
11. WORD VARIETY: never repeat the same keyword, topic phrase, or descriptor
    two or more times in close proximity (e.g. the event's core theme name
    appearing in the hook, a bullet, AND the CTA). Vary the phrasing after the
    first mention.
12. NEVER use an em dash (—) anywhere in the output. Use a period, comma, or
    "and" instead.
13. SPEAKERS SECTION HEADING: default to "Featured Speakers" rather than
    "Confirmed Speakers" unless the event data explicitly states the full
    speaker roster is final/complete.

Final bar: the output should read like it was written by an experienced
lifecycle-marketing team optimizing for conversions, while remaining factually
accurate and Linux-Foundation-professional, never manipulative or invented.
"""


def strip_em_dashes(text: str) -> str:
    """Safety net: replace stray em/en dashes with a comma or period.

    Backstop for AI_VARIANT_STYLE_RULES' "no em dash" instruction, in case the
    model ignores the prompt rule. Only intended for AI Template variant output.
    """
    if not text:
        return text
    # " word — word " -> " word, word " (dash used as a clause separator)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    return text


AI_STAGE_TEMPLATES = {
    "CFP Launch": {
        "stage_name": "CFP Launch",
        "purpose": "Recruit speakers from the community",
        "timing": "3-4 months before event",
        "tone": "Welcoming, inclusive, community-focused",
        "urgency_level": 6,
        "subject_pattern": "🎤 Call for Proposals: Share Your Work at [EVENT_NAME]",
        "subject_examples": [
            "🎤 Share Your Story: CFP Open for [EVENT_NAME]",
            "We want to hear from you: CFP for [EVENT_NAME]",
        ],
        "preview_pattern": "Submit a talk by [DATE]. First-time speakers welcome.",

        "content_prompt": """Generate a CFP email for open-source community recruitment.

PRIMARY OBJECTIVE: Recruit speakers. EVERY section must support this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- CFP Deadline: [DEADLINE]
- Topics: [TOPICS]

REQUIRED INFORMATION HIERARCHY (DO NOT DEVIATE):
1. HEADLINE: "Share Your Work at [EVENT_NAME]"

2. INTRODUCTION (30-50 words MAXIMUM, 2 sentences only)
   Start: "We're building the speaker lineup for [EVENT_NAME]."
   Hook: Explain why their voice matters to the community.
   RULE: Only these two ideas. No event details, no schedule, no pricing.

3. PRIMARY CTA: [ Submit Your Proposal ]

4. WHY SPEAK (60-80 words, 2-3 sentences)
   One idea only: Why speaking matters to the community.
   Lead with value to speakers, not value to event.

5. WHAT WE'RE LOOKING FOR (80-100 words)
   Use bullet format:
   • Talk type 1 (with example)
   • Talk type 2 (with example)
   • Explicitly: "First-time speakers—mentorship available"
   • Story-based over product pitches

6. IMPORTANT DATES (dates only, no narrative)
   CFP Deadline: [DATE]
   Notifications: [DATE]
   Event: [DATES]

7. FOOTER with support contact for questions

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Split any longer content into multiple paragraphs
- Whitespace BETWEEN every paragraph

CTA ENFORCEMENT:
- 1 PRIMARY CTA ONLY: "Submit Your Proposal"
- 0 SECONDARY CTAs
- NO unrelated CTAs (no sponsorship, no community links, no travel)

WORD REPETITION RULES:
- First mention: [EVENT_NAME]
- After that: "the conference," "the event," or "it"
- Reduce full event name repetition

SECTIONS TO REMOVE (not relevant to CFP):
- Travel information
- Sponsorship opportunities
- Venue details
- Logistics
- Membership
- Community links
- Agenda details

TONE & VOICE:
✓ Community manager voice
✓ First-timers explicitly welcome
✓ Focus on SPEAKER contribution to community
✓ Authentic, factual, educational
✗ NO "amazing," "revolutionary," "don't miss"
✗ NO marketing speak
✗ NO fake urgency

VALUE BEFORE DETAILS:
- Explain WHY this matters before asking for action
- Help readers understand benefit before requirements

INTERNAL VALIDATION (BEFORE RETURNING EMAIL):
□ Single objective: Recruit speakers only
□ Every section supports speaker recruitment
□ Opening: 30-50 words, 2 sentences, single idea
□ Information hierarchy: headline → intro → CTA → content → dates → footer
□ One primary CTA only (Submit Your Proposal)
□ Zero unrelated CTAs
□ No unnecessary sections (no travel, sponsorship, logistics)
□ No paragraph exceeds 3 sentences or 60 words
□ Mobile-friendly single column
□ Scannable in under 1 minute
□ Authentic tone (not promotional)
□ Word count: 200-280 words
□ All required sections present
□ All unnecessary sections removed

IF ANY RULE FAILS: Revise the email before returning.

WORD COUNT TARGET: 200-280 words""",

        "cta_strategy": [
            "Primary: Submit Your Proposal (link to CFP form)",
        ],
        "footer_note": "First-time speakers: we offer mentorship and support. Questions? Reply to this email.",
    },

    "Schedule Announcement": {
        "stage_name": "Schedule Announcement",
        "purpose": "Introduce speaker lineup and show learning opportunities",
        "timing": "4-8 weeks before event",
        "tone": "Educational, professional, community-focused",
        "urgency_level": 5,
        "subject_pattern": "📋 [EVENT_NAME] Schedule: [X] Talks on [TOPIC]",
        "subject_examples": [
            "📋 Schedule Released: [SPEAKER_COUNT]+ Speakers at [EVENT_NAME]",
            "Here's what you'll learn at [EVENT_NAME]",
        ],
        "preview_pattern": "[SESSION_COUNT]+ sessions. [SPEAKER_COUNT]+ speakers. Build your agenda.",

        "content_prompt": """Generate a Schedule Announcement email for open-source community.

PRIMARY OBJECTIVE: Showcase learning opportunities. EVERY section must support this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Sessions: [SESSION_COUNT]
- Speakers: [SPEAKER_COUNT]
- Topics: [TOPICS]

REQUIRED INFORMATION HIERARCHY (DO NOT DEVIATE):
1. HEADLINE: "[EVENT_NAME] Schedule is Live"

2. INTRODUCTION (30-50 words, 2 sentences)
   Announce: Schedule is available
   Value: What attendees will learn
   RULE: Only these two ideas. No pricing, no logistics, no other details.

3. PRIMARY CTA: [ View Full Schedule ]

4. LEARNING TRACKS (100-120 words, organized by track)
   Format per track:
   "[TRACK_NAME]: [SESSION_COUNT] sessions
   • [Session title 1]
   • [Session title 2]
   • [Session title 3]"
   Maximum 3 tracks featured (don't list all).

5. FEATURED SPEAKERS (60-80 words)
   Format: "Speaker Name on Topic" (name + topic only, no photos needed)
   List 3-4 top speakers
   Keep it short

6. SECONDARY CTA (optional): [ Register to Attend ]

7. FOOTER

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Use bullets for track listings
- Whitespace BETWEEN paragraphs

CTA ENFORCEMENT:
- 1 PRIMARY CTA: "View Full Schedule"
- 1 OPTIONAL SECONDARY CTA: "Register"
- NO unrelated CTAs (no sponsors, no travel, no community)

SECTIONS TO REMOVE (not for this stage):
- Sponsorship information
- Travel details
- Pricing (belongs in Registration Push email)
- Logistics
- Call for Proposals
- Membership
- Post-event content

TONE & VOICE:
✓ Educational focus: "Learn from experts"
✓ Concrete session titles (not generic)
✓ Breadth shown: Multiple tracks
✓ Community perspective: "Peer learning"
✗ NO marketing hype
✗ NO "don't miss"
✗ NO false urgency

VALUE BEFORE DETAILS:
- Opening explains WHAT attendees will learn
- Before listing tracks, explain value

INTERNAL VALIDATION:
□ Single objective: Showcase learning only
□ Every section supports learning opportunity
□ Opening: 30-50 words, 2 sentences
□ Information hierarchy: headline → intro → CTA → tracks → speakers → footer
□ One primary CTA: "View Full Schedule"
□ Maximum 1 secondary CTA: "Register"
□ No pricing, logistics, or sponsorship info
□ No paragraph exceeds 3 sentences or 60 words
□ Bullets used for track listing
□ Mobile-friendly
□ Scannable in <1 minute
□ Authentic tone
□ Word count: 200-280 words

IF ANY RULE FAILS: Revise before returning.

WORD COUNT TARGET: 200-280 words""",

        "cta_strategy": [
            "Primary: View Full Schedule (schedule/agenda link)",
            "Secondary: Register to Attend (registration page)",
        ],
        "footer_note": "Early registration helps us plan better. See you soon.",
    },

    "Registration Push / Pricing Deadline": {
        "stage_name": "Registration Push",
        "purpose": "Drive registrations before deadline",
        "timing": "2-4 weeks before event",
        "tone": "Direct, value-focused, factual",
        "urgency_level": 7,
        "subject_pattern": "🎟️ Early bird ends [DATE]: Register for [EVENT_NAME]",
        "subject_examples": [
            "🎟️ Early bird pricing ends [DATE]",
            "Register before [DATE] and save [AMOUNT]",
        ],
        "preview_pattern": "Registration closes [DATE]. Early bird pricing available now.",

        "content_prompt": """Generate a Registration Push email for open-source community.

PRIMARY OBJECTIVE: Drive registrations. EVERY section must support this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Early Price: [EARLY_PRICE]
- Regular Price: [REGULAR_PRICE]
- Savings: [SAVINGS_AMOUNT]
- Deadline: [DEADLINE]
- Days Left: [DAYS_LEFT]

REQUIRED INFORMATION HIERARCHY:
1. HEADLINE: "Early Bird Pricing Ends [DEADLINE]"

2. INTRODUCTION (30-50 words, 2 sentences)
   Line 1: Early bird closes [DATE]
   Line 2: State savings amount
   RULE: Only deadline + savings. No event description.

3. PRIMARY CTA: [ Register Now ]

4. WHAT'S INCLUDED (80-100 words, bullets)
   • Access to [SESSION_COUNT]+ sessions
   • Workshops on [TOPIC_1], [TOPIC_2]
   • Networking with [ATTENDEE_COUNT]+ community members
   • [One additional specific benefit]

5. PRICING SECTION (40-60 words, clear format)
   Early Bird: [EARLY_PRICE] (through [DEADLINE])
   Standard: [REGULAR_PRICE] (after [DEADLINE])
   Savings: [SAVINGS_AMOUNT]

6. SECONDARY CTA (optional): [ View All Options ]

7. FOOTER

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Use bullets for benefits
- Use structured format for pricing
- Whitespace BETWEEN paragraphs

CTA ENFORCEMENT:
- 1 PRIMARY CTA: "Register Now"
- 1 OPTIONAL SECONDARY CTA: "View All Options"
- NO unrelated CTAs (no sponsors, no travel, no other)

SECTIONS TO REMOVE:
- Sponsorship
- Travel information
- Agenda details (belongs in Schedule email)
- Logistics
- Call for Proposals
- Testimonials
- Community links
- Membership

URGENCY RULES (CRITICAL):
✓ Factual deadline: "Ends [DATE] at [TIME]"
✓ Clear savings: "[SAVINGS_AMOUNT]"
✗ NO fake scarcity: "Only 5 spots" (if 5,000 capacity)
✗ NO aggressive language: "ACT NOW!!!"
✗ NO exaggeration: "prices increasing dramatically"

VALUE BEFORE DETAILS:
- Opening states what they get for the price
- Pricing comes after benefits are explained

TONE & VOICE:
✓ Direct, factual
✓ Focus on value (what's included)
✓ Authentic, no hype
✗ NO "amazing," "revolutionary," "last chance"
✗ NO aggressive urgency

INTERNAL VALIDATION:
□ Single objective: Drive registration
□ Every section supports registration
□ Opening: 30-50 words, 2 sentences
□ Information hierarchy: headline → intro → CTA → benefits → pricing → footer
□ One primary CTA: "Register Now"
□ Maximum 1 secondary CTA: "View Options"
□ Factual deadline, no fake urgency
□ Clear pricing comparison (early → standard)
□ Savings amount stated clearly
□ No agenda details, sponsor info, or logistics
□ No paragraph exceeds 3 sentences or 60 words
□ Bullets for benefits
□ Mobile-friendly
□ Scannable in <1 minute
□ Authentic tone
□ Word count: 180-250 words

IF ANY RULE FAILS: Revise before returning.

WORD COUNT TARGET: 180-250 words""",

        "cta_strategy": [
            "Primary: Register Now (registration page)",
            "Secondary: View All Options (pricing page)",
        ],
        "footer_note": "Early bird pricing ends [DEADLINE]. Standard pricing applies after that date.",
    },

    "Discount Offer / VIP Access": {
        "stage_name": "Discount Offer",
        "purpose": "VIP/alumni discount offer",
        "timing": "2-4 weeks before event",
        "tone": "Warm, welcoming, community-focused",
        "urgency_level": 3,
        "subject_pattern": "Welcome back: [DISCOUNT_AMOUNT] off [EVENT_NAME] for [SEGMENT]",
        "subject_examples": [
            "We'd love to see you again at [EVENT_NAME]",
            "Exclusive rate for [SEGMENT]: [DISCOUNT_AMOUNT] off",
        ],
        "preview_pattern": "Special rate just for you. Code inside.",

        "content_prompt": """Generate a VIP/Alumni discount email for open-source community.

PRIMARY OBJECTIVE: Offer exclusive rate to segment. EVERY section supports this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Segment: [SEGMENT] (alumni, past speakers, etc.)
- Standard Price: [REGULAR_PRICE]
- Discount Price: [DISCOUNT_PRICE]
- Savings: [DISCOUNT_AMOUNT]
- Code: [PROMO_CODE]

REQUIRED INFORMATION HIERARCHY:
1. HEADLINE: "Welcome Back to [EVENT_NAME]"

2. PERSONALIZED INTRODUCTION (40-50 words, 2 sentences)
   Greeting: "Hi {{ contact.firstname }},"
   Why special: "As a [SEGMENT], we saved this rate for you"
   RULE: Only greeting + why special. No event description.

3. DISCOUNT OFFER (40-50 words, highlighted)
   Format:
   Code: [PROMO_CODE]
   Your price: [DISCOUNT_PRICE]
   Standard: [REGULAR_PRICE]
   Save: [DISCOUNT_AMOUNT]

4. PRIMARY CTA: [ Register with Code [PROMO_CODE] ]

5. WHAT'S NEW (50-70 words, 2-3 sentences)
   Explain 1-2 changes since they last attended
   Keep it brief, relevant to their interests

6. SECONDARY CTA (optional): [ Learn More ]

7. FOOTER

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Discount offer in clear, scannable format
- Whitespace BETWEEN paragraphs

CTA ENFORCEMENT:
- 1 PRIMARY CTA: "Register with Code [CODE]"
- 1 OPTIONAL SECONDARY: "Learn More"
- NO unrelated CTAs (no sponsors, no community, no travel)

SECTIONS TO REMOVE:
- Sponsorship
- Travel information
- Agenda (belongs in Schedule email)
- Logistics
- Call for Proposals
- Registration details (only the discount matters)
- Full event description
- Membership pitch

PERSONALIZATION RULES:
✓ Use {{ contact.firstname }} in greeting (separate line)
✓ Reference segment explicitly: "As a [SEGMENT]"
✓ Optional: mention past involvement: "Your [contribution] was valuable"
✗ Don't use token for generic messaging

TONE & VOICE:
✓ Warm, genuinely welcoming
✓ Celebrate their past involvement
✓ Community-first (not transactional)
✓ Authentic, personal
✗ NO mass-mailed feeling
✗ NO desperate language
✗ NO false exclusivity

VALUE BEFORE DETAILS:
- Opening explains WHY they're special
- Discount offer comes early
- Then explain what's changed/improved

INTERNAL VALIDATION:
□ Single objective: Offer exclusive rate
□ Every section supports discount offer
□ Opening: personalized, 40-50 words, 2 sentences
□ Information hierarchy: greeting → why special → code → CTA → what's new → footer
□ One primary CTA: "Register with Code"
□ Maximum 1 secondary: "Learn More"
□ Personalization token used in greeting
□ Discount offer in clear, scannable format
□ No agenda, logistics, or sponsorship
□ No paragraph exceeds 3 sentences or 60 words
□ Mobile-friendly
□ Scannable in <1 minute
□ Genuine, warm tone
□ Word count: 180-240 words

IF ANY RULE FAILS: Revise before returning.

WORD COUNT TARGET: 180-240 words""",

        "cta_strategy": [
            "Primary: Register with Code [PROMO_CODE] (registration with pre-filled code)",
        ],
        "footer_note": "Questions? Reply to this email. We'd love to hear from you.",
    },

    "Final Countdown": {
        "stage_name": "Final Countdown",
        "purpose": "Confirm attendance and build anticipation",
        "timing": "1-2 weeks before event",
        "tone": "Warm, supportive, anticipatory",
        "urgency_level": 5,
        "subject_pattern": "[DAYS_LEFT] Days Until [EVENT_NAME]",
        "subject_examples": [
            "Getting ready for [EVENT_NAME]? Here's what to expect.",
            "See you in [DAYS_LEFT] days at [EVENT_NAME]",
        ],
        "preview_pattern": "Event guide and schedule inside.",

        "content_prompt": """Generate a Final Countdown email for open-source community.

PRIMARY OBJECTIVE: Confirm attendance & build anticipation. EVERY section supports this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Days Left: [DAYS_LEFT]
- Start Time: [START_TIME] [TIMEZONE]
- Venue: [VENUE_NAME]
- Highlights: [KEY_SESSIONS]

REQUIRED INFORMATION HIERARCHY:
1. HEADLINE: "[DAYS_LEFT] Days Until [EVENT_NAME]"

2. INTRODUCTION (30-50 words, 2 sentences)
   Excitement: "We're excited to see you..."
   Direction: "Here's what to expect..."
   RULE: Only these. No detailed schedule.

3. PRIMARY CTA: [ View Full Schedule ]

4. KEY LOGISTICS (80-100 words, structured format)
   Date & Time: [DATES], [START_TIME] [TIMEZONE]
   Location: [VENUE_NAME], [ADDRESS]
   What to Bring: (2-3 bullets)
   Getting There: (transit/parking info, brief)

5. WHAT TO EXPECT (80-100 words, 2-3 sentences)
   Brief overview of learning tracks/schedule
   Don't list detailed sessions

6. SECONDARY CTA (optional): [ Download Event App ]

7. FOOTER with support contact

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Use structured format for logistics
- Bullets for "What to Bring"
- Whitespace BETWEEN paragraphs

CTA ENFORCEMENT:
- 1 PRIMARY CTA: "View Full Schedule"
- 1 OPTIONAL SECONDARY: "Download Event App"
- NO unrelated CTAs

SECTIONS TO REMOVE (not for countdown):
- Sponsorship
- Call for Proposals
- Registration info
- Detailed agenda (they know this)
- Pricing/costs
- Travel packages
- Membership
- Testimonials

LOGISTICS RULES:
✓ Clear date and time (no ambiguity)
✓ Venue name + address
✓ Transportation info: transit, parking
✓ What to bring: realistic items
✗ NO overwhelming detail
✗ NO unnecessary complexity

VALUE BEFORE DETAILS:
- Opening builds anticipation
- Then provide practical details
- End on positive note

TONE & VOICE:
✓ Warm, supportive
✓ Anticipatory (not anxious)
✓ Helpful and practical
✓ Community-focused
✗ NO hard sell
✗ NO fake urgency
✗ NO "don't miss"

INTERNAL VALIDATION:
□ Single objective: Confirm attendance & anticipation
□ Every section supports this
□ Opening: 30-50 words, 2 sentences
□ Information hierarchy: headline → intro → CTA → logistics → what to expect → footer
□ One primary CTA: "View Schedule"
□ Maximum 1 secondary: "Download App"
□ Clear date, time, timezone, venue
□ Transit/parking info practical
□ No detailed agenda (they know it)
□ No sponsorship, pricing, or CTA info
□ No paragraph exceeds 3 sentences or 60 words
□ Bullets for "What to Bring"
□ Mobile-friendly
□ Scannable in <1 minute
□ Warm, supportive tone
□ Word count: 200-280 words

IF ANY RULE FAILS: Revise before returning.

WORD COUNT TARGET: 200-280 words""",

        "cta_strategy": [
            "Primary: View Full Schedule (agenda/schedule link)",
            "Secondary: Download Event App (mobile app link)",
        ],
        "footer_note": "Can't wait to see you there. Questions? Email [SUPPORT_EMAIL]",
    },

    "Post-Event": {
        "stage_name": "Post-Event",
        "purpose": "Thank attendees and extend engagement",
        "timing": "1-2 days after event",
        "tone": "Grateful, reflective, community-focused",
        "urgency_level": 1,
        "subject_pattern": "Thank You for [EVENT_NAME] – Recordings & Resources",
        "subject_examples": [
            "It was great seeing you at [EVENT_NAME]",
            "[EVENT_NAME] Recap: Recordings, slides, and next steps",
        ],
        "preview_pattern": "Recordings available. Survey takes 3 minutes.",

        "content_prompt": """Generate a Post-Event Thank You email for open-source community.

PRIMARY OBJECTIVE: Thank attendees & extend engagement. EVERY section supports this. NO other objectives.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Attendees: [ATTENDEE_COUNT]
- Recordings: [AVAILABLE_DATE]
- Survey: [LINK]
- Community: [SLACK/DISCORD_LINK]
- Next Event: [NEXT_EVENT_DATE] (if scheduled)

REQUIRED INFORMATION HIERARCHY:
1. HEADLINE: "Thank You for [EVENT_NAME]"

2. GRATITUDE (50-60 words, 2 sentences)
   Genuine thanks for attending
   Acknowledge their contribution/participation
   RULE: Only gratitude. No logistics, no next event.

3. WHAT'S AVAILABLE NOW (100-120 words, bullets)
   • Session recordings: [LINK] (available [DATE])
   • Slides and materials: [LINK]
   • Photos: [LINK]
   • Community: Join [COMMUNITY_COUNT]+ in Slack [LINK]

4. PRIMARY CTA: [ Watch Recordings ]

5. FEEDBACK REQUEST (30-40 words, 2 sentences)
   Light ask: "Your 3-minute survey helps us improve"
   Tone: "We'd love to hear from you"

6. SECONDARY CTA (optional): [ Share Your Feedback ]

7. NEXT EVENT TEASER (optional, 40-50 words)
   "Already planning [NEXT_EVENT]. Save the date."
   Tone: invitation, not pressure

8. FOOTER

PARAGRAPH ENFORCEMENT:
- MAXIMUM 2-3 sentences per paragraph
- MAXIMUM 60 words per paragraph
- Use bullets for "What's Available"
- Whitespace BETWEEN paragraphs

CTA ENFORCEMENT:
- 1 PRIMARY CTA: "Watch Recordings"
- 1 OPTIONAL SECONDARY: "Share Feedback"
- 0 others (no sponsors, no merchandise, no membership)

SECTIONS TO REMOVE (not for this stage):
- Sponsorship
- Travel recaps
- Detailed stats (keep it brief)
- Promotional content
- Call for Proposals
- Registration for next year (only teaser)
- Merchandise sales
- Community JOIN NOW (just link to existing)

SECTIONS ALLOWED ONLY IF GENUINELY VALUABLE:
- 1-2 attendee testimonials (genuine quotes, not marketing)
- Event highlights (brief statistics only)
- Call to action for community continuation

GRATITUDE RULES:
✓ Genuine, specific thanks
✓ Acknowledge attendee contribution
✓ Celebrate the community moment
✗ NO transactional tone
✗ NO "thanks for registering"
✗ NO corporate speak

VALUE BEFORE DETAILS:
- Thank them first
- Then show what's available
- Community continuation optional

TONE & VOICE:
✓ Grateful, sincere
✓ Reflective, celebratory
✓ Community-first
✓ Warm, personal
✗ NO sales pitch
✗ NO pressure for next event
✗ NO transactional

INTERNAL VALIDATION:
□ Single objective: Thank & extend engagement
□ Every section supports this
□ Opening: 50-60 words, 2 sentences, genuine thanks
□ Information hierarchy: headline → gratitude → resources → CTA → feedback → optional teaser → footer
□ One primary CTA: "Watch Recordings"
□ Maximum 1 secondary: "Share Feedback"
□ No sponsorship, sales, or promotional content
□ Resources clearly listed with links
□ Feedback request light, optional
□ Next event as teaser only (optional)
□ No paragraph exceeds 3 sentences or 60 words
□ Bullets for resources
□ Mobile-friendly
□ Scannable in <1 minute
□ Genuine, grateful tone
□ Word count: 180-240 words

IF ANY RULE FAILS: Revise before returning.

WORD COUNT TARGET: 180-240 words""",

        "cta_strategy": [
            "Primary: Watch Recordings (video library link)",
            "Secondary: Share Your Feedback (survey link)",
        ],
        "footer_note": "Recordings available [DATE]. Session slides ready now. Thanks for being part of our community!",
    },
}

# Mapping from stage_detector stages to AI_STAGE_TEMPLATES keys
FUNNEL_STAGE_TO_AI_TEMPLATE = {
    "Event Announcement": "CFP Launch",
    "CFP Launch": "CFP Launch",
    "Registration Launch": "CFP Launch",
    "Co-Located Events + CFP Reminder": "Schedule Announcement",
    "DEI & Travel Fund": "Schedule Announcement",
    "Schedule Announcement": "Schedule Announcement",
    "Main Registration Push": "Registration Push / Pricing Deadline",
    "Final Countdown": "Final Countdown",
    "Event Week": "Final Countdown",
    "Thank You + Survey": "Post-Event",
    "Content & Recordings Release": "Post-Event",
    "Next Event CFP Teaser": "CFP Launch",
    "Community Nurture": "Post-Event",
    "Unknown": "CFP Launch",
}


def map_funnel_stage_to_ai_template(funnel_stage_name: str) -> str:
    """Map a stage_detector.detect_stage() 'name' value to an AI_STAGE_TEMPLATES key."""
    return FUNNEL_STAGE_TO_AI_TEMPLATE.get(funnel_stage_name, "CFP Launch")


def get_ai_template(stage: str) -> dict:
    """Get AI template for a given stage."""
    return AI_STAGE_TEMPLATES.get(stage)


def get_all_ai_templates() -> dict:
    """Get all AI templates."""
    return AI_STAGE_TEMPLATES


def get_ai_stage_names() -> list:
    """Get list of available AI stages."""
    return list(AI_STAGE_TEMPLATES.keys())


def fill_template_placeholders(template_text: str, event_data: dict) -> str:
    """Fill template placeholders with event data."""
    replacements = {
        "[EVENT_NAME]": event_data.get("event_name", "Event"),
        "[LOCATION]": event_data.get("location", "Location"),
        "[DATES]": event_data.get("dates", "TBD"),
        "[LOCATION_SHORT]": event_data.get("location", "").split(",")[0],
        "[MONTH]": event_data.get("month", ""),
        "[YEAR]": event_data.get("year", ""),
        "[EARLY_PRICE]": event_data.get("early_price", "$X"),
        "[REGULAR_PRICE]": event_data.get("regular_price", "$Y"),
        "[SAVINGS_AMOUNT]": event_data.get("savings_amount", "$Z"),
        "[DISCOUNT_PRICE]": event_data.get("discount_price", "$X"),
        "[DISCOUNT_AMOUNT]": event_data.get("discount_amount", "$Z"),
        "[PROMO_CODE]": event_data.get("promo_code", "PROMO"),
        "[DEADLINE]": event_data.get("deadline_date", "TBD"),
        "[DEADLINE_DATE]": event_data.get("deadline_date", "TBD"),
        "[DAYS_LEFT]": str(event_data.get("days_left", "X")),
        "[HOURS_LEFT]": str(event_data.get("hours_left", "X")),
        "[TIME_LEFT]": event_data.get("time_left", "TBD"),
        "[ATTENDEE_COUNT]": event_data.get("attendee_count", "1,000+"),
        "[SESSION_COUNT]": event_data.get("session_count", "100+"),
        "[SPEAKER_COUNT]": event_data.get("speaker_count", "50+"),
        "[TOPICS]": ", ".join(event_data.get("topics", [])),
        "[TOPIC_1]": event_data.get("topics", ["open source"])[0] if event_data.get("topics") else "open source",
        "[TOPIC_2]": event_data.get("topics", ["", "community"])[1] if len(event_data.get("topics", [])) > 1 else "community",
        "[TOPIC_3]": event_data.get("topics", ["", "", "innovation"])[2] if len(event_data.get("topics", [])) > 2 else "innovation",
        "[SEGMENT]": event_data.get("recipient_segment", "valued member"),
        "[FIRST_NAME]": event_data.get("first_name", ""),
        "[PAST_EVENT]": event_data.get("past_event", "past event"),
        "[COMPANIES]": event_data.get("featured_companies", "leading companies"),
        "[DATE]": event_data.get("date", event_data.get("dates", "TBD")),
        "[DEADLINE_TIME]": event_data.get("deadline_time", "11:59 PM"),
        "[START_TIME]": event_data.get("start_time", "9:00 AM"),
        "[END_TIME]": event_data.get("end_time", "5:00 PM"),
        "[TIMEZONE]": event_data.get("timezone", "PT"),
        "[VENUE_NAME]": event_data.get("venue_name", "Venue"),
        "[ADDRESS]": event_data.get("address", "Address"),
        "[PARKING_INFO]": event_data.get("parking_info", "Info available on event site"),
        "[TRANSIT_INFO]": event_data.get("transit_info", "Info available on event site"),
        "[SUPPORT_EMAIL]": event_data.get("support_email", "support@event.com"),
        "[SLACK/DISCORD_LINK]": event_data.get("community_link", "#"),
        "[COMMUNITY_COUNT]": event_data.get("community_count", "5,000+"),
        "[NEXT_EVENT_DATE]": event_data.get("next_event_date", "TBD"),
        "[AVAILABLE_DATE]": event_data.get("recordings_available_date", "[DATE]"),
        "[TRACK_COUNT]": str(event_data.get("track_count", "5")),
        "[TRACK_NAME]": event_data.get("track_name", "Track"),
        "[SESSION_HIGHLIGHT]": event_data.get("session_highlight", "sessions"),
        "[KEY_SESSIONS]": event_data.get("key_sessions", ""),
    }

    result = template_text
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, str(value))

    return result


if __name__ == "__main__":
    print("Available AI Stages:")
    for stage in get_ai_stage_names():
        print(f"  - {stage}")
