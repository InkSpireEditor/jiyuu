# Themes

Each `.yaml` file here is one colour theme jiyuu can draw a map with. The colour values come
from these palettes, used under their own licences:

| File | Palette | Source | Licence |
|---|---|---|---|
| `nord.yaml` | Nord, as arranged by Freeplane's `dark_nord_template.mm` map style | https://github.com/nordtheme/nord | MIT |
| `nord-frost.yaml` | Nord, Frost group | https://github.com/nordtheme/nord | MIT |
| `nord-aurora.yaml` | Nord, Aurora group | https://github.com/nordtheme/nord | MIT |
| `tokyonight-night.yaml` | Tokyo Night, `night` style | https://github.com/folke/tokyonight.nvim | Apache-2.0 |
| `solarized-dark.yaml` | Solarized, dark | https://github.com/altercation/solarized | MIT |

Which palette colour is used for which part of a map (canvas, edges, root, each depth level,
selection, tasks that are done) is jiyuu's own choice; each file's header comment notes where it departs from the
palette's obvious choice and why.

## Format

```yaml
name: Nord Frost
credits: Nord, https://github.com/nordtheme/nord (MIT)
canvas: "#2e3440"          # background behind the whole map
edge: "#d8dee9"            # edges, and node borders
selection: {text: "#2e3440", background: "#ebcb8b"}
root: {text: "#eceff4", background: "#4c566a"}
task_done: {text: "#8a94a8", background: "#3b4252"}  # a task that is done, at any depth
levels:                    # depth 1, 2, 3, ...; cycles back to the first after the last
  - {text: "#2e3440", background: "#8fbcbb"}
```

Every colour is a quoted `"#rrggbb"` string: unquoted, YAML reads `#` as the start of a
comment. Every text colour should have a contrast ratio of at least 3.0 against its
background, and the edge colour at least 3.0 against the canvas; the test suite enforces this
for the files bundled here.
