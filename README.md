# OpenSew 2 — Clothing Design for Blender

A Marvelous Designer style garment workflow inside Blender: draw flat pattern
pieces in a 2D view, sew them, drape them onto a character with Blender's own
cloth solver, and bind the result to the rig. Built against Blender 5.2.

This repository continues the `clothing_design` add-on. It supersedes the
numpy-core `opensew` library, whose Blender bridge gave no visual reference for
the flat panels or their arrangement before draping, and whose drapes could
not be corrected by hand when they went wrong.

- The add-on: [`clothing_design/`](clothing_design/) — workflow and design
  notes in its [README](clothing_design/README.md).
- Illustrated docs (single self-contained page): [`docs/clothing_design.html`](docs/clothing_design.html).

## Develop

Symlink the package into Blender's add-on folder so edits are live after
`Reload Scripts` (F3 > "Reload Scripts") or a restart:

```bash
ln -sfn /data/opensew-2/clothing_design ~/.config/blender/5.2/scripts/addons/clothing_design
```

Then enable **Clothing Design (Marvelous-style)** under Edit > Preferences > Add-ons.

Packaging for install elsewhere:

```bash
cd /data/opensew-2 && zip -r clothing_design.zip clothing_design -x '*__pycache__*'
```
