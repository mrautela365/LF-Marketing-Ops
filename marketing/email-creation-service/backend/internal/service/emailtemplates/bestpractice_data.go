package emailtemplates

// BestPracticeTemplates ports BEST_PRACTICE_TEMPLATES verbatim.
var BestPracticeTemplates = map[string]BestPracticeTemplate{
	"B2B_Event_Announcement": {
		Source:          "ArgoCon + KeycloakCon Japan 2026",
		QualityRating:   5,
		ConversionType:  "announcement",
		SenderProfile:   "Sr. Global Event Partnerships Manager",
		ExpectedOpenPct: 0.45,
		ExpectedCTRPct:  0.12,
		Template: BestPracticeVariant{
			ID:        "b2b_announcement",
			Label:     "B2B Event Announcement (ArgoCon Template)",
			Strategy:  "Build excitement + relationship focus + multiple CTAs",
			Subject:   "[Event Name] + [Co-Location] - [Key Achievement]!",
			Preheader: "[Number]+ attendees | [City] | [Date] | Schedule live",
			Body: `Hi [PERSONALIZATION: names],

We're excited to announce that [Event Name] [co-located with major event] is officially here.

📍 [City] | 📅 [Dates] | 🎟️ [Expected attendee count]+ expected

KEY HIGHLIGHTS:
• Schedule and speakers officially announced
• [Co-location advantage] (expanded reach + combined attendance)
• [Number]+ sessions across [key tracks]
• [Sponsor showcase details if applicable]
• Sponsorship deadline: [Date]

[RELATIONSHIP ELEMENT: historical context, past sponsorships]

NEXT STEPS:
[Soft CTA]: Schedule a meeting to discuss → [Calendar link]
[Medium CTA]: Review sponsorship prospectus → [Prospectus link - page X]
[Hard CTA]: Lock in sponsorship now → [Contract link]

Looking forward to seeing you in [City]!
[Sender name]
[Title]
[Phone] | [Website] | [Calendar]

P.S. [Humanizing element: personal note, travel info, availability]`,
		},
	},

	"B2B_Speaker_Conversion": {
		Source:          "ArgoCon Speaker Confirmations (Pooja Dhir)",
		QualityRating:   5,
		ConversionType:  "speaker_to_sponsor",
		SenderProfile:   "Event Partnerships Associate",
		ExpectedOpenPct: 0.52,
		ExpectedCTRPct:  0.18,
		Template: BestPracticeVariant{
			ID:        "b2b_speaker_conversion",
			Label:     "B2B Speaker Conversion (ArgoCon Template)",
			Strategy:  "Congratulate first, convert second - achievement focus",
			Subject:   "Congratulations on [Company]'s Speaking Slot at [Event]!",
			Preheader: "Speaking slot confirmed | Maximize visibility | Sponsorship opportunity",
			Body: `Hi [SPEAKER_NAME],

Congratulations on [Company] being selected to speak at [Event]! This is a great achievement for your team.

YOUR SPEAKING OPPORTUNITY:
Your expertise on [topic] will resonate with our [audience size]+ attendees. To maximize visibility and engagement, many speakers supplement with sponsorship to:
• Increase booth presence during sessions
• Host private meetings with attendees
• Showcase products/services in sponsor showcase
• Extend reach through co-located events

IS SPONSORSHIP RIGHT FOR YOU?
Our sponsorship prospectus (page [X]) outlines all tiers and benefits. Would you be the right person to discuss this with, or should I connect with someone from your marketing team?

NEXT STEPS:
[Soft CTA]: Schedule a call → [Calendar link]
[Medium CTA]: Review prospectus → [Prospectus link - page X]
[Hard CTA]: Yes, let's discuss sponsorship

Sponsorship deadline: [DATE] (limited spots available)

[Sender name]
[Title]
[Phone] | [Website] | [Calendar]`,
		},
	},

	"B2B_Strategic_Close": {
		Source:          "ArgoCon Strategic Opportunities (Nicole Puopolo)",
		QualityRating:   5,
		ConversionType:  "complex_multi_event_deal",
		SenderProfile:   "Sr. Global Event Partnerships Manager",
		ExpectedOpenPct: 0.48,
		ExpectedCTRPct:  0.14,
		Template: BestPracticeVariant{
			ID:        "b2b_strategic_close",
			Label:     "B2B Strategic Multi-Event Close (ArgoCon Template)",
			Strategy:  "Comprehensive context + transparent pricing + urgency + multiple options",
			Subject:   "[Event List] - Ready for a contract?",
			Preheader: "Multiple sponsorship opportunities | Limited spots | [Deadline]",
			Body: `Hi [ACCOUNT_NAME],

Our KubeCon co-located events are now live, and [Company] is at the top of our request list for sponsorship.

OPPORTUNITY OVERVIEW:
You previously expressed interest in sponsoring multiple events. Here's what's available:
• [Event 1] - Diamond sponsorship available
• [Event 2] - Diamond sponsorship available
• [Co-Located Event 3] - Platinum available
• [Waitlist status if applicable]

TRANSPARENT PRICING:
Diamond Sponsorship: $[PRICE] (3% discount for multiple events = $[DISCOUNTED] each)
Platinum Sponsorship: $[PRICE]

DECISION TIMELINE:
5 business days to sign & finalize (Deadline: [DATE])
[Scarcity messaging if limited spots]

FULL CO-LOCATED OPTIONS (12+ events):
[Complete list with links to each event prospectus page]

ALL-INCLUSIVE BENEFITS:
✓ Booth presence at all events
✓ Speaking slot(s)
✓ Private meeting room access
✓ Sponsor showcase participation
✓ Brand visibility across campaigns
✓ Post-event content access

DO YOU WANT TO MOVE FORWARD?
Let's get this locked in. I'm available to:
[CTA 1]: Schedule a call → [Calendar link]
[CTA 2]: Send contract immediately → [Contract link]
[CTA 3]: Discuss questions → Reply to this email or call [PHONE]

Looking forward to partnering with [Company]!
[Sender name]
[Title]
[Phone] | [Website] | [Calendar]

P.S. I'll be in [CITY] [DATE] - happy to meet in person if helpful.`,
		},
	},

	"B2B_Rapid_Close": {
		Source:          "ArgoCon Quick Closes (Pooja Dhir)",
		QualityRating:   4,
		ConversionType:  "existing_account_contract",
		SenderProfile:   "Event Partnerships Associate",
		ExpectedOpenPct: 0.35,
		ExpectedCTRPct:  0.22,
		Template: BestPracticeVariant{
			ID:        "b2b_rapid_close",
			Label:     "B2B Rapid Close - Existing Accounts (ArgoCon Template)",
			Strategy:  "Minimal friction - assumes context, fast to contract",
			Subject:   "[Company] [Tier] Sponsorship for [Event]",
			Preheader: "Contract ready | Quick turnaround | [Tier] included",
			Body: `Hi [CONTACT_NAME],

I'm looping in our Event Sales Ops team to send your [TIER] sponsorship contract for [Event Name].

They'll handle next steps. Any questions, let me know!

[Sender name]
[Title]
[Phone] | [Calendar link]`,
		},
	},

	"B2B_Registration_Launch": {
		Source:          "ArgoCon Registration/CFP Launch",
		QualityRating:   4,
		ConversionType:  "registration_and_sponsorship",
		SenderProfile:   "Sr. Global Event Partnerships Manager",
		ExpectedOpenPct: 0.40,
		ExpectedCTRPct:  0.10,
		Template: BestPracticeVariant{
			ID:        "b2b_registration_launch",
			Label:     "B2B Registration/CFP Launch (ArgoCon Template)",
			Strategy:  "Conversational + deadline-driven + information dense",
			Subject:   "[Event Name] - Deadline [DATE]",
			Preheader: "Registration open | Schedule announced | Deadline approaching",
			Body: `Hi [CONTACT_NAME],

One more email from me today! (I promise this is the last one... for now!)

I wanted to check in - would you want to add [Event Name] to your sponsorship calendar?

EVENT DETAILS:
📍 [City] | 📅 [Dates]
Venue: [Venue Name]

REGISTRATION LINK: [Link]
PROSPECTUS: Page [X] with full details → [Link]

KEY DEADLINE: [DATE]
[Upcoming announcement: "Schedule will be announced [Date]" - builds anticipation]

SPONSORSHIP TIERS AVAILABLE:
✓ Diamond: $[Price]
✓ Platinum: $[Price]
✓ Gold: $[Price]

NEXT STEPS:
[Soft CTA]: Add to calendar → [Calendar link]
[Medium CTA]: Review prospectus → [Prospectus link]
[Hard CTA]: Schedule sponsorship call → [Calendar link]

Let me know if you have any questions!

[Sender name]
[Title]
[Phone] | [Website] | [Calendar]

P.S. [Personal element: travel info, availability]`,
		},
	},
}

// TemplateTypeMapping ports TEMPLATE_TYPE_MAPPING verbatim.
var TemplateTypeMapping = map[string]string{
	"announcement":           "B2B_Event_Announcement",
	"speaker_conversion":     "B2B_Speaker_Conversion",
	"multi_event_deal":       "B2B_Strategic_Close",
	"existing_account_close": "B2B_Rapid_Close",
	"registration_launch":    "B2B_Registration_Launch",
}
