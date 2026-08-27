package aiemailtemplates

// AIVariantStyleRules ports AI_VARIANT_STYLE_RULES verbatim. Applies ONLY to
// the "AI Template" variant generators (generate_ai_template_content in
// core/agent.py and generate_email_content in generate_ai_content.py). Does
// NOT apply to Variant B (reference-driven) or the pre-written
// messaging-variant strategies in emailtemplates.
const AIVariantStyleRules = `━━━ MANDATORY STYLE RULES — AI TEMPLATE VARIANT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
   Prefer bullets (<ul><li>) over paragraphs for any list of 2+ items. Put the
   highest-value message before the first CTA. Cut repetition. Every paragraph
   should do exactly one job: build urgency, build desire, build credibility,
   remove hesitation, or drive the CTA — if it does none of those, remove it.
   A reader who only scans the bold text, headings, CTA buttons, and links for
   10-20 seconds must still walk away understanding the offer, the urgency, and
   the action to take.
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
14. VISUAL HIERARCHY AND FORMATTING — apply this EVERY SECTION, not just the
    opening hook and closing paragraph. A reader who only skims the bold
    words, links, and headings across the ENTIRE email (top to bottom) must
    still get the full offer, urgency, and proof, not just the framing.
    - EVERY section (hook, each supporting/detail section, and the closing
      paragraph) must contain at least one bolded <strong> phrase: the
      section's own key fact or benefit (a price, a deadline, a speaker/
      company name, a concrete outcome, a real inclusion). Do not concentrate
      all bolding in only the hook and the final paragraph and leave the
      middle sections plain. Keep bolding to short phrases (roughly 10-15% of
      that section's text, never a whole sentence or paragraph) so it still
      stands out.
    - Use an inline colored <span style="color:#XXXXXX"> in more than one
      section, not just once in the whole email, wherever it meaningfully
      increases emphasis (a deadline, a savings amount, an urgent notice, a
      scarcity fact) — still selectively, not on every sentence.
    - Include a contextual inline hyperlink in MULTIPLE sections (not just one
      or two total), e.g. "View the Agenda", "Meet the Speakers", "CFP
      Guidelines", "Travel Information", "Registration Details" alongside
      whichever section naturally supports it. Use descriptive link text,
      never "click here". Only link to a URL that is actually given above
      (the matching event link, or the main event page as fallback) — never
      invent a URL or a sub-page that wasn't provided.
    - Give each supporting section a short, clear bolded lead-in line rather
      than running straight from one paragraph into the next with no visual
      break — every section gets one, not just some.
    - Vary sentence length for a natural reading rhythm — avoid a string of
      same-length, same-structure sentences in a row.
    - Use generous whitespace between blocks; avoid dense, unbroken walls of
      text.
    - Overall visual flow should move: greeting/hook -> urgency -> benefits ->
      primary CTA -> supporting proof (audience/speakers/credibility) -> final
      CTA — so the structure itself, not just the words, guides the eye toward
      the action, and each stop along that flow carries its own visual
      emphasis rather than only the first and last stops.

Final bar: the output should read like it was written by an experienced
lifecycle-marketing team optimizing for conversions, while remaining factually
accurate and Linux-Foundation-professional, never manipulative or invented.
`
