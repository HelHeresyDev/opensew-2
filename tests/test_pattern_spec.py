import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clothing_design
from clothing_design import avatar, build, library, sim


def main():
    clothing_design.register()
    context = bpy.context
    assert bpy.ops.cd.import_character(figure="MAN") == {"FINISHED"}
    measured = avatar.measure(context)
    pieces, seams = library.preset_tshirt(measured, fit=0.1)
    spec = json.loads(json.dumps({"name": "Structured shirt", "shoulder_pins": False,
                                  "pieces": pieces, "seams": seams}, default=list))
    spec["pieces"][2]["ease"] = 0.045
    invalid = dict(spec, seams=[["Front", "missing", "Back", "hem"]])
    try:
        build.draft_garment(context, invalid)
    except ValueError:
        assert not build.garment_pieces(context, spec["name"])
        assert build.garment_object(context, spec["name"], create=False) is None
    else:
        raise AssertionError("Invalid seam accepted")

    garment = build.draft_garment(context, spec)
    assert garment.cd.garment == spec["name"] and not garment.cd.shoulder_pins
    assert len(build.garment_pieces(context)) == 4 and len(context.scene.cd.seams) == 10
    assert any(abs(piece.cd.ease - 0.045) < 1e-5 for piece in build.garment_pieces(context))
    assert bpy.ops.cd.sew() == {"FINISHED"}
    assert not build.loose_edges(garment.data)
    assert sim.layer_fit(context, garment) == {}

    scene = context.scene
    scene.cd.bind_armature = True
    assert bpy.ops.cd.finalize() == {"FINISHED"}
    rig = avatar.find_armature(scene.cd.avatar)
    assert any(mod.type == 'ARMATURE' and mod.object == rig for mod in garment.modifiers)
    upper_arm = next(bone for bone in rig.pose.bones if "leftarm" in bone.name.lower())
    thigh = next(bone for bone in rig.pose.bones if "leftupleg" in bone.name.lower())
    poses = [
        (1, None, None),
        (2, (0.25, -0.15, 1.0), None),
        (3, (0.7, -0.1, 0.7), (0.2, -1.0, 0.15)),
    ]
    for frame, arm_direction, leg_direction in poses:
        for bone, target in [(upper_arm, arm_direction), (thigh, leg_direction)]:
            basis = bone.bone.matrix_local.to_3x3()
            rest = bone.bone.tail_local - bone.bone.head_local
            bone.rotation_mode = 'QUATERNION'
            bone.rotation_quaternion = (basis.inverted() @ rest).rotation_difference(
                basis.inverted() @ (rest if target is None else Vector(target)))
            bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    scene.frame_set(3)
    leg = thigh.tail - thigh.head
    assert leg.y < 0 and leg.z > 0, tuple(leg)
    scene.frame_set(2)
    assert (upper_arm.tail - upper_arm.head).z > 0
    scene.frame_set(2, subframe=0.25)
    fit = sim.pose_fit(context, garment, [1, 2, 3])
    assert [entry["frame"] for entry in fit] == [1, 2, 3]
    assert scene.frame_current == 2 and abs(scene.frame_subframe - 0.25) < 1e-6
    assert fit[0]["vertices_inside"] == 0, fit
    assert len({entry["intersecting_triangles"] for entry in fit}) > 1, fit
    print("Rest, raised arm, and raised arm with high kick measurements:", fit, flush=True)


if __name__ == "__main__":
    main()
