# Intercom-Enabled Domains — Linux Foundation

This is the complete inventory of domains where Intercom is enabled, along with their standard `utm_source` values for banner campaigns. This list was compiled by scanning all outbound messages in the Intercom workspace.

## Active LFX Domains

| Domain | utm_source | Notes |
|---|---|---|
| mentorship.lfx.dev | lfx-mentorship | LFX Mentorship platform |
| insights.lfx.dev | lfx-insights | LFX Insights / project analytics |
| crowdfunding.lfx.dev | crowdfunding | LFX Crowdfunding |
| projectadmin.lfx.dev | pcc | LFX Project Control Center (PCC) |
| v1.projectadmin.lfx.dev | pcc-v1 | Legacy PCC version |
| myorg.lfx.dev | lfx-orgdash | LFX Organization Dashboard |
| easycla.lfx.linuxfoundation.org | lfx-easycla | EasyCLA Landing Page |
| docs.linuxfoundation.org | lf-docs | LF Documentation site |

## Partner / Sub-Foundation Domains

| Domain | utm_source | Notes |
|---|---|---|
| aaif.io | aaif | AI & Data Forum (formerly LF AI) — banner was SKIPPED per user preference in past campaigns |
| riscv.org | riscv | RISC-V International |

## Support / Help Center Domains

| Domain | utm_source | Notes |
|---|---|---|
| helpcenter.linuxfoundation.org | lf-helpcenter | LF Help Center |

## Test / Non-Production Domains

| Domain | utm_source | Notes |
|---|---|---|
| intercom-test.lfx.dev | — | Engineering test domain — do not deploy banners here |

## Domains NOT Managed via Intercom

These domains have promotional banners but they're managed through other systems:

| Domain | System | Notes |
|---|---|---|
| linuxfoundation.org | HubSpot CMS | Native website banner, managed by LF web team |
| training.linuxfoundation.org | LF Training team | Provide UTM URLs; they update the banner themselves |
| trainingportal.linuxfoundation.org | LF Training team | Same as above |

## UTM Source Naming Convention

When a new domain is added to Intercom that isn't listed above, derive the `utm_source` using this pattern:
- LFX products: `lfx-[product-name]` (e.g., `lfx-mentorship`, `lfx-easycla`)
- LF properties: `lf-[property]` (e.g., `lf-docs`, `lf-helpcenter`)
- External foundations: use the foundation's short name (e.g., `aaif`, `riscv`)
