# Test data

`node_ids.json` is a specification, not a recording: every `id` in it was computed by hand
with `hashlib` directly, not by running jiyuu's own code, so a bug that happened to be
self-consistent could not slip through as a passing test.
