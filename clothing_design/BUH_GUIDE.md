# OpenSew2 for Beneath Uncounted Heavens

This fork is based on upstream commit `86b4322` and uses the same `clothing_design` Python package and `bpy.ops.cd` operator names. It was tested on Linux with Blender 5.3.0, build `02f0899d78e3`. Upstream documents Blender 5.2 as its tested version. The cause of any difference between Blender versions remains untested.

## Install

The ZIP is a legacy Blender add-on. Back up the stock `clothing_design` add-on folder because both versions use that directory name. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**, select the ZIP, and enable **Clothing Design (Beneath Uncounted Heavens)**. Restart Blender if the stock package was loaded in that session.

The revised arrangement applies when you draft a T-shirt or jacket. For a T-shirt saved with the stock defaults, redraft it or set **Ease** to `0.04 m` on each of the four pattern pieces and use **Arrange on Body** again. Arrangement Ease is the starting clearance around the avatar. The **Ease** in **Add Garment** sets the width of the pattern.

## Simulate

**Sew** and **Sew & Drape** run the same stitch, weld, and settle sequence. The default T-shirt starts with 4 cm of arrangement clearance. The jacket starts with 5 cm and places the long sleeves farther along the arms so the sleeve caps can seat at the shoulders. The shoulder pin is used for a sleeved garment over a torso layer, where it helps hold the garment while sewing.

The graphical operators advance one frame at a time and show the current phase in Blender’s status bar. You can orbit or zoom between frames. Escape stops at the current frame and keeps the work completed so far. A single slow frame or weld can still briefly delay input. Simulation time depends on the garment and cloth settings.

## Run from Blender MCP

### Graphical Blender

Execute the following in Blender after setting the avatar, drafting the patterns, and selecting the garment in the Clothing workspace.

```python
import bpy

window = bpy.context.window_manager.windows[0]
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
region = next(region for region in area.regions if region.type == 'WINDOW')
with bpy.context.temp_override(window=window, area=area, region=region):
    print(bpy.ops.cd.drape('INVOKE_DEFAULT'))
```

Run the next snippet in a later MCP call. While the operator is running, it reports the phase, garment, Blender frame, and phase progress. When it finishes, the message includes counts of welded vertices and any overlong stitches that were removed without welding.

```python
import bpy
from clothing_design import build, ops, sim

status = ops.simulation_status()
print(status)
if status["state"] == "finished":
    garment = build.garment_object(bpy.context, create=False)
    print(sim.body_fit(bpy.context, garment))
```

`body_fit` checks the evaluated garment mesh at the current frame against the avatar. It reports vertices more than 4 mm inside the body by default, the maximum estimated depth in metres, and the number of garment triangles that intersect the body. Inspect the neckline, shoulders, sleeves, and seams in the viewport before finalizing. For layered or animated clothing, also check the other layers and representative poses.

### Headless Blender MCP

Start a fresh Blender scene for an experiment. If you need to load an empty startup scene through MCP, save your current work first and use `bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)`. The Blender MCP extension blocks `read_factory_settings` because it resets preferences.

Run each code block as a separate MCP request. Start by importing an avatar and drafting a named garment.

```python
import bpy

bpy.ops.cd.import_character(figure='MAN')
bpy.ops.cd.add_garment(preset='TSHIRT', name='Inner shirt')
result = {"garment": bpy.context.scene.cd.garment_name}
```

Queue the already arranged garment by name.

```python
import bpy
from clothing_design import ops

result = ops.start_sew(bpy.context, "Inner shirt")
```

Repeat this request until `state` is `finished`. Keep `frames_per_call=1` for an unknown garment or a tight timeout. A step runs at most one frame or advances the current phase. One costly frame or a weld still takes as long as Blender needs for that work. Keep the scene, view layer, and timeline in place while the job runs.

```python
import bpy
from clothing_design import ops

result = ops.step_sew(bpy.context, frames_per_call=1)
```

Use `ops.simulation_status()` to read progress after an interrupted request and `ops.cancel_sew()` to stop and keep the current state. Once the job completes and you have checked the fit and weld counts, set `bpy.context.scene.cd.garment_name` to the same name before calling `bpy.ops.cd.finalize()`. The existing `bpy.ops.cd.sew()` and `bpy.ops.cd.drape()` calls still run synchronously for standalone Blender scripts.

### Layered sewing performance

OpenSew pauses cloth and collision modifiers on outer garments while sewing underneath them. Inner garments still act as colliders. For a layered outfit, sew and finalize the inner garments first so later solves can use them as fitted colliders. The outer layers resume their previous modifier settings when the sew finishes or is cancelled.

On the project machine with Blender 5.3, a four-garment scene took 62.9 seconds to sew and settle its T-shirt in BUH 1.0.2. BUH 1.0.3 took 12.4 seconds at the same mesh resolution, cloth quality, and frame counts. Through headless Blender MCP, the 1.0.3 test finished in four calls with `frames_per_call=10`. The slowest call took 3.74 seconds. All 160 stitches welded and the final shirt had zero measured body intersections.

### Cultivator outfit experiment

The verified stock T-shirt and jacket use their default sleeve lengths. The longer 92 cm T-shirt sleeves and the open, knee-length jacket are separate fitting cases from the report. A crossed collar needs overlapping front pattern pieces. A sash needs a closed waist construction or an attachment to the garment underneath before gravity is enabled.

## Verification

Run from the fork root with the add-on available to Blender. The targeted fit and UI tests import the checkout directly.

```sh
blender -b --factory-startup --python-exit-code 1 --python tests/test_blender53_fit.py -- --operation stepped --outer-layer
blender -b --factory-startup --python-exit-code 1 --python tests/test_blender53_fit.py -- --figure WOMAN --operation drape
blender --factory-startup --enable-event-simulate --python-exit-code 1 --python tests/test_simulation_ui.py
```

The finished T-shirt and jacket had zero intersecting body triangles on Theo and Nora in the tested fitting pose. The stock T-shirt exposed skin around Theo’s shoulders and upper back. The fork result covered those areas in the front, back, and three-quarter renders. Tank top and trousers passed the body-intersection check on Theo. On each avatar, the jacket weld discarded three stitches that exceeded the maximum stitch gap. Inspect the seam joins even when the garment clears the body. Clipping during animation and fit on custom bodies require their own checks.
