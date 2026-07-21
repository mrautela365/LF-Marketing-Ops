"""
LF Events Marketing Journey — stage-matched email templates with messaging variants.
Source: https://bi-weekly-dashboard.onrender.com/events-marketing-journey.html

Each stage contains multiple variants with different messaging strategies:
  v1, v2, v3, etc. — alternative approaches (value-focused, urgency-focused, social proof, etc.)

Each variant contains:
  id        — unique variant identifier (e.g., "v1_value_focused")
  label     — human-readable variant name
  strategy  — marketing strategy description
  subject   — subject line template
  preheader — preview/preheader text template
  body      — full plain-text email body template

Placeholders to substitute before sending:
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
        "variants": [
            {
                "id": "v1_value_focused",
                "label": "Value-Focused Messaging",
                "strategy": "Emphasizes learning, networking, and community value",
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
            {
                "id": "v2_urgency_focused",
                "label": "Urgency & Savings Focus",
                "strategy": "Highlights early bird savings and limited-time advantage",
                "subject": "🚨 Early Bird Alert: [Event Name] Dates Just Announced – Save $300",
                "preheader": "Early bird opens [Date] | 10,000+ developers will attend | Mark your calendar",
                "body": """Hi {{first_name}},

The [Event Name] 2026 dates are officially locked in – and early bird pricing is about to drop.

📍 [City] | 📅 [Dates]

🐦 EARLY BIRD OPENS [DATE] — Save $300 on your pass

Here's what you need to know:
• Regular price: $1,299
• Early bird: $999 (saves you $300)
• Limited to first 1,000 registrations

This is your reminder to watch for the registration link drop. When early bird opens, spots fill fast.

🎯 Inside [Event Name]:
✓ 200+ sessions from industry leaders
✓ 50+ hands-on workshops
✓ 100+ sponsors with live demos
✓ Unmatched networking with 10,000+ peers

[Mark Your Calendar →]

The Linux Foundation Events Team

P.S. Bringing your team? Group discounts (5+ people) will save you even more.""",
            },
            {
                "id": "v3_social_proof",
                "label": "Social Proof & Community",
                "strategy": "Focuses on community size, past attendee testimonials, and FOMO",
                "subject": "10,000+ Developers Are Already Saying Yes to [Event Name] – Are You?",
                "preheader": "Join the community | Past attendees rave about it | Early bird opens soon",
                "body": """Hi {{first_name}},

[Event Name] 2026 is happening [Dates] in [City] – and the OSS community is buzzing about it.

Here's what past attendees say:

⭐⭐⭐⭐⭐ "Career-changing. Period." – [Company]
⭐⭐⭐⭐⭐ "Made connections that led to my next job offer." – [Company]
⭐⭐⭐⭐⭐ "Implemented what I learned and reduced deployment time by 40%." – [Company]

10,000+ developers from companies like yours will be there. The hallway track alone is legendary.

📍 [City] | 📅 [Dates]

🎯 What to expect:
• 200+ sessions from real practitioners solving real problems
• Hands-on workshops with cutting-edge open source tools
• Direct access to project maintainers and thought leaders
• Networking events and community gatherings
• Group discounts for teams

Early bird registration opens [Date] – save $300 when you register first.

[Get Early Notification →]

The Linux Foundation Events Team

P.S. If you're building with cloud native technologies, you can't miss this.""",
            },
        ]
    },

    "CFP Launch": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Call for Proposals",
                "strategy": "Standard CFP announcement",
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
        ]
    },

    "Registration Launch": {
        "variants": [
            {
                "id": "v1_discount_focused",
                "label": "Discount & Savings Focus",
                "strategy": "Leads with price, percentage savings, and limited-time urgency",
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
            {
                "id": "v2_value_focused",
                "label": "ROI & Value Focus",
                "strategy": "Emphasizes what attendees get (content, networking, takeaways)",
                "subject": "Registration Open: Your All-Access Pass to [Event Name]",
                "preheader": "200+ sessions | 10,000+ peers | 50+ hands-on workshops | All included",
                "body": """Hi {{first_name}},

Registration for [Event Name] is officially OPEN.

