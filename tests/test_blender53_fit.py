import argparse
from pathlib import Path
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clothing_design
from clothing_design import avatar, build, ops, sim


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--figure", choices=("MAN", "WOMAN"), default="MAN")
    parser.add_argument("--preset", choices=("TSHIRT", "TANK", "TROUSERS", "JACKET", "SASH"), default="TSHIRT")
    parser.add_argument("--operation", choices=("sew", "drape", "stepped"), default="sew")
    parser.add_argument("--outer-layer", action="store_true")
    parser.add_argument("--fit", type=float, default=0.08)
    parser.add_argument("--relax", action="store_true")
    parser.add_argument("--save", type=Path)
    opts = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    clothing_design.register()
    context = bpy.context
    with context.temp_override(selected_objects=None):
        assert bpy.ops.cd.import_character(figure=opts.figure) == {'FINISHED'}
    if opts.preset == "SASH":
        context.scene.cd.show_patterns = False
    assert bpy.ops.cd.add_garment(preset=opts.preset, fit=opts.fit) == {'FINISHED'}
    garment = build.garment_object(context, create=False)
    assert build.loose_edges(garment.data)
    if opts.preset == "SASH":
        assert build.activate_garment(context, garment) == garment
        assert all(not piece.visible_get(view_layer=context.view_layer)
                   for piece in build.garment_pieces(context))
        context.scene.cd.show_patterns = True
        assert all(piece.visible_get(view_layer=context.view_layer)
                   for piece in build.garment_pieces(context))
    outer_physics = []
    if opts.outer_layer:
        assert bpy.ops.cd.add_garment(preset="JACKET", name="Outer layer") == {'FINISHED'}
        outer = build.garment_object(context, create=False)
        outer_physics = [mod for mod in outer.modifiers if mod.type in {'CLOTH', 'COLLISION'}]
        assert len(outer_physics) == 2 and all(mod.show_viewport for mod in outer_physics)
        context.scene.cd.garment_name = garment.cd.garment
        ops.start_sew(context, garment.cd.garment)
        status = ops.step_sew(context, frames_per_call=2)
        assert status["stage_frame"] == 0 and not any(mod.show_viewport for mod in outer_physics)
        assert ops.cancel_sew()["state"] == "cancelled"
        assert all(mod.show_viewport for mod in outer_physics)
    before = time.monotonic()
    if opts.operation == "stepped":
        status = ops.start_sew(context, garment.cd.garment)
        assert status["phase"] == "Queued" and not bpy.ops.cd.sew.poll()
        for _ in range(100):
            status = ops.step_sew(context, frames_per_call=1)
            if status["state"] != "running":
                break
    else:
        assert getattr(bpy.ops.cd, opts.operation)() == {'FINISHED'}
    print(f"{opts.operation} took {time.monotonic() - before:.2f}s")
    status = ops.simulation_status()
    assert status["state"] == "finished", status
    assert status["frame"] == 76 and status["phase"] == "Settling", status
    assert not build.loose_edges(garment.data)
    assert all(mod.show_viewport for mod in outer_physics)

    fit = sim.body_fit(context, garment)
    print(f"{bpy.app.version_string} {opts.figure} {opts.preset}: {fit}", flush=True)
    if opts.preset in {"TSHIRT", "JACKET", "SASH"}:
        assert fit["vertices_inside"] == 0 and fit["intersecting_triangles"] == 0, fit
        if opts.preset in {"TSHIRT", "SASH"}:
            assert "0 open stitches removed" in status["message"], status
    elif opts.preset in {"TANK", "TROUSERS"}:
        assert fit["vertices_inside"] < fit["vertices"] * 0.005, fit

    if opts.preset == "SASH":
        waist = avatar.z_of(avatar.measure(context), "waist")
        evaluated = garment.evaluated_get(context.evaluated_depsgraph_get())
        heights = [(evaluated.matrix_world @ vertex.co).z for vertex in evaluated.data.vertices]
        assert waist - 0.16 < min(heights) < waist < max(heights) < waist + 0.08

    if opts.relax:
        status = ops.start_relax(context, garment.cd.garment, take_in=0, frames=3, relax_frames=2)
        assert status["operation"] == "cd.relax"
        assert ops.step_relax(context, frames_per_call=100, time_budget_s=1e-9)["frame"] == 77
        for _ in range(8):
            status = ops.step_relax(context, frames_per_call=2)
            if status["state"] == "finished":
                break
        assert status["state"] == "finished" and status["frame"] == 81, status
        assert all(mod.show_viewport for mod in outer_physics)

    if opts.save:
        assert sim.bake_shape(context, garment)
        for modifier in list(garment.modifiers):
            if modifier.type == 'CLOTH':
                garment.modifiers.remove(modifier)
        assert bpy.ops.wm.save_as_mainfile(filepath=str(opts.save.resolve())) == {'FINISHED'}


if __name__ == "__main__":
    main()
