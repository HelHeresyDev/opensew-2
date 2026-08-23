# Clothing Design — a Marvelous Designer style workflow for Blender

Draw flat pattern pieces, sew them together, and simulate them onto your
character. Built and tested against Blender 5.2.

## Install

The add-on is already installed at
`~/.config/blender/5.2/scripts/addons/clothing_design`.

To install it elsewhere: `Edit > Preferences > Add-ons > Install…` and pick
`clothing_design.zip`, then tick **Clothing Design (Marvelous-style)**.

## The workspace

Sidebar (`N`) > **Clothing** > Workspace > **Create Clothing Design Workspace**.

    ┌──────────────┬─────────────────────────────┬───────────┐
    │ 2D Pattern   │                             │ Outliner  │
    │ (front ortho)│      3D garment on body     ├───────────┤
    ├──────────────┤      + Clothing sidebar     │ Physics   │
    │ Side view    │                             │ properties│
    ├──────────────┴─────────────────────────────┴───────────┤
    │ Timeline                                               │
    └────────────────────────────────────────────────────────┘

The 2D pattern area is the world XZ plane laid out to the +X side of the
avatar, so pattern pieces and the body share one scene and one undo stack.

## Workflow

1. **Import Default Character** — brings in the bundled fitting avatar: the
   project character with no clothing, a neutral face, and the feet flattened
   onto the floor (the original is posed for high heels, with a 44 mm sole
   tilt). It lands in a `CD_Avatar` collection, is set as the avatar and
   measured in one step. Textures are stripped, so the asset is 1.4 MB rather
   than 220 MB. Pressing it again reuses the copy already in the scene.
   Garments come out noticeably cleaner on this avatar than on the animated
   character, because its arms are held away from the torso instead of resting
   against the ribs.
2. **Set Avatar** — or point it at your own body mesh instead. It works out which way it faces from the
   rig's toe bones, and measures it: a stack of horizontal cross-sections plus
   limb axes taken from the armature. Arms and head are masked out using the
   skin weights, so a figure standing with its arms down does not measure as
   having a 112 cm waist.
3. **Add Garment / Outfit** — nine garments: T-Shirt, Tank Top, Dress, Jacket,
   Hoodie, Skirt, Trousers, Jumpsuit, Flat Panel. **Outfit** builds several at
   once, each on its own layer: Casual, Streetwear, Dress & Jacket, Full Layers,
   Workwear.
   Original note — T-Shirt, Tank Top, Skirt, Trousers or a Flat Panel. Every
   piece is drafted from the measurements: the neckline is solved to 1.12x the
   true neck girth, the armhole to 1.3x the biceps, and the sleeve cap is
   solved by bisection to match the armhole it is sewn to.
4. **Draw Pattern** — click points in the 2D view, Enter to close. Each click
   run becomes a named edge you can sew.
5. **Counterpart** — copies the piece to the other side of the body and sews
   the edges that meet, which is the "draw the front, get the back" step.
6. **Fabric** — pick Crisp/Tailored, Soft/Jersey, Stiff/Denim or Light/Silk.
   Bending stiffness is the strongest control over how many folds appear;
   *Take In* shrinks the fabric onto the body once the seams are welded.
   Note the sign: in Blender a *positive* shrink tightens, negative eases out.
7. **Grab Fabric** — Marvelous Designer's hand. Drag on the garment to pull it
   while the simulation runs, release to let go, scroll to change the grab
   radius, Esc to finish. It works by hooking the pinned patch, because writing
   pin targets into mesh data mid-simulation stalls the solver.
8. **Sew & Drape** — three phases:
   - *stitch*: cloth sewing springs pull the seams closed at low gravity
   - *weld*: paired seam vertices are merged into one continuous surface
   - *settle*: the garment drapes at full gravity
   Welding matters. Sewing springs never stop pulling, so leaving them on for
   the whole simulation crushes the fabric into wrinkles.