Here's everything included in your pass:

📚 CONTENT & LEARNING
✓ 200+ sessions from industry practitioners
✓ 50+ hands-on workshops (beginner to advanced)
✓ 30+ lightning talks & quick hits
✓ 15+ Birds of a Feather (BoF) sessions led by community
✓ Post-event access to all recordings

🤝 NETWORKING & COMMUNITY
✓ Welcome reception & daily networking events
✓ Sponsor showcase with 100+ exhibitors & demos
✓ Meet-ups organized by interest/technology
✓ Direct access to maintainers and thought leaders
✓ 10,000+ peers from companies you know

🎤 FEATURED SPEAKERS
✓ [Keynote Speaker 1] – [Company]
✓ [Keynote Speaker 2] – [Company]
✓ [Keynote Speaker 3] – [Company]

🍔 LOGISTICS
✓ All meals during conference (breakfast, lunch, snacks)
✓ Event app for networking and schedule coordination
✓ Venue access including co-located events

---

EARLY BIRD SPECIAL: Save $300 when you register by [Date]
Regular: $1,299 | Early Bird: $999

[Register Now →]

The Linux Foundation Events Team""",
            },
            {
                "id": "v3_social_proof",
                "label": "Community & Social Proof",
                "strategy": "Focuses on attendee counts, testimonials, and community momentum",
                "subject": "Join 10,000+ Peers at [Event Name] – Registration Now Open",
                "preheader": "5,000+ already registered | Past attendees rave | Early bird pricing ends [Date]",
                "body": """Hi {{first_name}},

Registration for [Event Name] is LIVE – and people are already signing up.

5,000+ developers from companies like Amazon, Google, Meta, and startups are confirmed.

Here's why they're coming:

💬 "Best conference for cloud native – the hallway track alone is worth it." – Past Attendee
💬 "I implemented what I learned and reduced deployment time by 40%." – Past Attendee
💬 "Made connections that led to incredible opportunities." – Past Attendee

📍 [City] | 📅 [Dates]

WHAT YOU GET:
✓ Access to 200+ sessions across all your interests
✓ Hands-on workshops with cutting-edge tools
✓ Face-to-face time with project maintainers
✓ All meals, receptions, and networking events
✓ 100+ exhibitors showcasing the latest in open source
✓ Lifetime access to session recordings

EARLY BIRD ENDS [DATE] — Save $300
Don't wait. Spots are filling fast.

[Register Now →]

👥 Bringing your team? Group discounts available (5+).

The Linux Foundation Events Team

P.S. This is a must-attend event for anyone working with cloud native and open source technologies.""",
            },
        ]
    },

    "Co-Located Events + CFP Reminder": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Co-Located Events Announcement",
                "strategy": "Standard announcement of co-located events",
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
        ]
    },

    "DEI & Travel Fund": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Scholarships & Travel Fund",
                "strategy": "Standard announcement of financial support",
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
        ]
    },

    "Schedule Announcement": {
        "variants": [
            {
                "id": "v1_keynote_focused",
                "label": "Keynote & Speaker Focus",
                "strategy": "Highlights celebrity speakers and headliners",
                "subject": "🌟 The Keynotes Are Here – Meet [Event Name]'s Lineup",
                "preheader": "3 legendary speakers | Track 12+ topics | Early bird ends soon",
                "body": """Hi {{first_name}},

The moment you've been waiting for – the [Event Name] speaker lineup is here!

🎤 KEYNOTE SPEAKERS ANNOUNCED:

• [Speaker 1], [Title] at [Company]
  Expert on: [Topic] | Known for: [Achievement]

• [Speaker 2], [Title] at [Company]
  Expert on: [Topic] | Known for: [Achievement]

• [Speaker 3], [Title] at [Company]
  Expert on: [Topic] | Known for: [Achievement]

---

THEY'LL BE COVERING:
• Cloud native architecture & Kubernetes at scale
• AI/ML in open source (LLMs, training, deployment)
• Security & supply chain best practices
• Platform engineering & developer experience
• Open source culture & sustainability

Plus 190+ other sessions from industry leaders.

