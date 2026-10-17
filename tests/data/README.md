# Test data

All of it is hand-written, with placeholder text only.

- `node_ids.json` is a specification, not a recording: every `id` in it was computed by
  hand with `hashlib` directly, not by running jiyuu's own code, so a bug that happened to
  be self-consistent could not slip through as a passing test.
- `mm/` holds FreeMind/Freeplane `.mm` files, one per case the `.mm` reader has to handle.
- `ink/` holds `.ink` files that must read and write back byte for byte.
