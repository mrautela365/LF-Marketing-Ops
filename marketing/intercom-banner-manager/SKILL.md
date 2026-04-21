---
name: intercom-banner-manager
description: >
  Create, configure, audit, and manage Intercom outbound banners for Linux Foundation event promotions
  across LFX domains. Use this skill whenever someone asks to place banners, create promotional ribbons,
  add event announcements, manage Intercom outbound messages, audit which domains have Intercom enabled,
  or promote LF events (Open Source Summit, KubeCon, etc.) across LFX and Linux Foundation web properties.
  Also trigger when someone mentions "Intercom banners", "ribbon banners", "outbound banners",
  "promotional banners on LFX", "event banners", or asks to check which domains have banners deployed.
---

# Intercom Banner Manager for Linux Foundation Events

You manage Intercom outbound banners that promote Linux Foundation events across LFX and linuxfoundation.org web properties. This involves creating banners in the Intercom workspace, configuring URL targeting rules, setting audience types, generating UTM-tagged registration URLs, and auditing the domain inventory.

## Context

The Linux Foundation uses Intercom (workspace ID: `{workspaceId}`) to display promotional floating banners across its web properties. These banners typically promote major events like Open Source Summit, KubeCon, etc. The Intercom admin panel is at `https://app.intercom.com/a/apps/{workspaceId}`.

Banners are managed under **Outbound > Banners** in Intercom. Each banner targets a specific domain via URL rules and is shown to Visitors, Leads, and Users.

## Before You Start

Read the reference files to understand the full domain inventory and configuration conventions:
- `references/domains.md` — Complete list of Intercom-enabled domains with their utm_source values
- `references/banner-config.md` — Standard banner configuration, UTM structure, and step-by-step browser automation instructions

## Step 1: Gather Requirements

Before creating any banners, confirm with the user:

1. **Which event?** (e.g., Open Source Summit NA 2026, KubeCon EU 2025)
2. **Banner text** — The promotional message. Standard format: "Join us in [City] for [Event Name] * [Dates] *"
3. **CTA button text** — Usually "Register Now"
4. **Registration URL** — The base event registration URL (before UTM parameters)
5. **Which domains?** — All domains, a subset, or a specific new domain?
6. **Banner style** — Floating/Top is the standard. Inline/Bottom or Inline/Top are alternatives.

If the user has already provided this information in the conversation, don't ask again — just confirm and proceed.

## Step 2: Generate UTM-Tagged URLs

For each target domain, construct the registration URL with these UTM parameters:

```
[base_registration_url]?utm_source=[domain-specific]&utm_medium=ribbon-banner&utm_campaign=[Event-Campaign-Name]&utm_content=hero
```

The `utm_source` value is unique per domain — see `references/domains.md` for the mapping. The `utm_campaign` follows the pattern: `Event-Name-Region-Year` with hyphens (e.g., `Open-Source-Summit-NA-2026`).

## Step 3: Create Banners in Intercom

For each domain, create a new outbound banner via browser automation:

1. Navigate to `https://app.intercom.com/a/apps/{workspaceId}/outbound` and click **New message > Banner**
2. Configure the banner content (text, CTA button, URL)
3. Set banner style (Floating/Top is default) and enable dismiss button
4. Disable "Show the sender" — these are org-level announcements
5. Add URL targeting rule: **Current page URL contains [domain]**
6. Set audience to **Visitors, Leads, and Users** (all three for maximum visibility)
7. Verify frequency: "Send every time the person matches the rules"
8. Set the banner live

See `references/banner-config.md` for detailed browser automation steps.

## Step 4: Domain Audit (when requested)

When the user asks to audit or list Intercom-enabled domains:

1. Navigate to `https://app.intercom.com/a/apps/{workspaceId}/outbound`
2. Filter by Banners (and optionally Posts/Workflows)
3. Open each outbound message and check the URL targeting rule under "Where to send"
4. Compile a complete list of domains with their associated message IDs and types
5. Cross-reference against the known domain inventory in `references/domains.md`
6. Report any new domains not in the reference file, or domains that are missing banners

## Important Behaviors

### Banner Dismissal Tracking
Intercom tracks banner dismissals server-side, tied to the visitor's identity. Once someone dismisses a banner, they won't see it again — even if they clear cookies or switch browsers. This means:
- If the user reports they can't see a banner they just created, suggest testing in an **incognito/private window**
- For long-running campaigns, consider a **version rotation strategy**: duplicate the banner as "Version 2" with slightly modified text to reset dismissal state for everyone

### Audience Types — Always Add All Three
Intercom has three audience types. Banners should target **all three** for maximum visibility:
- **Visitors** — Anyone browsing who isn't logged in and has no conversation history
- **Leads** — Anyone who has started a conversation or replied to an outbound message
- **Users** — Anyone who has signed up or logged into the product

### Domains Managed Outside Intercom
Some LF properties use different banner systems:
- **linuxfoundation.org** — Uses a native HubSpot CMS banner (your HubSpot portal), not Intercom
- **training.linuxfoundation.org** and **trainingportal.linuxfoundation.org** — Managed by the LF Training team; provide them with UTM-tagged URLs

### Permission Restrictions
Some Intercom features may be restricted depending on the user's role:
- **Messenger settings** — Requires "Can manage Messenger settings" permission
- **Contacts section** — Requires "Can access people, companies, and account lists"
- These restrictions don't affect banner creation, which only requires outbound message permissions

## Output Format

After completing banner work, always provide a summary table:

```
| Banner Name | ID | Domain | Style | utm_source | Status |
|---|---|---|---|---|---|
| [Event] - [Domain] Banner | [ID] | [domain] | Floating/Top | [source] | Live |
```

Include the direct Intercom link for each banner: `https://app.intercom.com/a/apps/{workspaceId}/outbound/banners/[ID]`
