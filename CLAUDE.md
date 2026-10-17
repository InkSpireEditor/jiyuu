# CLAUDE.md

Guidance for Claude Code working in this repository.

## What jiyuu is

A desktop mindmap viewer and editor, similar to FreeMind and Freeplane, written in Python
with Flet. It opens Freeplane `.mm` maps and stores its own maps as `.ink` files. See
`ROADMAP.md` for the full design and the step-by-step implementation plan.

## Writing style

The user's global `~/.claude/CLAUDE.md` sets writing-style rules — write literally, name
things concretely, no figurative language, no invented shorthand. Those rules apply here to
code comments, commit messages and documentation exactly as they do everywhere else; they are
not repeated in full in this file.

## Session workflow

Work proceeds through `ROADMAP.md` one step at a time; see that file's "How to use this
file" for how a step's status and checkboxes are tracked.

- Before starting a step, confirm every step it depends on is `done`.
- Set the step's status to `in progress` before working on it, and implement its tasks.
- A step is not finished while any of its three gates fails. Run all three, and report their
  result — pass or fail, and pylint's score — before going further:

  ```bash
  poetry run pytest
  poetry run pylint --rcfile=.github/workflows/pylintrc --fail-under=9.5 jiyuu
  poetry run ty check
  ```
  If one fails, report the failure, fix it, and re-run all three — do not tick a step's
  boxes on a partial pass.
- Once all three pass: tick every checkbox for that step, set its status to `done`, add any
  decision made while doing it to the Decisions table, and `git add` the result.
- **Never run `git commit`.** Stage the files, then propose a commit message for the user —
  the user commits every change in this repository, without exception. If asked to commit
  anyway, stage the change and restate this rule rather than committing.
- Do not start the next step in the same change that finishes the current one.
- Grow the window (`jiyuu open`, `jiyuu/ui/`) alongside the backend: whenever a step
  produces something worth looking at, make the window show it too, so the user can see and
  try new features regularly rather than only reading a test-pass report. See the
  Cross-cutting guards in `ROADMAP.md`.
- If a step's done condition cannot be met, leave it `in progress` and write the failure
  under that step rather than marking it done.
- A step's data structures, algorithms, numeric defaults and worked examples in `ROADMAP.md`
  are the specification for that step, not a sketch to redesign from. Where it gives a
  function signature or a pseudocode block, implement that function; where it gives a real
  computed example (a hash, a coordinate, a rendered file), match it exactly, since those
  values are reproducible, not illustrative. Deviate only where a step's own
  "Blockers/risks" names a fallback and the described trigger actually occurred — and record
  which fallback was used, under that step, when it is.

## Documentation standard

Every module, class and function gets a docstring; a non-obvious line gets a comment. All of
it is written for a reader who has only the code and its own shipped docs in front of them —
someone outside this repository's history, who has never seen `ROADMAP.md` or this file.

- Describe what the code does and, where it is not obvious from the name, why — grounded in
  the file format, the library, or the problem being solved, never in this project's own
  planning. "Quoted because an all-digit key would otherwise read back as a YAML integer" is
  fine; "quoted per step 9 of the roadmap" or "because the user asked for it" is not.
- A reference to something outside this repository is fine only if a reader could actually
  find and check it themselves — a published specification, a library's own public
  documentation, a public project's own docs, named together with a real link. inkspire-api
  (https://github.com/InkSpireEditor/inkspire-api) is public and qualifies on that basis, as
  does any other public repository of the author's — but always with the link, never assumed
  as something the reader already knows. A genuinely private or unpublished project would not
  qualify, since the reader would have no way to reach it; there is no such project referenced
  in this codebase today.
- A reference to this repository's own `ROADMAP.md`, its Decisions table, a commit message,
  or a past conversation is not fine either — none of that ships with the code.
- This applies to `README.md` and any other documentation meant to describe jiyuu itself, not
  only to code comments and docstrings. `ROADMAP.md` and this file are the exception: they
  are the project's own planning documents, read only by this project's own contributors, and
  may name inkspire-api, reference each other, past steps, and decisions freely — as long as
  none of that leaks into what ships in `jiyuu/` or `README.md`.

## Privacy: real mindmap content

During a coding session the user may open real Freeplane/FreeMind or `.ink` maps of their
own, to check that a reader or the viewer handles them correctly. **Their content — node
text, file names, any attribute value — must never reach anything that gets committed**: not
a fixture, not a test, not a code comment or docstring, not a commit message, not this file
or `ROADMAP.md`, not a note written down anywhere in the repository.

- Open the user's own files from outside the repository — their existing location on disk,
  or a path under `/tmp` for the session — never by copying them into `tests/data/` or any
  other path inside the working tree, even temporarily and even if later `.gitignore`d: a
  gitignored file can still be swept in by an overly broad `git add`.
- If a real file exposes a bug, reproduce it with a new fixture built from placeholder text
  (`Project`, `Goals`, `Foo`, ...) that triggers the same code path, and describe the bug in
  terms of that placeholder fixture. Do not quote, paraphrase, or describe the real file's
  content to explain the bug — describe the shape of the problem instead (e.g. "a `<node>`
  with no `TEXT` and no `richcontent`").
- Before staging a change, check `git status` for anything under a path the user pointed
  jiyuu at for manual testing. If it is unclear whether a file is a repository fixture or one
  of the user's own maps, ask before adding it.

## Commands

```bash
poetry install
poetry run jiyuu ...
poetry run pytest
poetry run pylint --rcfile=.github/workflows/pylintrc --fail-under=9.5 jiyuu
poetry run ty check
```

## Layout

- `jiyuu/` — the core model, layout, navigation, editing and format modules. None of these
  import `flet`.
- `jiyuu/formats/` — `.ink` grammar, `.mm` reading/writing, markdown export.
- `jiyuu/ui/` — the only place `flet` is imported.
- `jiyuu/assets/` — the bundled font and the colour themes (`themes/*.yaml`). Every colour
  drawn comes from a theme file; none is written as a constant in UI code.
- `tests/`, `tests/data/` — fixtures and hand-written test vectors.

## `.ink` format

`jiyuu/formats/ink.py` implements the grammar used by inkspire-api
(https://github.com/InkSpireEditor/inkspire-api, `inkspire_api/ink.py` and
`docs/ink-format.md`), a separate public project of the author's, copied rather than shared
as a dependency so each project can evolve its own section names. The module's own docstring
describes the grammar fully and self-containedly and also credits inkspire-api by that link,
per `ROADMAP.md` step 7. Keep the grammar compatible with inkspire-api's `docs/ink-format.md`
unless a difference is deliberate, and if so, record the difference in both the module's
docstring and `ROADMAP.md`'s Decisions table. A change made here does not reach inkspire-api
automatically, and the reverse is also true — note inkspire-api is licensed
PolyForm-Noncommercial-1.0.0; check jiyuu's own licence is compatible with code copied from it
before step 0's `LICENSE` is chosen.

## Fixtures and test data

Fixtures and examples use placeholder text only (`Project`, `Goals`, `Foo`, `Jane Doe` — not
invented "realistic" names). See "Privacy: real mindmap content" above for how the user's own
maps are handled during manual testing.
