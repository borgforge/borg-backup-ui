# Unified UI design references

Issue [#28](https://github.com/borgforge/borg-backup-ui/issues/28) tracks the
shared foundation for the UI redesign from
[#27](https://github.com/borgforge/borg-backup-ui/issues/27). This directory
records the approved prototype sources and the rules that production code must
preserve when adopting them.

The studies are design guidance. They are not production templates and their
hardcoded sample text must not be copied into the application. Existing routes,
APIs, behavior, localization keys, and the framework-free architecture remain
authoritative.

## Approved references

The visual foundation comes from `jobs-design-study`: color families,
typography, spacing, borders, surfaces, navigation rail, page headers, buttons,
forms, tables, logs, and status treatments. Its A, B, and C page layouts are not
an additional Jobs layout decision.

| Area | Approved study | Selection | Implementation issue | Screenshots |
| --- | --- | --- | --- | --- |
| Dashboard | `dashboard-sidebar-study` | Variant C | [#29](https://github.com/borgforge/borg-backup-ui/issues/29) | [Dark](screenshots/dashboard-dark.png) / [Light](screenshots/dashboard-light.png) |
| Jobs | `jobs-location-study` | `sidebar.html` | [#29](https://github.com/borgforge/borg-backup-ui/issues/29) | [Dark](screenshots/jobs-dark.png) / [Light](screenshots/jobs-light.png) |
| History | `history-sidebar-study` | Single variant | [#30](https://github.com/borgforge/borg-backup-ui/issues/30) | [Dark](screenshots/history-dark.png) / [Light](screenshots/history-light.png) |
| Reports | `reports-job-sidebar-study` | Variant C | [#30](https://github.com/borgforge/borg-backup-ui/issues/30) | [Dark](screenshots/reports-dark.png) / [Light](screenshots/reports-light.png) |
| Restore Tests | `restore-tests-sidebar-study` | Single variant | [#31](https://github.com/borgforge/borg-backup-ui/issues/31) | [Dark](screenshots/restore-tests-dark.png) / [Light](screenshots/restore-tests-light.png) |
| Browse and Restore | `browse-restore-sidebar-study` | Single variant | [#32](https://github.com/borgforge/borg-backup-ui/issues/32) | [Dark](screenshots/browse-restore-dark.png) / [Light](screenshots/browse-restore-light.png) |
| Settings | `settings-sidemenu-study` | Single variant | [#33](https://github.com/borgforge/borg-backup-ui/issues/33) | [Dark](screenshots/settings-dark.png) / [Light](screenshots/settings-light.png) |
| Storage | `storage-study` | Variant A without summary ledger | [#34](https://github.com/borgforge/borg-backup-ui/issues/34) | [Dark](screenshots/storage-variant-a-dark.png) / [Light](screenshots/storage-variant-a-light.png) |

### Storage alternatives

Variant A is approved without the repository summary ledger. Variants B and C
remain archived alternatives. All three retain repository tests, SMB mount
controls, manual Borg check levels, load warnings, and log actions.

| Candidate | Focus | Screenshot |
| --- | --- | --- |
| A (approved) | Location sidebar with repository workspace, without summary ledger | [Dark](screenshots/storage-variant-a-dark.png) / [Light](screenshots/storage-variant-a-light.png) |
| B | Dense location board with persistent check controls | [Dark](screenshots/storage-variant-b-dark.png) / [Light](screenshots/storage-variant-b-light.png) |
| C | Repository inspector with detail and check context | [Dark](screenshots/storage-variant-c-dark.png) / [Light](screenshots/storage-variant-c-light.png) |

Help keeps its existing content in the new visual foundation. A contextual
table-of-contents sidebar may be added where it improves navigation. Rewriting
the standalone handbook is outside this redesign and remains tracked
separately.

## Shared layout rules

German UI terminology uses `Standorte` and `Alle Standorte` for location
navigation and filters. Compact table headers use `Ort`. English uses
`Locations`, `All locations`, and `Location`. Internal API fields and code may
keep the existing `location` identifiers.

Location-grouped navigation uses one fixed order: Local, USB, SMB, Storagebox.
Missing groups are omitted without changing the relative order. The order is
not user-configurable.

- Preserve the existing primary navigation and route structure.
- Use a consistent page header for title, context, and primary actions.
- Use a context sidebar for locations, jobs, settings sections, or help topics
  when the page has a meaningful secondary hierarchy.
- Keep the selected context and the workspace title visibly connected.
- Prefer compact, scannable rows and tables for operational data. Cards are for
  summaries or focused information, not a replacement for dense data views.
- Keep primary actions visible. Put destructive and infrequent actions in a
  clearly labeled secondary menu.
- Contain logs and wide tables within their workspace so they do not expand the
  complete page width.
- Reuse shared primitives instead of page-specific copies: surfaces, headers,
  sidebars, navigation entries, badges, tables, forms, notices, empty states,
  action groups, and log panels.
- Job selection sidebars must render the configured job icon and icon color
  stored in the job metadata, with the backup-type icon only as a fallback.
- Location sidebars must reuse the Local, USB, SMB, and Storagebox SVG icons
  from the existing Storage page. Do not add a Custom location unless the
  application supports creating and using that location.

## Responsive contract

Production pages must support all four layout classes. Breakpoints may be
adjusted to the real content, but behavior must stay consistent between pages.

| Layout | Reference width | Required behavior |
| --- | --- | --- |
| Desktop | 1280 px and wider | Full primary rail, sticky context sidebar, complete data layout |
| Compact desktop | 1024-1279 px | Compact primary rail, reduced columns, wrapped actions where needed |
| Tablet | 768-1023 px | Fully usable; context navigation stacks above the workspace or becomes a horizontally scrollable list |
| Mobile | Below 768 px | Functional fallback; single-column content, wrapped actions, contained horizontal scrolling for irreducible tables |

Tablet compatibility is the minimum visual target. Mobile is still required to
remain functional: primary actions, labels, validation messages, and navigation
must not be clipped or available only through hover.

## Theme and status rules

Light and dark themes must have equivalent component and state coverage. The
prototype screenshots are visual references, not contrast approval. In
particular, some light-theme prototype badges use a nearly black background for
values such as `Gespeichert`, `Bereit`, and `Lokal`. Production code must not
retain that treatment.

- Define semantic tokens for neutral, information, running, success, warning,
  error, loading, and disabled states in both themes.
- In the light theme, use light or moderately tinted semantic backgrounds with
  dark readable text. Do not inherit dark-theme badge backgrounds.
- Location and category badges use neutral or informational tokens; they must
  not look like errors or disabled states.
- Status meaning must not depend on color alone. Keep a text label and use an
  icon or marker where useful.
- Target WCAG AA contrast: at least 4.5:1 for normal text and 3:1 for large text,
  controls, focus indicators, and meaningful graphical boundaries.
- Verify hover, focus, selected, disabled, and loading treatments separately in
  both themes.

## Interaction rules

- All interactive elements need a visible keyboard focus state.
- Hover may reinforce an action but must not reveal the only way to access it.
- Disabled controls remain legible and explain the unavailable action where the
  reason is not obvious.
- Loading states prevent duplicate actions and communicate ongoing work.
- Empty states explain what is missing and provide the relevant next action.
- Warning and error states identify the affected scope and preserve useful
  technical details without exposing secrets.
- Sticky sidebars and headers must become static before they obstruct tablet or
  mobile content.
- Horizontal scrolling is acceptable inside a data table or context list, but
  not for the complete page.

## Implementation constraints

- Use local HTML, CSS, and JavaScript only. Do not add a frontend framework or
  runtime dependency.
- Integrate the existing localization keys from #11 for every user-facing
  string.
- Preserve application behavior before applying visual changes.
- Introduce shared tokens and components incrementally so each implementation
  issue can merge without breaking pages that have not yet migrated.
- Validate the complete redesign and both themes in
  [#35](https://github.com/borgforge/borg-backup-ui/issues/35).

The screenshots were rendered at 1440 x 1000 from the accepted local studies.
They capture representative default states only; responsive and interaction
requirements are defined by this document rather than by static images.
