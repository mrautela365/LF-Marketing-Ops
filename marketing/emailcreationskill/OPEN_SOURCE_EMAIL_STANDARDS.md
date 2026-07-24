# Open Source Event Email Standards (2025–2026)
## Complete Team Documentation & Implementation Guide

---

## Table of Contents

1. [Core Principles](#core-principles)
2. [Writing Guidelines](#writing-guidelines)
3. [Email Architecture by Stage](#email-architecture-by-stage)
4. [CTA Strategy](#cta-strategy)
5. [Personalization Rules](#personalization-rules)
6. [Visual Design Standards](#visual-design-standards)
7. [Accessibility Requirements](#accessibility-requirements)
8. [Mobile-First Design](#mobile-first-design)
9. [AI Generation Guidelines](#ai-generation-guidelines)
10. [QA Checklist](#qa-checklist-before-publishing)

---

## Core Principles

### #1: One Goal Per Email

**Rule**: Every email should have exactly one primary objective.

**Examples of ONE goal per email:**
- ✓ Announce the event
- ✓ Drive Early Bird registration
- ✓ Introduce speakers
- ✓ Promote agenda
- ✓ Prepare attendees
- ✓ Collect feedback

**Rule**: Never combine multiple unrelated objectives.

**✗ Wrong**: "Announce event + Drive registration + Promote sponsors" in one email  
**✓ Right**: One email for each objective across the campaign lifecycle

---

### #2: 30–60 Second Reading Experience

The email should be completely understandable within 30–60 seconds.

Users should be able to **scan** the email instead of reading every sentence.

**Content should flow:**
```
Why this matters
↓
Proof (speakers, agenda, social proof)
↓
Action (CTA)
```

---

### #3: Community Manager Voice (Not Marketer)

Write like an experienced community manager who cares about the community.

**Tone should be:**
- Professional
- Friendly
- Technical
- Community-focused
- Educational
- Human

**Avoid:**
- Marketing buzzwords ("amazing," "revolutionary," "game-changing")
- Clickbait
- Excessive excitement
- Fake urgency
- "Don't miss this amazing opportunity!"
- "Act now!!"
- Aggressive language (ALL CAPS, multiple exclamation marks)

**Instead use:**
- Authentic language
- Factual claims
- Community-focused benefits
- Clear deadlines (not "CLOSES SOON")

---

## Writing Guidelines

### Paragraph Rules

**Maximum paragraph length:** 2–3 sentences

**Recommended word count per paragraph:** 25–60 words

**Never generate:** Large walls of text

**After every paragraph:** Leave whitespace (1 blank line)

**Example:**

```
✓ Good:
We're excited to share the speaker lineup for KubeCon Japan. 
With 100+ speakers and 200+ sessions, there's something for everyone.

✗ Bad:
We're excited to share the speaker lineup for KubeCon Japan because we've assembled 
an amazing group of speakers from around the world who will discuss a wide range of 
important topics in the Kubernetes and cloud native ecosystem. This year's event 
features 100+ speakers and 200+ sessions across 5 specialized tracks, ensuring 
attendees can find talks that match their interests and expertise level.
```

---

### Heading Rules

**Rule**: Every major section should have a heading.

**Examples:**
- Why Attend
- Featured Speakers
- Agenda Highlights
- Workshops
- Networking
- Early Bird Pricing
- Sponsors
- What's Included

**Never produce:** One continuous block of content without section headings

---

### Bullet List Rules

**Use bullets whenever possible.**

**Maximum:** 3–5 bullets per list

**Bullets should be short.** No paragraph-length bullets.

**Example:**

```
✓ Good:
• OpenTelemetry adoption
• Kubernetes observability
• eBPF for network monitoring
• Continuous profiling

✗ Bad:
• Learn about OpenTelemetry adoption and how it's transforming observability 
  practices across the cloud native ecosystem with real examples from production deployments
```

---

## Email Architecture by Stage

### Stage 1: Event Announcement

**Objective:** Create awareness

**Timing:** 8–12 weeks before event

**Word Count Target:** 150–220 words

**CTA Strategy:** 1 primary CTA

**Structure:**
1. Logo/Header
2. Hero Image (required)
3. Headline
4. Introduction (1–2 sentences)
5. Why Attend (2–3 bullets)
6. Key Details (date, location, registration link)
7. **PRIMARY CTA: "Learn More" or "Register"**
8. Featured Speakers (optional)
9. Sponsor logos (optional, footer)
10. Footer

**Sample Subject Line:**
- "📅 KubeCon Japan 2026: Community-Driven Cloud Native Conference"
- "Mark your calendar: KubeCon + CloudNativeCon Japan"

**Tone:** Professional, warm, welcoming

---

### Stage 2: Call for Proposals (CFP)

**Objective:** Recruit speakers

**Timing:** 3–4 months before event

**Word Count Target:** 200–280 words

**CTA Strategy:** 1 primary CTA (Submit Proposal)

**Structure:**
1. Logo/Header
2. Hero Image (optional)
3. Headline
4. Introduction (50 words)
5. Why Speak (60 words)
6. What We're Looking For (80 words, bullet list)
7. **PRIMARY CTA: "Submit Your Proposal"**
8. Important Dates
9. Footer (with support contact)

**Key Message:** First-time speakers explicitly welcome, mentorship available

**Tone:** Welcoming, inclusive, community-focused

---

### Stage 3: Early Bird Registration

**Objective:** Generate registrations

**Timing:** 2–4 weeks after announcement

**Word Count Target:** 180–250 words

**CTA Strategy:** 1 primary, 1 secondary

**Structure:**
1. Logo/Header
2. Hero Image (required: countdown or pricing visual)
3. Headline
4. Urgency Statement (factual deadline)
5. **PRIMARY CTA: "Register Now"**
6. What's Included (3–5 bullets)
7. Pricing Comparison
8. Featured Speakers/Topics
9. **SECONDARY CTA: "View All Options"**
10. Footer

**Tone:** Direct, value-focused, factual (no hype)

**Critical Rule:** No fake urgency. Use real deadlines only.

---

### Stage 4: Speaker/Agenda Spotlight

**Objective:** Increase credibility

**Timing:** 10–14 days before event

**Word Count Target:** 180–220 words

**CTA Strategy:** 1 primary, 1 optional secondary

**Structure:**
1. Logo/Header
2. Hero Image (optional)
3. Headline
4. Introduction (40 words)
5. **PRIMARY CTA: "View Full Schedule"**
6. Featured Speakers (3–5 speaker cards with headshots, titles, session names)
7. Learning Tracks (organized by topic)
8. **SECONDARY CTA (optional): "Register Now"**
9. Footer

**Speaker Card Format:**
- Name
- Title @ Company
- Session Title
- 1–2 sentence bio

**Tone:** Educational, expert-focused, credibility-building

---

### Stage 5: Registration Closing / Last Chance

**Objective:** Drive final registrations

**Timing:** 3–7 days before event

**Word Count Target:** 120–180 words (SHORT)

**CTA Strategy:** 1–2 primary CTAs (both "Register")

**Structure:**
1. Logo/Header
2. Hero Image (required: countdown or urgent visual, RED/ORANGE color)
3. Headline (e.g., "3 Days Until KubeCon Japan")
4. Deadline Statement (factual, direct)
5. **PRIMARY CTA: "Secure Your Spot"**
6. Quick Reminder (2–3 bullet benefits)
7. **SECONDARY CTA: "Register Now"** (if different action than primary)
8. Footer

**Critical Rule:** Keep it SHORT. No room for hesitation.

**Tone:** Urgent but not aggressive; direct, factual

---

### Stage 6: Event Week Reminder

**Objective:** Prepare attendees

**Timing:** 1–7 days before event

**Word Count Target:** 100–150 words

**CTA Strategy:** 1 primary, 1 optional secondary

**Structure:**
1. Logo/Header
2. Greeting + Confirmation
3. **PRIMARY CTA: "Add to Calendar"** (multi-format: Outlook, Google, iCal)
4. Key Logistics (date, time, location, timezone, parking, transit)
5. What to Bring (bulleted)
6. **SECONDARY CTA (optional): "View Schedule"**
7. Support Contact Info
8. Footer

**For Virtual Events:** Include Zoom link, tech requirements, "join 10 min early"

**For In-Person Events:** Include parking, transit, venue map, hotel info

**Tone:** Warm, helpful, supportive

---

### Stage 7: Live Event

**Objective:** Drive engagement

**Timing:** During event (morning-of)

**Word Count Target:** 80–120 words (VERY SHORT)

**CTA Strategy:** 1 primary CTA

**Structure:**
1. Good morning
2. Today's Highlights (3–4 session picks)
3. Networking Reminder
4. **PRIMARY CTA: "Today's Schedule"**
5. Footer

**Tone:** Energetic, supportive

---

### Stage 8: Thank You / Post-Event

**Objective:** Celebrate attendees and extend engagement

**Timing:** 1–2 days after event

**Word Count Target:** 120–180 words

**CTA Strategy:** 1 primary, 1 optional secondary

**Structure:**
1. Logo/Header
2. Hero Image (optional: event photos)
3. Thank You (60 words, genuine gratitude)
4. Event Highlights (statistics, quote)
5. **PRIMARY CTA: "View Recordings"**
6. What's Available (bullets: videos, slides, photos, community)
7. Feedback Request (optional secondary CTA)
8. Next Event Teaser (optional)
9. Footer

**Tone:** Grateful, reflective, community-focused

---

### Stage 9: Session Recordings Release

**Objective:** Extend engagement

**Timing:** 3–7 days after event

**Word Count Target:** 150–220 words

**CTA Strategy:** 1 primary, 1 secondary

**Structure:**
1. Logo/Header
2. Hero Image (optional: featured session)
3. Headline
4. Announcement (recordings now available)
5. **PRIMARY CTA: "Watch Sessions"**
6. Recommended Sessions (3–5 session titles)
7. Download Resources (slides, PDFs, GitHub links)
8. **SECONDARY CTA: "Join Community"**
9. Footer

**Tone:** Educational, value-focused

---

### Stage 10: Survey / Feedback

**Objective:** Collect feedback

**Timing:** Immediately after event or within 2 days

**Word Count Target:** 80–120 words (MINIMAL)

**CTA Strategy:** 1 primary CTA only

**Structure:**
1. Thank You
2. Why Feedback Matters (1–2 sentences)
3. **PRIMARY CTA: "Take the Survey"**
4. Estimated Time ("3-minute survey")
5. Footer

**Tone:** Grateful, brief, genuine

**Rule:** No additional content. Survey is the only purpose.

---

### Stage 11: Membership / Community Follow-up

**Objective:** Continue engagement

**Timing:** 1–2 weeks after event

**Word Count Target:** 180–220 words

**CTA Strategy:** 1 primary CTA

**Structure:**
1. Logo/Header
2. Hero Image (optional: community)
3. Headline ("Continue Your Journey")
4. Introduction (continue learning, stay connected)
5. Community Paths (bullets: working groups, Slack, GitHub, training)
6. Membership Info (optional, not aggressive)
7. **PRIMARY CTA: "Join the Community"**
8. Footer

**Tone:** Warm, inviting, community-first

**Critical Rule:** Focus on community first. Don't aggressively sell membership.

---

## CTA Strategy

### Primary CTA Rules

**#1: Exactly ONE primary CTA per email**

**#2: Place immediately after the introduction or value statement**

**#3: Button should appear above the fold** (first 150px of visible email)

**#4: Text should be action-oriented and specific**

**Examples:**
- ✓ "Register Now"
- ✓ "Submit Your Proposal"
- ✓ "View Full Schedule"
- ✓ "Add to Calendar"
- ✓ "Watch Recordings"
- ✗ "Learn More" (vague)
- ✗ "Click Here" (not specific)

**Button Styling:**
- Desktop: 44×44px minimum
- Mobile: 44×44px (can be 48×48px for urgent emails)
- Color: Brand primary or high-contrast (red/orange for urgent)

---

### Secondary CTA Rules

**#1: Optional. Only if it supports the primary objective.**

**#2: Maximum 2 secondary CTAs per email**

**#3: Place after supporting content, before footer**

**#4: Use lower visual priority (gray button or text link)**

**Examples of valid secondaries:**
- "View All Options"
- "Download Guide"
- "Register Now" (if primary was "View Agenda")
- "Join Community"

**Never use secondary for:**
- Unrelated actions (e.g., "Follow us on Twitter" in a registration email)
- Competing actions (e.g., two different registration pages)

---

### Total CTA Count Rule

**Never exceed 3 total CTAs per email**

**Recommended distribution:**
- 1 primary (always)
- 0–2 secondary (supporting)
- Total: 1–3 CTAs maximum

---

## Personalization Rules

### Tokens to Include

**Every email should use:**

```
{{ contact.firstname }}    // "Hi John," in greeting
{{ contact.company }}      // "As a Google engineer, you'll love..."
{{ contact.role }}         // "Whether you're a developer or architect..."
{{ contact.industry }}     // "For finance professionals..."
```

**Use in:**
- Greeting: Always ("Hi {{ contact.firstname }},")
- Body: Only if relevant (don't force personalization)
- CTA text: Rarely (keep primary CTA focused)

### Personalization Rules

**#1: Lead with personalized greeting**
- "Hi {{ contact.firstname }}," (separate paragraph with margin-bottom)
- Never run greeting into next sentence

**#2: Only personalize when relevant**
- Don't force personalization if not applicable
- Don't use tokens for generic context

**#3: Fallback gracefully**
- If token missing, use generic ("Hi there,")
- Never show raw token ("Hi {{ contact.firstname }},")

**#4: Past interaction reference (optional)**
- "We loved your question on [TOPIC] last year"
- "As a KubeCon 2025 attendee, you know..."
- Only if verified data exists

---

## Visual Design Standards

### Images

**Include images ONLY when they support the message:**

- ✓ Hero image: Announcement, Early Bird, Last Chance, Thank You
- ✓ Speaker photos: Speaker spotlight (100×100px headshots)
- ✓ Sponsor logos: Footer (40–60px height)
- ✓ Event photos: Post-event thank you
- ✓ Maps/QR codes: Event week logistics

**Never include:**
- ✗ Decorative images (no value)
- ✗ Full-body speaker photos in emails (use headshots only)
- ✗ Unrelated graphics

**Image Specs:**
- Max width: 600px (desktop)
- Format: JPG or PNG
- Always include alt text for accessibility
- File size: <200KB per image

---

### Visual Hierarchy

**Follow this order consistently:**

```
LOGO / Header
↓
Preheader / Preview Text
↓
Hero Image (optional, stage-dependent)
↓
HEADLINE (22–26px, bold)
↓
Short Introduction (16px)
↓
PRIMARY CTA
↓
Supporting Content Sections
  - Headings (18–20px)
  - Body text (16px)
  - Bullets (16px)
↓
Social Proof (testimonials, counts)
↓
SECONDARY CTA (optional)
↓
FOOTER (14px)
```

---

### Social Proof Placement

**Place AFTER value has been established, NOT first.**

**Examples:**
- Speaker photos (with names, titles)
- Sponsor logos
- Attendee count ("5,000+ attendees from X countries")
- Testimonials ("Best conference I've attended" - Sarah Chen, VP Engineering)
- Previous year stats ("4.8/5 star rating from attendees")

**Rule:** Social proof supports claims, doesn't lead the email

---

## Accessibility Requirements

### WCAG Best Practices

**#1: Use meaningful headings**
- Heading hierarchy: H1 (headline) → H2 (sections) → H3 (subsections)
- Don't skip heading levels
- Every section must have a descriptive heading

**#2: Alt text for all images**
- Required for hero images
- Describe what the image shows
- Example: "KubeCon Japan 2026 conference venue in Yokohama"

**#3: High contrast for readability**
- Heading/body text: Minimum 4.5:1 contrast ratio
- CTA buttons: At least 4.5:1 contrast
- Tool: Use WebAIM contrast checker

**#4: Descriptive CTA text**
- ✓ "Register Now"
- ✓ "View Full Schedule"
- ✗ "Click Here"
- ✗ "Submit"

**#5: Semantic HTML**
- Use <h1>, <h2>, <h3> for headings (not just bold text)
- Use <ul><li> for lists (not • character)
- Use <strong> or <b> for emphasis (not ALL CAPS)
- Use <a> tags for all links

**#6: Avoid image-only communication**
- Never use images for critical information
- Always supplement images with text
- Example: Include text "Event Date: July 28-30" in addition to hero image with date

---

## Mobile-First Design

### Requirements

**#1: Single column layout**
- No multi-column grids or complex tables
- All content stacks vertically
- 100% responsive width

**#2: Large, readable fonts**
- Body text: 16px minimum
- Headings: 18–22px minimum
- Never go below 14px (even for fine print)

**#3: Generous whitespace**
- 20px padding around buttons
- 15px between sections
- 1 blank line between paragraphs

**#4: Large, tappable buttons**
- 44×44px minimum (Apple HIG standard)
- 48×48px for urgent emails (Last Chance, Registration Closing)
- Full-width on mobile OR 2-column grid on desktop

**#5: Easy scanning on small screens**
- Bullets and lists format clearly
- Headings stand out visually
- CTA button visible without scrolling (above-the-fold)

---

## AI Generation Guidelines

### For Claude/AI Models

When generating email content, prioritize:

**#1: Value before promotion**
- Explain why the information matters before asking readers to act
- Lead with benefit, not with the ask

**#2: Authentic, conversational language**
- Write like a community manager (not a bot)
- Use contractions ("we're" not "we are")
- Avoid corporate jargon

**#3: Highlight learning, collaboration, community**
- "Learn from peers"
- "Connect with the community"
- "Share your experience"
- NOT "exclusive opportunity" or "limited slots"

**#4: Build urgency only with real deadlines**
- Use factual dates ("Registration closes June 15")
- NOT fake urgency ("Don't miss out!" "Act now!")
- NOT false scarcity ("Only 5 spots left" if capacity is 5,000)

**#5: Keep technical accuracy high**
- Date formats correct
- Session names accurate
- Speaker titles current

**#6: Avoid repetitive phrases and AI clichés**
- ✗ "We're thrilled to announce..."
- ✗ "Don't miss this amazing opportunity..."
- ✗ "Join us as we dive deep into..."
- ✓ "We're sharing the speaker lineup for..."
- ✓ "Here's what you'll learn at..."
- ✓ "Discover X topic across Y sessions..."

**#7: Ensure every section naturally leads to the next**
- Intro → Proof → CTA → Supporting content → Footer
- Each section transitions logically
- No abrupt topic changes

**#8: End with a single, clear action**
- Aligned with email's primary objective
- No competing actions
- Call back to the main CTA

---

## QA Checklist Before Publishing

### Content Quality

- [ ] **One goal per email** — Primary objective is clear
- [ ] **Word count** — Matches target for this stage (see Email Architecture)
- [ ] **Paragraph count** — Maximum 2–3 sentences per paragraph
- [ ] **No marketing buzzwords** — Check for: "amazing," "revolutionary," "don't miss," "act now," "exclusive," "limited"
- [ ] **Tone is authentic** — Reads like community manager, not marketer
- [ ] **Scannable** — Can be understood in 30–60 seconds

### Structure & Layout

- [ ] **Headings present** — Every major section has a descriptive heading
- [ ] **Bullets used effectively** — 3–5 items max, short phrases
- [ ] **Whitespace included** — 1 blank line between paragraphs
- [ ] **Visual hierarchy clear** — Logo → Headline → Intro → CTA → Content → Footer

### CTA Strategy

- [ ] **Primary CTA present** — Exactly 1, placed after introduction
- [ ] **Primary CTA visible above-the-fold** — No scrolling required
- [ ] **CTA text is specific** — Not "Click here," but "Register Now" or "View Schedule"
- [ ] **Button size correct** — 44×44px minimum (48×48px if urgent)
- [ ] **Secondary CTA count** — Max 2 (preferred: 0–1)
- [ ] **Total CTA count** — Max 3 per email

### Personalization

- [ ] **Greeting uses token** — "Hi {{ contact.firstname }},"
- [ ] **Token appears in separate <p>** — Not run into next sentence
- [ ] **No exposed tokens** — No {{ }} showing in published version
- [ ] **Fallback exists** — Generic version if token missing

### Visual Design

- [ ] **Hero image appropriate** — Present if required for stage
- [ ] **Images have alt text** — Descriptive, not just filename
- [ ] **Sponsor logos present** — Footer, 40–60px height
- [ ] **No decorative images** — Every image supports the message
- [ ] **Image max width 600px** — Desktop responsive

### Accessibility

- [ ] **Heading hierarchy correct** — H1 → H2 → H3, no skipping
- [ ] **Contrast ratio 4.5:1+** — Text, headings, CTA buttons readable
- [ ] **Alt text for all images** — Descriptive, meaningful
- [ ] **CTA text descriptive** — "Register Now" not "Click Here"
- [ ] **Semantic HTML** — <h2>, <ul><li>, <strong>, <a> tags used
- [ ] **No image-only information** — Critical content has text backup

### Mobile-First Design

- [ ] **Single column layout** — No multi-column grids
- [ ] **Font size 16px minimum** — All body text readable
- [ ] **Button size 44×44px minimum** — Tappable on mobile
- [ ] **Whitespace generous** — 20px padding, 15px spacing
- [ ] **No horizontal scroll** — All content fits 375px width
- [ ] **CTA visible without scrolling** — Above-the-fold placement

### Links & CTAs

- [ ] **All links functional** — No broken URLs
- [ ] **Link text descriptive** — Not "here" or "click"
- [ ] **UTM parameters added** — If applicable for tracking
- [ ] **Link colors accessible** — Sufficient contrast

### Final Review

- [ ] **Proofread for typos** — Spell-checked, grammar-checked
- [ ] **Dates are accurate** — Event dates, deadlines, times correct
- [ ] **Speaker/topic names correct** — Verified against source data
- [ ] **No placeholder text** — All [BRACKETS] replaced with real values
- [ ] **Personalization tokens test** — Verified in test email with real contact
- [ ] **Send list correct** — Intended recipient list verified
- [ ] **Unsubscribe link present** — Legal requirement
- [ ] **Footer complete** — Company name, address, contact info present

### Before Hitting "Send"

- [ ] **Preview in 3+ email clients** — Gmail, Outlook, Apple Mail
- [ ] **Test on mobile phone** — Open on real device (not just emulator)
- [ ] **Check spam folder** — Verify not going to spam
- [ ] **Timing correct** — Send time appropriate for audience timezone
- [ ] **Post-send verification** — Check first few opens/clicks in HubSpot

---

## Campaign Lifecycle Example

### Complete Campaign Sequence (8–12 weeks)

```
WEEK 1:   Event Announcement
          ↓ 3–5 days
WEEK 2:   Early-Bird Registration (with deadline)
          ↓ 1 week
WEEK 3:   Speaker Spotlight (credibility)
          ↓ 5 days
WEEK 4:   Agenda Release (learning opportunities)
          ↓ 2 weeks
WEEK 6:   Social Proof (FOMO light: "X registered")
          ↓ 1 week
WEEK 7:   Last-Chance Early-Bird (deadline approaching)
          ↓ 2 weeks
WEEK 9:   Final Reminder (week before)
          ↓ 3 days
WEEK 11:  Event Week Logistics (2–3 days before)
          ↓ 1 day
WEEK 12:  Day-Before Reminder (optional)
          ↓ 1 day
EVENT:    Event Week Live Engagement (morning-of emails)
          ↓ 1–2 days after
POST:     Thank You + Recordings
          ↓ 3–7 days
          Survey/Feedback
          ↓ 1–2 weeks
          Community Follow-Up (next event teaser)
```

---

## Tone & Voice Reference

### By Campaign Stage

| Stage | Tone | Vibe | Energy |
|-------|------|------|--------|
| **Announcement** | Professional, warm | Welcoming | Moderate |
| **CFP** | Inclusive, encouraging | "We want your voice" | Moderate-High |
| **Early Bird** | Direct, value-focused | "Save money" | Moderate |
| **Spotlight** | Educational, credible | "Learn from experts" | Moderate |
| **Last Chance** | Urgent, factual | "Time running out" | High |
| **Event Week** | Warm, helpful | "We've got you" | Moderate |
| **Live Event** | Energetic, supportive | "Join the conversation" | High |
| **Thank You** | Grateful, reflective | "Community moment" | Moderate |
| **Recordings** | Value-focused, educational | "Keep learning" | Low-Moderate |
| **Survey** | Brief, grateful | "Help us improve" | Low |
| **Community** | Inviting, community-first | "Keep the connection" | Moderate |

---

## Common Mistakes to Avoid

### ❌ Mistake #1: Multiple Competing CTAs
- ✗ Register, View Schedule, Download Guide, Join Slack, Follow Twitter (5 CTAs)
- ✓ Primary CTA + 1 optional secondary maximum

### ❌ Mistake #2: Marketing Buzzwords
- ✗ "Don't miss this amazing, revolutionary opportunity"
- ✓ "Here's what you'll learn at KubeCon Japan"

### ❌ Mistake #3: Fake Urgency
- ✗ "Only 3 spots left!" (when capacity is 5,000)
- ✓ "Early bird pricing ends June 15"

### ❌ Mistake #4: Long Paragraphs
- ✗ 7+ sentences, 100+ words in one paragraph
- ✓ 2–3 sentences, 25–60 words maximum

### ❌ Mistake #5: No Section Headings
- ✗ One continuous block of content
- ✓ Clear headings: "Why Attend," "Featured Speakers," etc.

### ❌ Mistake #6: Generic CTA Text
- ✗ "Click Here," "Learn More," "Submit"
- ✓ "Register Now," "View Full Schedule," "Submit Your Proposal"

### ❌ Mistake #7: Unescaped Personalization Tokens
- ✗ Email shows "Hi {{ contact.firstname }},"
- ✓ Email shows "Hi John,"

### ❌ Mistake #8: No Alt Text for Images
- ✗ Images are decorative with no description
- ✓ All images have descriptive alt text

### ❌ Mistake #9: Button Too Small
- ✗ Button is 30×30px, hard to tap on mobile
- ✓ Button is 44×44px+ for easy tapping

### ❌ Mistake #10: No Whitespace
- ✗ Text blocks run together
- ✓ 1 blank line between paragraphs, 20px padding around buttons

---

## Template for New Emails

Use this as a starting point for any new campaign email:

```
Subject: [EMOJI] [HEADLINE/ACTION]
Preview: [25–40 character preview text]

Hi {{ contact.firstname }},

[INTRODUCTION — 1–2 sentences, 25–50 words]

[ PRIMARY CTA ]

[SECTION HEADING]
[Supporting content — 60–100 words, bullets if possible]

[SECTION HEADING]
[Supporting content — 60–100 words, bullets if possible]

[ SECONDARY CTA (optional) ]

[CLOSING — 1 sentence, warm tone]

The [Organization] Team
---
[Unsubscribe link]
[Contact info]
[Social media links]
```

---

## Questions?

For implementation questions or edge cases, refer back to:
- **Core Principles** (#1: One goal, #2: 30–60 seconds, #3: Community voice)
- **Writing Guidelines** (Paragraphs, headings, bullets)
- **CTA Strategy** (1 primary max)
- **QA Checklist** (Before publishing)

When in doubt, ask: "Would a trusted community manager write this?"