🗓️ THE FULL SCHEDULE IS LIVE
200+ sessions across 12 tracks | 50+ workshops | 30+ lightning talks

[Explore the Schedule →] [Create Your Agenda →]

⏰ REMINDER: Early bird pricing ends [Date]
Lock in your $300 savings and attend these keynotes live.

[Register Now →]

The Linux Foundation Events Team

P.S. Can't pick? Use the schedule builder to plan your personalized agenda.""",
            },
            {
                "id": "v2_session_focused",
                "label": "Session Variety & Content Focus",
                "strategy": "Emphasizes breadth of topics and hands-on workshops",
                "subject": "The Schedule is LIVE – 200+ Sessions Awaiting You",
                "preheader": "12 tracks | 50+ workshops | 200+ sessions | Build your agenda",
                "body": """Hi {{first_name}},

The [Event Name] schedule is officially LIVE – and there are 200+ reasons to clear your calendar.

📊 BY THE NUMBERS:
• 200+ sessions across 12 tracks
• 50+ hands-on workshops (intro to advanced)
• 30+ lightning talks
• 15+ Birds of a Feather sessions
• 3 days of non-stop learning

🎯 TRACK HIGHLIGHTS:

CLOUD NATIVE & KUBERNETES
✓ Scaling Kubernetes in production
✓ Cost optimization & FinOps
✓ Platform engineering patterns
✓ GitOps & deployment strategies

AI/ML IN OPEN SOURCE
✓ Building LLMs at scale
✓ Fine-tuning & inference optimization
✓ Vector databases & RAG systems
✓ MLOps best practices

SECURITY & SUPPLY CHAIN
✓ Zero-trust architecture
✓ SBOM generation & management
✓ Vulnerability scanning & remediation
✓ Secrets management

PLATFORM ENGINEERING
✓ Developer experience (DX) patterns
✓ Internal developer platforms (IDPs)
✓ CI/CD optimization
✓ Observability & monitoring

---

🛠️ HANDS-ON WORKSHOPS
Want to get your hands dirty? Choose from 50+ workshops where you'll learn by doing.

[Browse the Full Schedule →] [Create Your Agenda →]

💡 Pro tip: Use the schedule builder to mark sessions and create your personalized itinerary.

Early bird ends [Date] – lock in $300 in savings.

[Register Now →]

The Linux Foundation Events Team""",
            },
            {
                "id": "v3_networking_focused",
                "label": "Networking & Community Focus",
                "strategy": "Emphasizes connections, community events, and hallway track",
                "subject": "The Schedule Reveals What Happens When 10,000 Developers Gather",
                "preheader": "200+ sessions | Networking events | Meet your peers | The hallway track",
                "body": """Hi {{first_name}},

The [Event Name] schedule is here – and it's about more than just sessions.

🤝 THE HALLWAY TRACK IS LEGENDARY

Past attendees say:
💬 "The conversations I had between sessions changed my career."
💬 "I made 5 connections that led to new business opportunities."
💬 "The open source community gathering is incredibly energizing."

This year's schedule includes dedicated networking moments:
• Welcome reception (meet your peers right away)
• Sponsor showcase & hands-on demos (talk with leaders in the field)
• Track-specific meet-ups (connect with people working on your technologies)
• Daily networking breakfasts & evening receptions
• Birds of a Feather sessions (community-led discussions on niche topics)

📚 PLUS 200+ SESSIONS

You'll have both structured learning AND unstructured time to connect.

Session Tracks:
✓ Cloud native, AI/ML, security, platform engineering
✓ Hands-on workshops at every level
✓ Keynotes from industry leaders
✓ Lightning talks & quick wins
✓ Community perspectives

---

[Browse the Schedule →] [Create Your Personalized Agenda →]

The best part? You'll walk away with both new skills AND new connections.

Early bird ends [Date] – save $300 and secure your spot.

[Register Now →]

The Linux Foundation Events Team

P.S. Bringing your team? Use the schedule to coordinate which sessions you'll each attend.""",
            },
        ]
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
        "variants": [
            {
                "id": "v1_fomo_urgency",
                "label": "FOMO & Fear-Based Urgency",
                "strategy": "Emphasizes what you'll miss if you don't attend (FOMO angle)",
                "subject": "🚨 Final Call: Registration Closes in 48 Hours",
                "preheader": "Online registration ends [Date] | Limited onsite availability | Act now",
                "body": """Hi {{first_name}},

[Event Name] registration closes in 48 HOURS.

After [Date], online registration closes and only limited onsite walk-up availability remains.

[Register Now – Before It's Too Late →]

---

HERE'S WHAT YOU'LL MISS IF YOU DON'T REGISTER:

❌ 200+ sessions from industry leaders (won't get to watch them live)
❌ Hands-on workshops with cutting-edge OSS tools (limited onsite spots)
❌ Face-to-face networking with 10,000+ peers (your competition will be there)
❌ The energy and inspiration of the open source community
❌ Career opportunities and connections that could define your next move

The hallway track alone changes careers. You'll regret missing it.

---

⭐⭐⭐⭐⭐ "Career-changing. Period." – Past attendee
⭐⭐⭐⭐⭐ "Best investment I made for my career this year." – Past attendee

This is your last chance.

[Register Now →]

The Linux Foundation Events Team

P.S. No more early bird pricing after [Date]. Your window is closing.""",
            },
            {
                "id": "v2_last_chance",
                "label": "Last Chance & One More Thing",
                "strategy": "Friendly reminder without aggressive tone, emphasizes 'one more chance'",
                "subject": "One More Thing – Registration Ends Tomorrow",
                "preheader": "48 hours left | Online registration closes [Date] | Don't miss it",
                "body": """Hi {{first_name}},

Just a friendly reminder: registration for [Event Name] ends tomorrow ([Date]).

This is genuinely your last chance to register online. After tomorrow, only limited walk-up availability remains.

---

IF YOU'VE BEEN ON THE FENCE, HERE'S WHY NOW IS THE TIME:

📍 [City] | 📅 [Dates]

✓ 200+ sessions on the topics you care about
✓ 50+ hands-on workshops (try new tools, learn from experts)
✓ Networking with 10,000+ people working on open source
✓ Meet project maintainers and thought leaders face-to-face
✓ All meals, receptions, and networking events included
✓ Post-event access to all session recordings

BRINGING YOUR TEAM?
Group discounts (5+) are still available – buy today before the cutoff.

---

[Register Now →]

Questions? Check the FAQ or reach out to events@linuxfoundation.org

The Linux Foundation Events Team

P.S. Early bird pricing ends tonight. Regular pricing starts tomorrow.""",
            },
            {
                "id": "v3_social_proof_testimonial",
                "label": "Social Proof & Testimonials",
                "strategy": "Leads with past attendee success stories and proof of value",
                "subject": "48 Hours Left – See Why Thousands Are Attending [Event Name]",
                "preheader": "5,000+ already registered | Hear from past attendees | Last call",
                "body": """Hi {{first_name}},

5,000+ people have already registered for [Event Name]. You're so close to being part of this.

[Dates] in [City] — registration closes TOMORROW.

---

HERE'S WHAT PAST ATTENDEES SAY:

💬 "Career-changing. Period." – [Title], [Company]
"I came to learn about cloud native. I left with a job offer from a company I met in the hallway."

💬 "The best investment I made for my career this year." – [Title], [Company]
"The connections I made directly led to us hiring world-class engineers from the community."

💬 "I implemented what I learned and reduced our deployment time by 40%." – [Title], [Company]
"The hands-on workshops were incredible. Went back and changed how we ship code."

💬 "The energy and inspiration can't be replicated online." – [Title], [Company]
"Being around 10,000 people passionate about open source is energizing. You have to experience it live."

---

YOU'LL GET:
✓ 200+ sessions and hands-on workshops
✓ Access to the speakers, maintainers, and leaders you normally only read about
✓ Connections with peers solving the same problems
✓ Inspiration and energy to tackle new challenges
✓ Lifetime access to recordings (but it's not the same as being there)

[Register Now – Last Chance →]

The Linux Foundation Events Team

P.S. If you're working with cloud native, Kubernetes, AI/ML, or security – this event is for you.""",
            },
        ]
    },

    "Event Week": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Day 1 Welcome Guide",
                "strategy": "Standard welcome and logistics for first day",
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
        ]
    },

    "Thank You + Survey": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Post-Event Thank You",
                "strategy": "Standard post-event thank you and survey request",
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
        ]
    },

    "Content & Recordings Release": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Recordings Release",
                "strategy": "Standard announcement of session recordings",
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
        ]
    },

    "Next Event CFP Teaser": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Next Year Teaser",
                "strategy": "Standard teaser for next year's event",
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
        ]
    },

    "Community Nurture": {
        "variants": [
            {
                "id": "v1_main",
                "label": "Community Update",
                "strategy": "Standard monthly community update",
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
        ]
    },
}

