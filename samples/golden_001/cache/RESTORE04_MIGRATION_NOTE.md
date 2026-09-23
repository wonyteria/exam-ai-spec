# RESTORE-04 cache migration

The six-class layer engine changed restored-page bytes (policy-
filtered removal mask instead of the dilated trace mask), so
image-bound cache keys changed. Recorded responses were aliased
from the legacy key to the RESTORE-04 key for the same (page,
region, prompt) call. Seeded regression data only — not an
accuracy oracle.
