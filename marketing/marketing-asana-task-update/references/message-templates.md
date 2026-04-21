# Message Templates for Asana Comments

Templates for common Marketing Ops communication scenarios. Claude reads this file when
drafting messages in Phase 9 to pick the right tone and format.

## Task Completed — Segment Delivery

```
Hi [Requester],

Your segment is ready:
- List name: [List Name]
- Contact count: [Count]
- Filters applied: [Brief filter description]
- HubSpot list ID: [ID]

You can find it in HubSpot under Contacts > Lists > [List Name].
Let us know if you need any changes.

— Marketing Ops
```

## Task Completed — Email Campaign Setup

```
Hi [Requester],

The email is set up and ready for your review:
- Email name: [Name]
- Audience: [List name] ([Count] contacts)
- Scheduled send: [Date/Time] (or "Draft — awaiting your approval")
- Subject line: [Subject]

Please review in HubSpot and confirm we're good to send.

— Marketing Ops
```

## Task Completed — List Pull / Data Export

```
Hi [Requester],

The list pull is complete:
- Criteria: [Brief description of filters]
- Total contacts: [Count]
- Exported to: [Location or format]

Let us know if you need the data sliced differently.

— Marketing Ops
```

## Task Completed — Report / Analysis

```
Hi [Requester],

Here's the analysis you requested:
- [Key finding 1]
- [Key finding 2]
- [Key finding 3]

Full details are [attached / in the linked document / summarized below].
Happy to dig deeper into any of these if needed.

— Marketing Ops
```

## Need More Information — Missing Parameters

```
Hi [Requester],

We're working on this but need a few details to proceed:

1. [Specific question — e.g., "What date range should we use for the list pull?"]
2. [Specific question — e.g., "Should we include contacts from all regions or just NA?"]

Once you confirm, we'll get this wrapped up.

— Marketing Ops
```

## Need More Information — Ambiguous Request

```
Hi [Requester],

Want to make sure we get this right. The request mentions [ambiguous element] —
could you clarify:

- [Option A interpretation] — is this what you mean?
- [Option B interpretation] — or this?

Just want to confirm before we build it out.

— Marketing Ops
```

## Need More Information — Blocked by External Dependency

```
Hi [Requester],

We're ready to execute on this, but we're waiting on:
- [External dependency — e.g., "The custom property 'Project Name' hasn't been created in HubSpot yet"]

Can you check with [relevant person/team] or let us know if there's a workaround?

— Marketing Ops
```

## Task Update — In Progress

```
Hi [Requester],

Quick update — we're actively working on this:
- Done: [Completed step]
- In progress: [Current step]
- Up next: [Upcoming step]

ETA: [Date or "end of day"]. We'll update you when it's done.

— Marketing Ops
```

## Task Update — Partial Completion

```
Hi [Requester],

We've completed part of this request:
- Done: [What's done]
- Remaining: [What's left and why]

We'll follow up once the rest is wrapped up. Let us know if the completed
portion is urgent and you want to use it now.

— Marketing Ops
```
