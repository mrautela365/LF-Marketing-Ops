SEGMENT_PLANNER_PROMPT = """Plan the HubSpot audience segment for this Linux Foundation event:

{url}

Follow the event-segment-planner skill instructions exactly, working through all 4 steps:
1. Scrape the event page — extract event name, brand/foundation, location, dates, event type
2. Find previous edition emails in HubSpot — search for prior sends and check the LF Event \
Audiences Foundation OptIn Report
3. Analyse historical segmentation logic — reconstruct inclusion, exclusion, and opt-in \
filter strategy
4. Produce the full Segment Plan Report in the standard format

Narrate what you are doing at every sub-step.
End with: "Ready to proceed? Say yes and I'll build the segment in HubSpot."
"""