9. **Finalize** — freezes the shape, adds thickness, transfers skin weights
   from the body and binds to the rig, so the garment follows your animation.

## Mesh and subdivision

Pattern pieces are built as a **quad grid clipped to the outline**, not a
triangulation. Two reasons: a quad cage subdivides into a clean surface, and its
edges run along the pattern's own axes, so the cloth stretches along the grain
the way woven fabric does. Panels come out 100% quads at roughly 85 degrees
minimum corner angle.

**Subdivision** has separate viewport and render levels. The cloth always solves
on the quad cage, so raising the level costs nothing at simulation time - only
the displayed surface gets denser:

| Level | Rendered faces (tank top) | Mean fold angle | Drape time |
|------:|--------------------------:|----------------:|-----------:|
| 0     | 2,290                     | 19.4 deg        | 8 s        |
| 1     | 8,892                     |  8.4 deg        | 8 s        |
| 2     | 35,032                    |  4.4 deg        | 15 s       |

Modifier order is enforced as Armature, Cloth, Subdivision, Solidify. Putting the
subdivision before the cloth makes the solver run on the subdivided mesh instead
of the cage, which cost 217 s instead of 8 for the same result.

## Several garments at once

Each garment is its own entry in the **Garments** panel, listed by layer with its
open-stitch count. Selecting one makes it active: the pattern pieces, the seam
list and every operator follow it.

`Layer` sets the wearing order. A garment collides with the body and with every
garment on a *lower* layer, so 0 is worn innermost. The collision is deliberately
one-directional - an outer layer sees the inner ones, never the reverse - because
two cloth objects colliding with each other make the depsgraph cyclic and Blender
silently drops the relationship.

**Sew** stitches, welds and settles the active garment. **Unsew** does the
opposite: it rebuilds the garment from its flat pattern pieces, drops the rig
binding and thickness, and puts the stitches back so you can edit the draft and
try again. **Sew All** / **Unsew All** work through every layer from the inside
out.

Seams belong to the garment whose pieces they join, not to the scene. Storing
them globally meant adding a second garment wiped the first one's stitching and
left it impossible to re-sew.

## Skin weights

`Finalize` transfers weights from the body by nearest-polygon interpolation and
then **smooths them across neighbouring vertices**. This is not cosmetic. At the
crotch the two thighs nearly touch, so neighbouring garment vertices land on
opposite legs: one follows the left thigh, the next follows the right. As the
legs separate those neighbours are dragged apart and the garment tears open.
Measured on the jumpsuit at a mid-stride frame, worst-case edge stretch went
from 7.8x to 2.1x once the influences were blended.

Note that `bpy.ops.object.vertex_group_smooth` does nothing when driven
headlessly, so the smoothing is implemented directly rather than through the
operator.

## Notes

- Collision is restricted to a `CD_Colliders` collection holding just the
  avatar. Letting every cloth object collide with every other creates
  depsgraph cycles.
- *Keep Off Body* lifts arranged panels clear of the mesh before simulating.
  Anything starting inside the body gets ejected explosively by the solver.
- A Flat Panel has no seams, so it falls. That is expected: it is a piece of
  cloth, not a garment.
- Measurements ignore arms, hands, fingers and the head, using the rig's own
  skin weights. Missing even one group matters: CC4 names finger bones
  `Index1`/`Mid1`, and with those unmasked an A-pose reads as a 164 cm waist.
- Waist and hip are taken as the narrowest and widest sections of the torso,
  not from the rig's `Waist`/`Pelvis` bones, which sit several cm low.
- Fabric defaults are Crisp/Tailored: bending 25, compression 120, Take In
  0.05, quality 12. That is roughly a third fewer folds than the soft default,
  at about twice the simulation time.
- Sleeves are the roughest preset. The cap sews correctly but tends to gather
  at the armhole on a character whose arms hang against the body. On the
  bundled avatar they come out clean.
