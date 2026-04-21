# Banner Configuration Guide

Step-by-step instructions for creating and configuring Intercom outbound banners via browser automation.

## Standard Banner Settings

These are the default settings for LF event promotion banners:

| Setting | Default Value |
|---|---|
| Banner style | Floating |
| Position | Top |
| Show sender | Off (disabled) |
| Show dismiss button | On (enabled) |
| Action type | Open a URL (button) |
| Button text | "Register Now" |
| Audience | Visitors, Leads, and Users (all three) |
| Frequency | Send every time the person matches the rules |
| Scheduling | Start sending immediately, Never stop sending, Any day any time |

## UTM URL Structure

Every banner's CTA URL must include UTM parameters for attribution tracking:

```
https://events.linuxfoundation.org/[event-slug]/register/?utm_source=[source]&utm_medium=ribbon-banner&utm_campaign=[Campaign-Name]&utm_content=hero
```

### Parameter Definitions

| Parameter | Value | Description |
|---|---|---|
| utm_source | Domain-specific (see domains.md) | Identifies which LF property drove the click |
| utm_medium | `ribbon-banner` | Always "ribbon-banner" for Intercom banners |
| utm_campaign | Event name with hyphens | e.g., `Open-Source-Summit-NA-2026` |
| utm_content | `hero` | Standard value for top-of-page banner placement |

## Browser Automation: Creating a New Banner

### Navigate to Banner Creator
1. Go to `https://app.intercom.com/a/apps/{workspaceId}/outbound`
2. Click the **"New message"** button (top right area, or use the + button)
3. Select **"Banner"** from the message type options

### Configure Content
4. Click the banner title area at the top and type the banner name: `[Event Name] - [Domain Short Name] Banner`
   - Example: "Open Source Summit NA 2026 - EasyCLA Banner"
5. Click on the banner text area in the preview and type the promotional message
   - Standard format: `Join us in [City] for [Event Name] * [Dates] *`
6. Under "What action should be taken?", select **"Open a URL"**
7. Select **"Via a button"** for the action delivery method
8. Set button text to **"Register Now"**
9. Paste the full UTM-tagged URL in the URL field

### Configure Style
10. Scroll to banner style settings
11. Select **"Floating"** (not Inline)
12. Select **"Top"** position
13. Toggle **"Show the sender"** to **Off**
14. Toggle **"Show a dismiss button"** to **On**

### Configure Rules (URL Targeting)
15. Scroll down to the **"Rules"** section
16. Under **"Where to send"**, click **"Add page rule"**
17. From the dropdown, click **"Add a URL rule"**
18. In the rule configuration dialog, select **"contains"** from the radio button list
19. In the text input field, type the target domain (e.g., `easycla.lfx.linuxfoundation.org`)
20. Click **"Done"** to save the URL rule

### Configure Audience
21. In the **"Audience"** section, click the current audience chip (usually shows "Users")
22. A dropdown appears with three options: Visitors, Leads, Users
23. Click **"Visitors"** to add it (checkmark appears)
24. Click **"Leads"** to add it (checkmark appears)
25. Verify all three show checkmarks: Visitors, Leads, Users
26. The chip should now read **"Visitors, Leads, and Users"**
27. Click outside the dropdown to close it

### Set Live
28. Scroll to the top of the page
29. Click the **"Set live"** button (top right corner)
30. A confirmation dialog appears: "Ready to set your banner live?"
31. Click **"Set live"** in the confirmation dialog
32. Verify the banner status changes to show a green **"Live"** badge

## Banner Naming Convention

Use this pattern for banner titles in Intercom:
```
[Event Name] [Year] - [Domain/Product] Banner
```

Examples:
- "Open Source Summit NA 2026 - Mentorship Banner"
- "Open Source Summit NA 2026 - EasyCLA Banner"
- "KubeCon EU 2025 - PCC Banner"

## Verifying a Banner is Working

After setting a banner live:
1. Open the target domain in an **incognito/private browser window** (important — your own session may have a dismissed state)
2. Wait 3-5 seconds for the Intercom messenger to initialize
3. The banner should appear at the top of the page (for Floating/Top style)
4. Click the CTA button and verify the registration page loads with correct UTM parameters in the URL

## Troubleshooting

### Banner not showing for the user who created it
This is the most common issue. Intercom tracks dismissals server-side. If the user (or their Intercom identity) previously dismissed any banner on that domain, new banners won't show. Solutions:
- Test in incognito/private window
- Create a "Version 2" of the banner with slightly different text to reset dismissal tracking

### Banner not showing for anyone
Check these in order:
1. Is the banner status "Live"? (not Draft or Paused)
2. Is the URL rule correct? (domain name must match exactly)
3. Are all three audience types selected?
4. Is Intercom's messenger actually installed on the target domain?
5. Is there a scheduling restriction limiting when it shows?

### Multiple banners on the same domain
Intercom can show multiple banners, but it may only show one at a time. If an older banner exists for the same domain, consider pausing it before setting the new one live.
