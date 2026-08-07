# Ambassador Properties

There is no single cross-brand "is_ambassador" flag in HubSpot. Ambassador status is tracked
per-program, as a set of separate contact properties. To build a "community ambassadors only"
filter, OR across every property below (HubSpot's filter model requires the root filterBranch
to stay OR-of-AND — distribute one additional top-level AND branch per property below rather
than nesting an OR inside a branch).

This list is manually maintained — extend it as new ambassador programs are found in HubSpot.

| Program | Property | Type | Best-available "is an ambassador" gate |
|---------|----------|------|------------------------------------------|
| CNCF | `cncf_ambassador___year_ambassador` | enumeration (years 2016-2024) | `HAS_PROPERTY` |
| CNCF | `cncf___past_ambassador` | enumeration (Yes/No) | `IS_EQUAL_TO "No"` for currently-active; `HAS_PROPERTY` for ever-was |
| LF Energy | `lf_energy_ambassador___bio` | text | `HAS_PROPERTY` |
| LF Energy | `lf_energy_ambassador___headshot` | text | `HAS_PROPERTY` (secondary signal) |
| LF Energy | `lf_energy_ambassador___why_do_you_want_to_be_an_ambassador` | text | `HAS_PROPERTY` (secondary signal) |
| Open Mainframe | `open_mainframe_ambassador___bio` | text | `HAS_PROPERTY` |
| Open Mainframe | `open_mainframe_ambassador___project_list` | text | `HAS_PROPERTY` (secondary signal) |

## Notes

- Only CNCF has a distinct "currently active" signal (`cncf___past_ambassador` = "No") versus
  "ever filled out the ambassador form" (`cncf_ambassador___year_ambassador` HAS_PROPERTY). For
  LF Energy and Open Mainframe, there is no such distinction — the bio field is the best
  available proxy for "has ever been an ambassador," since these programs never record an
  explicit past/current status.
- Use one property per program as the primary gate (`HAS_PROPERTY` on the bio-equivalent field
  for LF Energy / Open Mainframe, `HAS_PROPERTY` on `cncf_ambassador___year_ambassador` for
  CNCF) — the "secondary signal" properties exist mainly for reference and don't need their own
  branch unless the primary gate for that program is empty.
