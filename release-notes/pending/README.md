# Pending release-note fragments

Add one Markdown file per user-visible issue, for example `247.md`.

Rules:

- Use ASCII-safe `-` bullet lines.
- Describe user-visible behavior, not implementation details.
- Commit the fragment before the final source preflight and test-channel build.
- Internal changes marked `release-note::no` do not need a fragment.
- Never edit or delete a tested fragment manually before stable promotion.

The test-channel build embeds the exact rendered notes and hashes the fragment
files in its provenance. Stable promotion copies the tested package and notes
without rebuilding, then deletes only the fragments recorded by that package.