# ── Best Practice Templates (B2B Event Marketing) ────────────────────────────
# Derived from ArgoCon + KeycloakCon analysis (proven high-conversion templates)
# These are reference templates showing what works in real campaigns

BEST_PRACTICE_TEMPLATES = {
    "B2B_Event_Announcement": {
        "source": "ArgoCon + KeycloakCon Japan 2026",
        "quality_rating": 5,  # Out of 5
        "conversion_type": "announcement",
        "sender_profile": "Sr. Global Event Partnerships Manager",
        "key_metrics": {"expected_open_rate": 0.45, "expected_ctr": 0.12},
        "template": {
            "id": "b2b_announcement",
            "label": "B2B Event Announcement (ArgoCon Template)",
            "strategy": "Build excitement + relationship focus + multiple CTAs",
            "subject": "[Event Name] + [Co-Location] - [Key Achievement]!",
            "preheader": "[Number]+ attendees | [City] | [Date] | Schedule live",
            "body": """Hi [PERSONALIZATION: names],

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

P.S. [Humanizing element: personal note, travel info, availability]"""
        }
    },

    "B2B_Speaker_Conversion": {
        "source": "ArgoCon Speaker Confirmations (Pooja Dhir)",
        "quality_rating": 5,
        "conversion_type": "speaker_to_sponsor",
        "sender_profile": "Event Partnerships Associate",
        "key_metrics": {"expected_open_rate": 0.52, "expected_ctr": 0.18},
        "template": {
            "id": "b2b_speaker_conversion",
            "label": "B2B Speaker Conversion (ArgoCon Template)",
            "strategy": "Congratulate first, convert second - achievement focus",
            "subject": "Congratulations on [Company]'s Speaking Slot at [Event]!",
            "preheader": "Speaking slot confirmed | Maximize visibility | Sponsorship opportunity",
            "body": """Hi [SPEAKER_NAME],

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
[Phone] | [Website] | [Calendar]"""
        }
    },

    "B2B_Strategic_Close": {
        "source": "ArgoCon Strategic Opportunities (Nicole Puopolo)",
        "quality_rating": 5,
        "conversion_type": "complex_multi_event_deal",
        "sender_profile": "Sr. Global Event Partnerships Manager",
        "key_metrics": {"expected_open_rate": 0.48, "expected_ctr": 0.14},
        "template": {
            "id": "b2b_strategic_close",
            "label": "B2B Strategic Multi-Event Close (ArgoCon Template)",
            "strategy": "Comprehensive context + transparent pricing + urgency + multiple options",
            "subject": "[Event List] - Ready for a contract?",
            "preheader": "Multiple sponsorship opportunities | Limited spots | [Deadline]",
            "body": """Hi [ACCOUNT_NAME],

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

P.S. I'll be in [CITY] [DATE] - happy to meet in person if helpful."""
        }
    },

    "B2B_Rapid_Close": {
        "source": "ArgoCon Quick Closes (Pooja Dhir)",
        "quality_rating": 4,
        "conversion_type": "existing_account_contract",
        "sender_profile": "Event Partnerships Associate",
        "key_metrics": {"expected_open_rate": 0.35, "expected_ctr": 0.22},
        "template": {
            "id": "b2b_rapid_close",
            "label": "B2B Rapid Close - Existing Accounts (ArgoCon Template)",
            "strategy": "Minimal friction - assumes context, fast to contract",
            "subject": "[Company] [Tier] Sponsorship for [Event]",
            "preheader": "Contract ready | Quick turnaround | [Tier] included",
            "body": """Hi [CONTACT_NAME],

I'm looping in our Event Sales Ops team to send your [TIER] sponsorship contract for [Event Name].

They'll handle next steps. Any questions, let me know!

[Sender name]
[Title]
[Phone] | [Calendar link]"""
        }
    },

    "B2B_Registration_Launch": {
        "source": "ArgoCon Registration/CFP Launch",
        "quality_rating": 4,
        "conversion_type": "registration_and_sponsorship",
        "sender_profile": "Sr. Global Event Partnerships Manager",
        "key_metrics": {"expected_open_rate": 0.40, "expected_ctr": 0.10},
        "template": {
            "id": "b2b_registration_launch",
            "label": "B2B Registration/CFP Launch (ArgoCon Template)",
            "strategy": "Conversational + deadline-driven + information dense",
            "subject": "[Event Name] - Deadline [DATE]",
            "preheader": "Registration open | Schedule announced | Deadline approaching",
            "body": """Hi [CONTACT_NAME],

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

P.S. [Personal element: travel info, availability]"""
        }
    }
}


