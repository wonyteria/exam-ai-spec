# WP03 cache migration

The S01 print-preservation guard changed `trace_removed` bytes, so
image-bound cache keys changed. Recorded responses were aliased from
the pre-guard key to the post-guard key for the same (page, region,
prompt) call. Seeded regression data only — not an accuracy oracle.
