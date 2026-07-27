"""
REAL Event Lifecycle Email Templates — Based on actual successful campaigns

These templates follow the ACTUAL structure found in leading tech event campaigns:
- Dreamforce, KubeCon/CNCF, Google Cloud Next, AWS re:Invent, Stripe, Eventbrite

Each stage template includes:
  - REAL email anatomy (sections, CTA placement, word count)
  - Proven messaging patterns
  - Mobile-first structure requirements
  - Tone progression across the lifecycle
  - Visual element specifications

NOT theoretical best practices — actual patterns from successful campaigns.
"""

from datetime import datetime
import json

# ── REAL Event Email Templates (Based on industry-leading campaigns) ──

AI_STAGE_TEMPLATES = {
    "CFP Launch": {
        "stage_name": "CFP Launch",
        "purpose": "Announce Call for Proposals and drive speaker submissions",
        "timing": "3-4 months before event",
        "tone": "Energetic, inclusive, community-focused",
        "urgency_level": 7,
        "subject_pattern": "🎤 [MAIN_ACTION] at [EVENT_NAME] – Deadline [DATE]",
        "subject_examples": [
            "🎤 Call for Proposals: Share Your Story at [EVENT_NAME]",
            "🎤 Submit to Speak at [EVENT_NAME] – Deadline [DATE]",
        ],
        "preview_pattern": "Share your expertise. First-time speakers welcome.",

        # REAL STRUCTURE from research:
        "content_prompt": """Generate a Call for Proposals email following REAL industry patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- CFP Deadline: [DEADLINE]
- Topics: [TOPICS]

REAL EMAIL ANATOMY (follow this structure exactly):

1. OPENING HOOK (50-70 words, 1 sentence hook + brief context)
   - Lead with: "Share your expertise" or "Speak at [EVENT_NAME]"
   - Who: "We're looking for speakers like you"
   - When: "[DEADLINE_DATE] deadline"
   - Tone: Warm, inclusive (no gatekeeping)
   - Example: "We're building the speaker lineup for [EVENT_NAME], and we want to hear from YOU. Whether you're a first-time speaker or seasoned veteran, we're looking for diverse voices and perspectives on [TOPICS]. Deadline: [DATE]."

2. WHAT WE'RE LOOKING FOR (80-100 words)
   - Talk types: "Breakout talks (30-45 min), lightning talks (10 min), panels, workshops"
   - Session count: "[SESSION_COUNT]+ talks from speakers across the industry"
   - Diversity note: "We actively seek underrepresented voices" (if true)
   - Benefit callout: "Speak to [ATTENDEE_COUNT]+ industry professionals"
   - First-timer support: "Mentorship available for first-time speakers"

3. TOPIC EXAMPLES (60-80 words, use bullet list)
   - List 4-5 specific topics from [TOPICS]
   - Include 1-2 concrete session examples (make it real)
   - Example topics: "Machine Learning in Production", "Open Source Sustainability", "Cloud Cost Optimization"
   - Tone: "We're interested in..." not "We require..."

4. SOCIAL PROOF (30-40 words)
   - Past speaker prestige: "Previous speakers included leaders from [COMPANIES]"
   - OR: "1,000+ developers and architects attended last year"
   - Keep it short and credible

5. CLOSING (30-40 words)
   - Reiterate deadline: "Deadline: [DEADLINE] at [TIME]"
   - Encourage: "We can't wait to hear your ideas"
   - Link to submit: "Submit your proposal at [LINK]"

TONE RULES (CRITICAL):
✓ Inclusive, welcoming (invite first-timers)
✓ Community-focused (peer learning, not prestige)
✓ Direct, clear (what we need, how to apply)
✓ NO corporate speak, NO "exclusive opportunity"
✓ First-time speaker support = key differentiator

CTA PLACEMENT:
- 1 primary: "Submit Your Proposal" (clear, specific link)
- 0 secondary CTAs (keep focus on submission)

WORD COUNT TARGET: 200-280 words (short and punchy)

MOBILE REQUIREMENTS:
- Single column
- Button: 44×44px minimum
- Topic bullets in <ul><li> format
- Font: 16px minimum""",

        "cta_strategy": [
            "Primary: Submit Your Proposal (link to CFP form)",
            "No secondary CTA — maintain singular focus on submission",
        ],
        "footer_note": "First-time speakers welcome. We offer mentorship and support.",
    },

    "Schedule Announcement": {
        "stage_name": "Schedule Announcement",
        "purpose": "Share speaker lineup and schedule; drive registrations",
        "timing": "4-8 weeks before event",
        "tone": "Professional + warm, educational",
        "urgency_level": 5,
        "subject_pattern": "📣 [EVENT_NAME] Schedule is Live – [X] Sessions, [Y] Speakers",
        "subject_examples": [
            "📣 See the [EVENT_NAME] Lineup – 100+ Sessions, 50+ Speakers",
            "The agenda is here: [X] tracks at [EVENT_NAME]",
        ],
        "preview_pattern": "See all [SESSION_COUNT]+ sessions. Build your agenda.",

        "content_prompt": """Generate a Schedule Announcement email following REAL industry patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Total Sessions: [SESSION_COUNT]
- Total Speakers: [SPEAKER_COUNT]
- Keynote speakers: [KEYNOTE_NAMES]
- Tracks: [TRACK_NAMES]
- Topics: [TOPICS]

REAL EMAIL ANATOMY (Dreamforce, Google Cloud Next pattern):

1. HERO IMAGE (300-400px height)
   - Required: Event graphics with date/location overlay
   - Font on hero: Date (18-20px), location (14px)
   - Optional: Animated GIF of conference highlights
   - Mobile: Responsive, maintains readability

2. OPENING HOOK (40-60 words, 2-3 sentences)
   - Lead statement: "The [EVENT_NAME] schedule is live!"
   - Transition: "Here's what you need to know"
   - Tone: Warm greeting, excitement without hype
   - Example: "Hi {{ contact.firstname }}, We're excited to share the full agenda for [EVENT_NAME]. With [SESSION_COUNT]+ sessions, [SPEAKER_COUNT]+ speakers, and [TRACK_COUNT] specialized tracks, there's something for everyone."

3. PRIMARY CTA (Button after opening)
   - Button text: "Build Your Personalized Agenda"
   - Purpose: Drive traffic to event site's schedule builder
   - Placement: After opening, before stats
   - Style: 44×44px, brand primary color

4. KEY STATISTICS (60-80 words)
   - Session count: "[SESSION_COUNT]+ sessions"
   - Speaker count: "[SPEAKER_COUNT]+ speakers from [COMPANIES/REGIONS]"
   - Track breakdown: "6 specialized tracks covering [TOPICS]"
   - Tone: Data-driven, highlight breadth

5. FEATURED SPEAKERS (100-150 words)
   - Structure: 3-5 keynote speaker names with titles
   - Format: "Name, Title @ Company | Keynote: [TOPIC]"
   - No photos in this section (keep word count down)
   - Example: "Opening Keynote: Jane Doe, VP Engineering at Google | 'The Future of Cloud Architecture'"
   - Include 1-2 speaker quotes if available (15-20 words max)

6. AGENDA HIGHLIGHTS BY TRACK (80-100 words)
   - List format: "Track name: X sessions | Topics: [TOPICS]"
   - Feature 2-3 specific session titles per track
   - Example:
     "Cloud Architecture: 12 sessions | Topics: Kubernetes, Infrastructure as Code, Cost Optimization
     AI/ML: 15 sessions | Topics: LLMs, Model Optimization, Production Pipelines"
   - End with: "Plus workshops, panels, and hands-on labs"

7. SOCIAL PROOF (30-40 words)
   - "Join [ATTENDEE_COUNT]+ engineers and architects"
   - OR: "Last year, attendees rated us 4.8/5 stars"
   - Small, factual, credible

8. SECONDARY CTA (Optional, can include)
   - Button text: "View Full Schedule" (or "Register Now")
   - Placement: After agenda highlights
   - Secondary because agenda builder is the primary goal

TONE RULES:
✓ Professional but approachable
✓ Educational focus (what you'll LEARN)
✓ NO fluff adjectives ("amazing", "incredible")
✓ Specific sessions, not generic topics
✓ Community angle: "Join X professionals"

WORD COUNT TARGET: 200-280 words (excludes hero/buttons)

VISUAL ELEMENTS:
- 1 hero image (600px × 300-400px)
- 0 speaker headshots in this email (keep clean)
- Optional: Track icons (if simple, doesn't clutter)

MOBILE REQUIREMENTS:
- Single column, responsive hero
- Buttons stack vertically
- Track breakdown readable at 16px font
- No wide tables""",

        "cta_strategy": [
            "Primary: Build Your Personalized Agenda (agenda builder link)",
            "Secondary: Register Now (registration link)",
        ],
        "footer_note": "Early-bird pricing available. Seats filling up.",
    },

    "Registration Push / Pricing Deadline": {
        "stage_name": "Registration Push",
        "purpose": "Drive registrations before deadline with urgency and value",
        "timing": "2-4 weeks before event",
        "tone": "Urgent + enthusiastic, benefit-focused",
        "urgency_level": 8,
        "subject_pattern": "⏰ [DAYS_LEFT] Days: Save [SAVINGS_AMOUNT] on [EVENT_NAME]",
        "subject_examples": [
            "⏰ Early-bird pricing ends [DATE] – Save [SAVINGS_AMOUNT]",
            "🎟️ Last chance at early-bird rates for [EVENT_NAME]",
        ],
        "preview_pattern": "Early-bird closes [DATE]. Secure your spot now.",

        "content_prompt": """Generate a Registration/Pricing Deadline email following REAL industry patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Early-Bird Price: [EARLY_PRICE]
- Regular Price: [REGULAR_PRICE]
- Savings: [SAVINGS_AMOUNT]
- Deadline: [DEADLINE_DATE] at [DEADLINE_TIME]
- Days Left: [DAYS_LEFT]
- Pass Types: [TICKET_TYPES]

REAL EMAIL ANATOMY (Eventbrite, AWS pattern):

1. HERO VISUAL (250-350px height)
   - Option A: Savings graphic showing "[SAVINGS_AMOUNT] savings" prominently
   - Option B: Countdown timer visual: "[DAYS_LEFT] Days | [HOURS_LEFT] Hours Remaining"
   - Option C: Price comparison: "[EARLY_PRICE] → [REGULAR_PRICE]"
   - Goal: Make savings VISIBLE and OBVIOUS

2. OPENING: URGENCY + VALUE (50-70 words, 2-3 short sentences)
   - Lead: "Save [SAVINGS_AMOUNT] with early-bird pricing"
   - Deadline: "Deadline: [DEADLINE_DATE] at [TIME]"
   - Tone: Factual, direct, NOT panicky
   - Example: "Early-bird pricing for [EVENT_NAME] ends [DATE] at [TIME]. After that, standard pricing ([REGULAR_PRICE]) applies. Save [SAVINGS_AMOUNT] by registering now."

3. PRIMARY CTA (Immediately after opening)
   - Button text: "Claim Early-Bird Tickets – Save [SAVINGS_AMOUNT]"
   - Color: Contrasting, urgent (can use red/orange)
   - Size: 44×44px minimum
   - Placement: Above-the-fold (first 150px)
   - Support text: "([EARLY_PRICE] expires [DATE])"

4. VALUE SECTION (60-80 words)
   - What's included: "Full access to [SESSION_COUNT]+ sessions, workshops, networking events"
   - Experience value: "Network with [ATTENDEE_COUNT]+ professionals from [REGIONS]"
   - Pass options: "Choose Full Pass, Day Pass, or Virtual Access"
   - NO long paragraphs — use bullet format

5. SOCIAL PROOF (30-40 words)
   - Attendee count: "[ATTENDEE_COUNT]+ already registered"
   - Scarcity (if true): "Only [SPOTS] spots remaining at early-bird rate"
   - Testimonial (optional): "Previous attendees rated it 4.8/5 stars"

6. SECONDARY CTA (Optional)
   - Button text: "View All Pass Options" or "Add Team Members"
   - Purpose: Catch readers who need more info

7. DEADLINE CALLOUT (Emphasized, 20-30 words)
   - Restate: "Prices increase to [REGULAR_PRICE] on [DATE]"
   - Make it clear and factual

TONE RULES:
✓ Lead with BENEFIT (savings), then deadline
✓ Urgent language: "Final X days", "Prices increase", "Spots filling"
✓ Focus on VALUE: what you're getting
✓ NO aggressive/fake scarcity ("Only 5 spots left" if capacity is 10,000)
✓ NO fluff, NO hype

WORD COUNT TARGET: 150-220 words

VISUAL ELEMENTS:
- 1 hero: savings graphic OR countdown timer (required)
- Color scheme: Warm tones (red/orange) for urgency acceptable

MOBILE REQUIREMENTS:
- Buttons 44×44px minimum
- Savings amount prominent on small screens
- Countdown timer responsive
- Single column
- Large font: 18-20px for deadline""",

        "cta_strategy": [
            "Primary: Claim Early-Bird Tickets (register link)",
            "Secondary: View All Pass Options (pass details)",
            "Tertiary: Add Team Members (group discount)",
        ],
        "footer_note": "Early-bird pricing ends [DATE] at [TIME]. Prices increase immediately after.",
    },

    "Discount Offer / VIP Access": {
        "stage_name": "Discount Offer",
        "purpose": "Exclusive offer for VIP/alumni segment",
        "timing": "2-4 weeks before event",
        "tone": "Warm, exclusive, personally welcoming",
        "urgency_level": 4,
        "subject_pattern": "🎁 Exclusive Offer: [SEGMENT] Save [DISCOUNT_AMOUNT]",
        "subject_examples": [
            "🎁 Welcome back: Alumni get [DISCOUNT_AMOUNT] off [EVENT_NAME]",
            "An exclusive offer for you, [FirstName]",
        ],
        "preview_pattern": "Exclusive [SEGMENT] rate inside. Save [DISCOUNT_AMOUNT].",

        "content_prompt": """Generate a personalized VIP/Alumni discount email following REAL patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Segment: [SEGMENT] (e.g., "alumni 2025", "past speakers", "community leaders")
- Standard Price: [REGULAR_PRICE]
- Discount Price: [DISCOUNT_PRICE]
- Savings: [DISCOUNT_AMOUNT]
- Promo Code: [PROMO_CODE]

REAL EMAIL ANATOMY (Dreamforce alumni pattern):

1. PERSONALIZED GREETING (First thing, 2 sentences)
   - "Hi {{ contact.firstname }},"
   - Lead: "We'd love to see you back at [EVENT_NAME]!"
   - Acknowledge history: "As a [SEGMENT], we saved this rate just for you"
   - Tone: Warm, genuine welcome (NOT transactional)

2. WHY THEY'RE SPECIAL (40-50 words)
   - Explain segment: "You're part of our [SEGMENT] community, and we value your involvement"
   - Reference past: "Your [CONTRIBUTION/ATTENDANCE] at [PAST_EVENT] was meaningful"
   - Emotional hook: "We'd love your perspective again"

3. THE OFFER (40-50 words, PROMINENT)
   - Savings highlighted: "Save [DISCOUNT_AMOUNT] with code [PROMO_CODE]"
   - Price comparison: "[DISCOUNT_PRICE] instead of [REGULAR_PRICE]"
   - Timeline: "This offer expires [DATE]"
   - Code placement: LARGE, scannable (consider visual badge)

4. PRIMARY CTA (After offer details)
   - Button text: "Claim Your Discount – Code [PROMO_CODE]"
   - OR: "Register Now at [DISCOUNT_PRICE]"
   - Link should ideally pre-fill promo code if possible
   - Size: 44×44px

5. WHAT'S NEW (50-70 words)
   - Highlight changes since they last attended
   - "This year we're featuring [NEW_CONTENT/TOPICS]"
   - "New tracks we think you'll love: [EXAMPLES]"
   - Explain why to return

6. COMMUNITY ASPECT (30-40 words)
   - "Reconnect with [SEGMENT] peers"
   - "Meet new members of our community"
   - Emphasize: reunion, networking, belonging

7. SECONDARY CTA (Optional)
   - Button text: "Learn What's New" or "View Schedule"
   - For hesitant readers wanting more info

TONE RULES:
✓ Personal (celebrate THEIR contribution)
✓ Warm welcome (we missed you)
✓ Exclusive (genuine, not fake)
✓ Community-focused (who you'll reconnect with)
✗ NO pushy language
✗ NO mass-mailed feeling
✗ NO desperation ("We need you")

WORD COUNT TARGET: 180-240 words

MOBILE REQUIREMENTS:
- Promo code PROMINENT and SCANNABLE
- Large font for discount amount
- Easy copy-button for code (if JavaScript available)
- Single column

PERSONALIZATION REQUIRED:
- {{ contact.firstname }} greeting
- Segment-specific content (not generic)
- Reference to past involvement if known""",

        "cta_strategy": [
            "Primary: Claim Your [PROMO_CODE] Discount (register with code)",
            "Secondary: Learn What's New (event highlights)",
        ],
        "footer_note": "Use code [PROMO_CODE] at checkout. Valid through [DATE]. Questions? Reply to this email.",
    },

    "Final Countdown": {
        "stage_name": "Final Countdown",
        "purpose": "Last push before event; confirm and excite attendees",
        "timing": "1-2 weeks before event",
        "tone": "Energetic, community-focused, anticipatory",
        "urgency_level": 6,
        "subject_pattern": "[DAYS_LEFT] Days Until [EVENT_NAME] – Get Ready!",
        "subject_examples": [
            "[DAYS_LEFT] Days: [EVENT_NAME] is almost here!",
            "You're registered! Here's what to expect →",
        ],
        "preview_pattern": "Event week coming. Build your agenda + logistics inside.",

        "content_prompt": """Generate a Final Countdown email following REAL industry patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Days Until: [DAYS_LEFT]
- Venue: [VENUE_NAME]
- Start Time: [START_TIME] [TIMEZONE]
- Key sessions/highlights: [KEY_SESSIONS]
- Networking events: [SOCIAL_EVENTS]
- Attendee count: [ATTENDEE_COUNT]

REAL EMAIL ANATOMY (KubeCon, Google Cloud pattern):

1. OPENING HOOK (30-40 words, 1-2 sentences)
   - Lead: "[DAYS_LEFT] days until [EVENT_NAME]!"
   - Tone: Excitement, anticipation (NOT pressure)
   - Example: "We're [DAYS_LEFT] days away from [EVENT_NAME]! Get ready to learn, network, and connect with [ATTENDEE_COUNT]+ peers."

2. EXPERIENCE NARRATIVE (60-80 words)
   - Paint a picture: "Imagine [SCENARIO]"
   - Featured speakers: "[SPEAKER_NAMES] opening with keynotes on [TOPICS]"
   - Networking: "Coffee chats, dinner events, and community connections"
   - Community angle: "[ATTENDEE_COUNT]+ engineers and architects from [REGIONS]"
   - Tone: Descriptive, engaging (what awaits them)

3. SCHEDULE BREAKDOWN (100-120 words)
   - Day-by-day highlights: "Monday: Keynotes + Workshops | Tuesday: Deep Dives | Wednesday: Closing Sessions"
   - Track overview: "6 specialized tracks covering [TOPICS]"
   - Featured sessions: List 3-5 specific session titles (make it real)
   - Networking: "Evening events, breakfast meetups, lounge networking"

4. PRIMARY CTA
   - Button text: "Build Your Final Agenda" or "Add to Calendar"
   - Purpose: Help them prepare
   - Link to event app/schedule builder
   - Size: 44×44px

5. LOGISTICS SECTION (60-80 words, CRITICAL)
   - Event date: "[DATE]"
   - Time: "[START_TIME] - [END_TIME] [TIMEZONE]"
   - Location: "[VENUE_NAME], [ADDRESS]"
   - For in-person: Parking info, transit, weather, what to bring
   - For virtual: Zoom link (or "you'll receive it soon"), tech requirements
   - For hybrid: Both details + "Choose your mode"

6. SOCIAL PROOF (30-40 words)
   - Attendee background: "From [COUNTRIES/COMPANIES]"
   - Past feedback: "4.8/5 star rating from [LAST_YEAR]"
   - Diversity: "Diverse voices across [SPECTRUM]"

7. SECONDARY CTA
   - "Download the Event App" or "View Venue Maps"
   - Reduce friction for day-of experience

TONE RULES:
✓ Energetic but grounded
✓ Focus on EXPERIENCE (learning, connections)
✓ Community-focused (peer learning)
✓ Anticipation, not panic
✗ NO aggressive FOMO language
✗ NO "don't miss out" fatigue
✗ NO logistics without experience narrative

WORD COUNT TARGET: 220-300 words

VISUAL ELEMENTS:
- Optional hero image: Event highlights or venue
- NO countdown timer here (keep focus on experience)

MOBILE REQUIREMENTS:
- Single column
- Logistics block readable and scannable
- Button stack vertically
- Large font for date/time (18px minimum)""",

        "cta_strategy": [
            "Primary: Build Your Final Agenda (or Add to Calendar)",
            "Secondary: Download Event App (or View Venue Maps)",
        ],
        "footer_note": "Can't wait to see you in [LOCATION]! Questions? Email: [SUPPORT_EMAIL]",
    },

    "Post-Event": {
        "stage_name": "Post-Event",
        "purpose": "Thank attendees, share recordings, feedback, community",
        "timing": "1-2 days after event",
        "tone": "Warm, grateful, reflective, forward-looking",
        "urgency_level": 2,
        "subject_pattern": "Thank You for [EVENT_NAME] – Recordings + What's Next",
        "subject_examples": [
            "Thank you for [EVENT_NAME] – Here's what you can access now",
            "[EVENT_NAME] Recap: Download slides, watch recordings, join us again",
        ],
        "preview_pattern": "Recordings available. Survey takes 3 min. Thank you.",

        "content_prompt": """Generate a warm post-event thank-you email following REAL patterns.

EVENT DETAILS:
- Name: [EVENT_NAME]
- Location: [LOCATION]
- Date: [DATES]
- Total attendees: [ATTENDEE_COUNT]
- Recordings available: [DATE]
- Feedback survey: [LINK]
- Community channel (Slack/Discord): [LINK]
- Next event teaser: [NEXT_EVENT_NAME] / [NEXT_DATE] (if scheduled)

REAL EMAIL ANATOMY (All major conferences follow this):

1. HEARTFELT OPENING (40-50 words, 2 sentences)
   - Gratitude: "Thank you for joining us in [LOCATION]"
   - Acknowledgment: "Your energy, questions, and connections made it special"
   - Tone: Genuine, NOT corporate/formal
   - Example: "We're still buzzing from [EVENT_NAME]! Thank you for being part of it. Your presence made the experience richer."

2. HIGHLIGHT KEY MOMENTS (60-80 words)
   - Statistics: "[ATTENDEE_COUNT]+ attendees from X countries"
   - Standout sessions: "Conversations about [TOPIC] drew standing rooms"
   - Attendee sentiment: "The energy in [LOCATION] was incredible"
   - Include 1 short testimonial: "[QUOTE]" - [PERSON], [ROLE] (15-25 words max)
   - Tone: Celebratory, factual

3. WHAT'S AVAILABLE NOW (100-120 words, MAIN VALUE)
   - Recordings: "Session videos available [DATE] at [LINK]"
   - Slides/materials: "Speaker decks, PDFs, and resources ready at [LINK]"
   - Photos: "Event photos available in gallery: [LINK]"
   - Community: "Join [ATTENDEE_COUNT]+ members in our Slack community: [LINK]"
   - Networking: "[CONTINUATION_FORMAT]" (e.g., "Monthly virtual meetups start [DATE]")
   - Use clear structure (bullets or short paragraphs)

4. PRIMARY CTA
   - Button text: "Watch Session Recordings" (or "Access Materials")
   - Purpose: Drive traffic to content library
   - Size: 44×44px

5. FEEDBACK REQUEST (30-40 words)
   - Light ask: "Your 3-minute survey helps us improve"
   - Tone: "We'd love to hear from you"
   - Link to survey
   - Optional second CTA: "Share Your Feedback"

6. NEXT EVENT TEASER (40-50 words, OPTIONAL)
   - "Save the date: [NEXT_EVENT] is scheduled for [DATE]"
   - OR "We're already planning [NEXT_FLAVOR]…more to come"
   - Tone: Invitation, not pressure
   - Mention: Early-bird date if available

7. COMMUNITY ONGOING (30-40 words)
   - "The conversation continues in our community"
   - Slack, Discord, forum, etc.
   - "Monthly calls, resource sharing, peer support"

TONE RULES:
✓ Genuine gratitude (not pro forma)
✓ Celebrate ATTENDEE contribution
✓ Community-first (keep connections going)
✓ Reflective, warm
✓ Forward-looking (but not pushy)
✗ NO sales pitch
✗ NO desperation for next event
✗ NO transactional feeling

WORD COUNT TARGET: 180-240 words

VISUAL ELEMENTS:
- Optional hero: Event photo collage or highlight reel
- NO countdown timers
- Optional: Attendee testimonial quotes (visual callout)

MOBILE REQUIREMENTS:
- Single column
- Links to recordings/resources clickable
- Survey link obvious
- Community link obvious""",

        "cta_strategy": [
            "Primary: Watch Session Recordings (video library link)",
            "Secondary: Share Your Feedback (survey link)",
            "Tertiary: Join Our Community (Slack/Discord/forum)",
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
