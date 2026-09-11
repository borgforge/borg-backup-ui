# Pending release-note fragments

Add one Markdown file per user-visible issue, for example `247.md`.

## Format

Use these exact headings for the relevant categories. Empty categories are
omitted, and each category appears only once in the combined release notes:

- `### Before updating`: required preparation, migration and compatibility notices.
- `### Bug Fixes`: corrected behavior and its benefit to the user.
- `### Security`: actual security fixes, when present.
- `### Improvements`: new or improved workflows; highlight the main feature.

Write concise English sentences with an issue reference at the end. Use
ASCII-safe `-` bullets, blank lines after headings and four spaces for nested
bullets. Preserve the detail needed for upgrade decisions; keep implementation
history in `docs/changelog.md`. Do not repeat each entry in a second language.
German upgrade guidance belongs in the German manual and publication notice.

Example:

```markdown
### Before updating

- Create fresh configuration exports after migration. (#247)

### Improvements

- **Main feature:** Explain what users can now do. (#247)
    - Describe a related visible improvement.
```

Fragments without a heading are treated as Improvements. The renderer preserves
blank lines, nested lists and inline Markdown. Unknown category headings fail
the build so spelling mistakes cannot silently create a different layout.

## Test and stable releases

- Commit fragments before the final source preflight and test-channel build.
- Internal changes marked `release-note::no` do not need a fragment.
- A correction to already tested notes requires a new committed test candidate.
  Do not edit the published manifest or package in place.

The test-channel build embeds the exact rendered notes and hashes the fragment
files in its provenance. Stable promotion copies the complete tested version
block, including headings, whitespace and nested lists, without rebuilding or
rewriting it. It then deletes only the fragments recorded by that package.