def get_best_practice_template(template_key: str) -> dict | None:
    """Return a best-practice B2B template by key."""
    return BEST_PRACTICE_TEMPLATES.get(template_key)


def get_all_best_practice_templates() -> dict:
    """Return all best-practice templates with metadata."""
    return BEST_PRACTICE_TEMPLATES


def recommend_best_practice_template(campaign_type: str) -> dict | None:
    """
    Recommend the best template based on campaign type.

    Types: announcement, speaker_conversion, multi_event_deal,
           existing_account_close, registration_launch
    """
    recommendations = {
        "announcement": "B2B_Event_Announcement",
        "speaker_conversion": "B2B_Speaker_Conversion",
        "multi_event_deal": "B2B_Strategic_Close",
        "existing_account_close": "B2B_Rapid_Close",
        "registration_launch": "B2B_Registration_Launch",
    }

    key = recommendations.get(campaign_type)
    if key:
        template = BEST_PRACTICE_TEMPLATES.get(key)
        return {
            "key": key,
            "template": template,
            "quality_rating": template.get("quality_rating") if template else 0,
            "source": template.get("source") if template else None
        }
    return None


def get_template(stage_name: str, variant_id: str | None = None) -> dict | None:
    """
    Return the template dict for a given stage name and optional variant_id.
    If variant_id is None, returns the first variant.
    Returns None if stage or variant not found.
    Backward compatible: returns first variant by default.
    """
    stage = STAGE_TEMPLATES.get(stage_name)
    if not stage:
        return None

    variants = stage.get("variants", [])
    if not variants:
        return None

    if variant_id is None:
        return variants[0]

    for variant in variants:
        if variant.get("id") == variant_id:
            return variant

    return None


def get_template_variants(stage_name: str) -> list[dict] | None:
    """Return all variant templates for a given stage name, or None if stage not found."""
    stage = STAGE_TEMPLATES.get(stage_name)
    return stage.get("variants") if stage else None


def get_template_variant(stage_name: str, variant_id: str) -> dict | None:
    """Return a specific template variant by stage name and variant_id, or None if not found."""
    variants = get_template_variants(stage_name)
    if not variants:
        return None

    for variant in variants:
        if variant.get("id") == variant_id:
            return variant

    return None


def list_variant_strategies(stage_name: str) -> list[dict] | None:
    """
    Return metadata for all variants in a stage (for agent guidance).
    Returns list of {id, label, strategy} dicts, or None if stage not found.
    """
    variants = get_template_variants(stage_name)
    if not variants:
        return None

    return [
        {
            "id": v.get("id"),
            "label": v.get("label"),
            "strategy": v.get("strategy"),
        }
        for v in variants
    ]


def get_all_stage_names() -> list[str]:
    return list(STAGE_TEMPLATES.keys())
