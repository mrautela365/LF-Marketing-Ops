"""
LF Events Marketing Journey — stage-matched email templates.
Source: https://bi-weekly-dashboard.onrender.com/events-marketing-journey.html

Each entry contains:
  subject         — primary subject line template
  preheader       — preview/preheader text template
  body            — full plain-text email body template

Placeholders to substitute before sending to Claude:
  [Event Name]    → actual event name
  [City]          → event city
  [Dates]         → event dates
  [Date]          → a specific deadline date
  {{first_name}}  → personalization token (keep as-is for HubSpot)
  {{company_name}}→ personalization token (keep as-is)
  [LINK]          → replace with actual event URL
"""

STAGE_TEMPLATES: dict[str, dict] = {

    "Event Announcement": {
        "subject": "Save the Date: [Event Name] is Coming to [City]!",
        "preheader": "Join 10,000+ developers [Dates] in [City] | Early bird opens soon",
        "body": """Hi {{first_name}},

The wait is over. [Event Name] 2026 dates are officially here.

📍 [City] | 📅 [Dates] | 🎟️ 10,000+ attendees expected

Why this matters for {{company_name}}:
• 200+ sessions across cloud native, AI/ML, security & platform engineering
• Hands-on workshops with the latest OSS tools your team is already using
• Face-to-face access to project maintainers
• Unmatched networking with peers solving the same challenges you are

Mark your calendar now.

🐦 Early bird registration opens soon – save $300 when you act fast.

Stay tuned for keynote announcements, session highlights, and exclusive attendee perks.

See you in [City],
The Linux Foundation Events Team

P.S. Forward this to your team lead – group discounts (5+ attendees) will be available soon.""",
    },

    "CFP Launch": {
        "subject": "Call for Proposals Now Open – Share Your Expertise at [Event Name]",
        "preheader": "First-time speakers welcome | Mentorship available | Deadline [Date]",
        "body": """Hi {{first_name}},

The Call for Proposals is officially OPEN for [Event Name] – and we want to hear YOUR story.

🎯 Why your experience matters:
The community needs real-world insights. Whether you're scaling Kubernetes, implementing zero-trust security, or building AI/ML pipelines – your challenges and solutions will resonate.

📋 We're looking for sessions on:
• Cloud Native & Kubernetes (platform engineering, scaling, cost optimization)
• AI/ML in Open Source (LLMs, training infrastructure, model deployment)
• Security & Supply Chain (zero trust, SBOM, vulnerability management)
• Platform Engineering (developer experience, golden paths)
• Community & Open Source Culture

🎤 Session formats:
→ Breakout (40 min) – Deep dive with Q&A
→ Lightning Talk (10 min) – Quick hit, high impact
→ Workshop (90 min) – Hands-on learning
→ Panel – Multiple perspectives

🗓️ CFP closes: [Date]

[Submit Your Proposal →]

First-time speaker? We offer mentorship, proposal reviews, and speaker coaching.

The Linux Foundation Events Team""",
    },

    "Registration Launch": {
        "subject": "🎟️ Early Bird Registration is LIVE – Save $300",
        "preheader": "Early bird $999 (reg $1,299) | Ends [Date] | 200+ sessions included",
        "body": """Hi {{first_name}},

The moment you've been waiting for – registration for [Event Name] is NOW OPEN.

🐦 EARLY BIRD SPECIAL: Save $300 when you register by [Date]
Regular: $1,299 → Early Bird: $999

That's 23% off – but only for the next [X] days.

🎟️ Your all-access pass includes:
✓ 200+ sessions across 12 tracks (cloud native, AI/ML, security, platform engineering)
✓ All keynotes & co-located events
✓ Sponsor showcase with 100+ exhibitors & hands-on demos
✓ Networking events and receptions
✓ All meals during conference days
✓ Post-event access to session recordings

[Register Now & Save $300 →]

---

👥 BRINGING YOUR TEAM?
• 5-9 attendees: Save $100/person
• 10+ attendees: Save $200/person

🎓 Need assistance? Scholarships & travel funds available.

The Linux Foundation Events Team""",
    },

    "Co-Located Events + CFP Reminder": {
        "subject": "NEW: 5 Co-Located Events Added + CFP Closes Soon",
        "preheader": "All included with your pass | CFP closes [Date] | Don't miss out",
        "body": """Hi {{first_name}},

Big news: [Event Name] just got WAY more valuable.

We just announced co-located events — ALL included with your registration:

🔹 [Co-Located Event 1] – Deep dive into cloud native topics
🔹 [Co-Located Event 2] – Hands-on security & supply chain workshop
🔹 [Co-Located Event 3] – Community Day
🔹 [Co-Located Event 4] – AI/ML Summit
🔹 [Co-Located Event 5] – Developer Experience Unconference

💡 What this means for you:
→ One registration = access to multiple events
→ More specialized tracks in the areas you care about
→ Smaller, focused sessions with project maintainers

Already registered? Your pass automatically includes all these events.
Haven't registered yet? This is your reminder to lock in early bird pricing.

⏰ REMINDER: CFP closes [Date].
If you've been thinking about speaking, now is the time.

[Register Now →] | [Submit CFP →]

The Linux Foundation Events Team""",
    },

    "DEI & Travel Fund": {
        "subject": "Need Support to Attend? Scholarships & Travel Fund Now Open",
        "preheader": "Full pass + up to $1,500 travel support | Deadline [Date] | Everyone welcome",
        "body": """Hi {{first_name}},

Let's be real: Conference costs can be a barrier. We know that.

That's why we're opening applications for scholarships and travel funds — because talent and potential aren't limited to those with big budgets.

---

🎓 DIVERSITY SCHOLARSHIP
Full conference pass included

Who should apply:
✓ Women, non-binary, and gender minorities in tech
✓ Black, Indigenous, Latinx, and other underrepresented groups
✓ LGBTQ+ technologists
✓ People with disabilities
✓ Career changers entering tech
✓ First-generation college students
✓ Anyone from an underrepresented community in open source

✈️ TRAVEL FUND
Up to $1,500 for flights, hotel, and expenses

🗓️ Application deadline: [Date]

[Apply for Scholarship →] | [Apply for Travel Fund →]

We believe [Event Name] is stronger when everyone is in the room.

The Linux Foundation Events Team""",
    },

    "Schedule Announcement": {
        "subject": "🗓️ The Schedule is LIVE – Plan Your [Event Name] Experience",
        "preheader": "Keynotes revealed | 12 tracks | 50+ workshops | Schedule builder live",
        "body": """Hi {{first_name}},

The moment you've been waiting for – the [Event Name] schedule is here!

🌟 KEYNOTE SPEAKERS ANNOUNCED:
• [Speaker 1], [Title] at [Company]
• [Speaker 2], [Title] at [Company]
• [Speaker 3], [Title] at [Company]

📊 BY THE NUMBERS:
• 200+ sessions across 12 tracks
• 50+ workshops & tutorials
• 30+ lightning talks
• 15+ BoF sessions

🔥 NOT TO MISS:
• Sessions on cloud native, AI/ML, security, and platform engineering
• Hands-on workshops for every level
• Community-led Birds of a Feather sessions

[Explore Full Schedule →]

💡 Pro tip: Use the schedule builder to create your personalized agenda.

⏰ Early bird ends in 2 weeks – register now to save $300.

[Register at Early Bird Rate →]

The Linux Foundation Events Team""",
    },

    "Main Registration Push": {
        "subject": "⚡ Early Bird Ends Friday – Don't Miss Your $300 Savings",
        "preheader": "Price increases after [Date] | 5,000+ already registered | Lock in savings now",
        "body": """Hi {{first_name}},

This is it – early bird pricing ends THIS FRIDAY.

After [Date], registration increases by $300. Lock in your savings now.

[Register Before Price Increase →]

---

WHY ATTEND [EVENT NAME]?

💬 "Best conference for cloud native – the hallway track alone is worth it."
💬 "I implemented what I learned and reduced our deployment time by 40%."
💬 "Made connections that led to my next job offer."

---

WHAT'S INCLUDED IN YOUR PASS:
✓ 200+ sessions, all keynotes, co-located events
✓ Sponsor showcase with 100+ exhibitors & hands-on labs
✓ Welcome reception & daily networking events
✓ All meals during the conference
✓ Post-event access to session recordings
✓ Certificate of attendance

[Secure Your Spot →]

Price goes up [Date]. Don't wait.

The Linux Foundation Events Team""",
    },

    "Final Countdown": {
        "subject": "🚨 Final Call: Registration Closes in 48 Hours",
        "preheader": "Online registration ends [Date] | Limited onsite availability | Act now",
        "body": """Hi {{first_name}},

[Event Name] registration closes in 48 HOURS.

After [Date], online registration closes and only limited onsite walk-up availability remains.

[Register Now – Before It's Too Late →]

---

HERE'S WHAT YOU'LL MISS IF YOU DON'T REGISTER:

❌ 200+ sessions from industry leaders
❌ Hands-on workshops with cutting-edge OSS tools
❌ Face-to-face networking with 10,000+ peers
❌ The energy and inspiration of the open source community
❌ Career opportunities and connections that could define your next move

---

⭐⭐⭐⭐⭐ "Career-changing. Period." – Past attendee
⭐⭐⭐⭐⭐ "Best investment I made for my career this year." – Past attendee

This is your last chance.

[Register Now →]

The Linux Foundation Events Team""",
    },

    "Event Week": {
        "subject": "🎉 Welcome to [Event Name] – Your Day 1 Guide",
        "preheader": "Badge pickup open | Opening keynote today | Download the app",
        "body": """Hi {{first_name}},

IT'S HERE! Welcome to [Event Name] 2026.

📍 YOUR DAY 1 ESSENTIALS:

🎫 BADGE PICKUP
[Location] | Opens [Time]
Have your QR code ready (check your confirmation email)

🎤 DON'T MISS TODAY:
• [Time]: Opening Keynote – [Ballroom]
• [Time]: Welcome Reception – [Location]

📱 DOWNLOAD THE APP
Schedule, maps, networking, live updates
Available on App Store & Google Play

---

PRO TIPS:
• Arrive early for keynotes – seating fills fast
• Visit the sponsor showcase for hands-on demos
• Use the app to connect with other attendees
• Bookmark sessions for reminders 10 minutes before they start

---

📍 VENUE: [Venue Name], [City]
🚌 Getting here: [Transportation info]
🍽️ Meals: Breakfast & lunch provided in [Hall]
💊 First aid: [Location]

See you there!
The Linux Foundation Events Team""",
    },

    "Thank You + Survey": {
        "subject": "Thank You for Joining [Event Name] – Share Your Feedback",
        "preheader": "Complete our 5-min survey | Recordings coming soon | Stay connected",
        "body": """Hi {{first_name}},

What an incredible week! Thank you for being part of [Event Name] 2026.

We hope you left inspired, connected, and energized.

📝 SHARE YOUR FEEDBACK (5-min survey)
Your input directly shapes future events.

[Take the Survey →]

---

🎬 SESSION RECORDINGS
Recordings will be available in your LFX portal within 2 weeks.

[Access Your LFX Portal →]

📸 EVENT PHOTOS
Relive the memories – photos will be live shortly!

---

STAY CONNECTED:
• Join the conversation: #[EventHashtag]
• Community Slack – continue discussions with peers
• Newsletter – get updates on [Event] 2027

💡 Share your key takeaways with your team and keep the momentum going!

Thank you again for being part of our community.

The Linux Foundation Events Team""",
    },

    "Content & Recordings Release": {
        "subject": "🎬 [Event Name] Session Recordings Are Now Live",
        "preheader": "200+ sessions on demand | Watch keynotes, workshops & more | Free for attendees",
        "body": """Hi {{first_name}},

The sessions you loved (and the ones you missed) are now available!

🎬 200+ SESSION RECORDINGS
All sessions from [Event Name] are now in your LFX portal – watch anytime, anywhere.

[Access Session Recordings →]

---

🔥 MOST-WATCHED SESSIONS:

1. [Top Session Title] – [Speaker]
2. [Top Session Title] – [Speaker]
3. [Top Session Title] – [Speaker]

💡 Pro tip: Create a watch list and share it with your team. Maximize your learning ROI!

---

📝 BLOG RECAPS & KEY ANNOUNCEMENTS:
• Top 10 Technical Takeaways
• Major Project Announcements
• Community Award Winners
• Event By The Numbers

[Read the Recap →]

🔗 SHARE YOUR EXPERIENCE:
Tag us with #[EventHashtag] and share your biggest takeaway on LinkedIn.

The Linux Foundation Events Team""",
    },

    "Next Event CFP Teaser": {
        "subject": "The Next Chapter: [Event Name] 2027 – CFP Opens Soon",
        "preheader": "Save the date | VIP CFP access for past attendees | Early bird notification",
        "body": """Hi {{first_name}},

[Event Name] 2026 was unforgettable. But we're already looking ahead.

📅 SAVE THE DATE
[Event Name] 2027
[Dates] | [City]

---

🎤 WANT TO SPEAK AT [EVENT NAME] 2027?

CFP opens [Date] – and as a past attendee, you get VIP treatment.

Join our Speaker Interest List for:
• 48-hour early CFP access before public announcement
• Trending topic suggestions from the program committee
• First-time speaker resources & mentorship matching

[Join Speaker Interest List →]

---

🐦 EARLY BIRD NOTIFICATION (VIP ACCESS)

Be first to know when 2027 registration opens and get the best pricing before anyone else.

[Get Early Bird Notification →]

---

📣 HELP US SPREAD THE WORD
Know someone who would love [Event Name]? Share this with your network.

See you in [City]!
The Linux Foundation Events Team""",
    },

    "Community Nurture": {
        "subject": "Stay Connected: [Month] Community Update from Linux Foundation Events",
        "preheader": "Community news, learning opportunities & upcoming events",
        "body": """Hi {{first_name}},

Here's what's happening in the [Event/Project] community this month:

📰 COMMUNITY NEWS
• [Announcement 1]
• [Announcement 2]
• [Project milestone or update]

---

🎓 LEARNING OPPORTUNITIES

• [Course/Certification] – Free for community members
• [Upcoming Webinar] – [Date/Time]

[Explore LFX Training Catalog →]

---

👥 GET INVOLVED

🌟 Mentorship Program
Applications open for the next cohort.
[Apply as Mentor] | [Apply as Mentee]

💬 Community Meetings
Join our monthly community call – [Date/Time]
[Add to Calendar]

🏆 Contributor Spotlight
Know someone doing amazing work? Nominate them!

---

📅 UPCOMING EVENTS
• [Event 1] – [Date], [City]
• [Event 2] – [Date], [City]

[See All Upcoming Events →]

Stay connected and keep contributing!
The Linux Foundation Events Team""",
    },
}


def get_template(stage_name: str) -> dict | None:
    """Return the template dict for a given stage name, or None if not found."""
    return STAGE_TEMPLATES.get(stage_name)


def get_all_stage_names() -> list[str]:
    return list(STAGE_TEMPLATES.keys())
