import argparse
from pathlib import Path
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clothing_design
from clothing_design import build, ops, sim


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--figure", choices=("MAN", "WOMAN"), default="MAN")
    parser.add_argument("--preset", choices=("TSHIRT", "TANK", "TROUSERS", "JACKET"), default="TSHIRT")
    parser.add_argument("--operation", choices=("sew", "drape"), default="sew")
    parser.add_argument("--save", type=Path)
    opts = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    clothing_design.register()
    context = bpy.context
    assert bpy.ops.cd.import_character(figure=opts.figure) == {'FINISHED'}
    assert bpy.ops.cd.add_garment(preset=opts.preset) == {'FINISHED'}
    garment = build.garment_object(context, create=False)
    assert build.loose_edges(garment.data)
    before = time.monotonic()
    assert getattr(bpy.ops.cd, opts.operation)() == {'FINISHED'}
    print(f"{opts.operation} took {time.monotonic() - before:.2f}s")
    status = ops.simulation_status()
    assert status["state"] == "finished", status
    assert status["frame"] == 76 and status["phase"] == "Settling", status
    assert not build.loose_edges(garment.data)

    fit = sim.body_fit(context, garment)
    print(f"{bpy.app.version_string} {opts.figure} {opts.preset}: {fit}", flush=True)
    if opts.preset in {"TSHIRT", "JACKET"}:
        assert fit["vertices_inside"] == 0 and fit["intersecting_triangles"] == 0, fit
        if opts.preset == "TSHIRT":
            assert "0 open stitches removed" in status["message"], status
    elif opts.preset in {"TANK", "TROUSERS"}:
        assert fit["vertices_inside"] < fit["vertices"] * 0.005, fit

    if opts.save:
        assert sim.bake_shape(context, garment)
        for modifier in list(garment.modifiers):
            if modifier.type == 'CLOTH':
                garment.modifiers.remove(modifier)
        assert bpy.ops.wm.save_as_mainfile(filepath=str(opts.save.resolve())) == {'FINISHED'}


if __name__ == "__main__":
    main()
