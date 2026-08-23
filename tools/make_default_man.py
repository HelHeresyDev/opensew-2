# Build clothing_design/assets/default_man.blend: the male fitting avatar.
#
#   blender -b /data/kits/cc4_blender/guy-test.blend --python tools/make_default_man.py
#
# Keeps the body, brow, eyes, teeth and tongue with their rig; drops the
# clothing, hair, lights and every texture; clears the pose so the rig's own
# rest pose (arms held 60 deg out, as on the female avatar) is what drapes
# see; removes the 161 facial shape keys; stands the feet on the floor.
import bpy, os, sys

KEEP = {"CC_Base_Body": "CD_Man_Body", "Kevin_Brow": "CD_Man_Brow", "CC_Base_Eye": "CD_Man_Eye",
        "CC_Base_Teeth": "CD_Man_Teeth", "CC_Base_Tongue": "CD_Man_Tongue"}
RIG = "Armature"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "clothing_design", "assets", "default_man.blend")

arm = bpy.data.objects[RIG]
keep = [bpy.data.objects[n] for n in KEEP] + [arm]

# drop everything else
for ob in list(bpy.data.objects):
    if ob not in keep:
        bpy.data.objects.remove(ob, do_unlink=True)

# rest pose: no animation, no pose transforms
arm.animation_data_clear()
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
arm.data.pose_position = 'POSE'
arm.name = "CD_Man_Rig"
arm.data.name = "CD_Man_Rig"

# simple untextured materials, matching the female asset's names
def plain(name, rgb, rough=0.55):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return mat

skin = plain("CD_Avatar_Skin", (0.62, 0.47, 0.38))
eye = plain("CD_Avatar_Eye", (0.9, 0.9, 0.9), 0.2)
mouth = plain("CD_Avatar_Mouth", (0.55, 0.25, 0.25))
MATS = {"CD_Man_Body": skin, "CD_Man_Brow": skin, "CD_Man_Eye": eye,
        "CD_Man_Teeth": mouth, "CD_Man_Tongue": mouth}

for src, dst in KEEP.items():
    ob = bpy.data.objects[src]
    ob.name = dst
    ob.data.name = dst
    if ob.data.shape_keys:
        ob.shape_key_clear()
    for mod in list(ob.modifiers):
        if mod.type != 'ARMATURE':
            ob.modifiers.remove(mod)
    ob.data.materials.clear()
    ob.data.materials.append(MATS[dst])
    for attr in list(ob.data.attributes):      # CC4 ships colour/uv extras
        if attr.data_type in ('FLOAT_COLOR', 'BYTE_COLOR'):
            try:
                ob.data.attributes.remove(attr)
            except Exception:
                pass
    ob.hide_set(False); ob.hide_viewport = False; ob.hide_render = False

body = bpy.data.objects["CD_Man_Body"]
body["cd_figure"] = 'MAN'

# feet on the floor: evaluate the rest pose and shift the rig down
dg = bpy.context.evaluated_depsgraph_get()
ev = body.evaluated_get(dg)
zmin = min((ev.matrix_world @ v.co).z for v in ev.data.vertices)
arm.location.z -= zmin
print("floor shift %.4f m" % -zmin)

# one collection, no stray data
scene = bpy.context.scene
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)
coll = bpy.data.collections.new("Collection")
scene.collection.children.link(coll)
for ob in bpy.data.objects:
    for c in ob.users_collection:
        c.objects.unlink(ob)
    coll.objects.link(ob)
for block in (bpy.data.images, bpy.data.actions, bpy.data.cameras, bpy.data.lights,
              bpy.data.node_groups, bpy.data.worlds, bpy.data.texts):
    for x in list(block):
        block.remove(x)
for _ in range(4):
    bpy.data.orphans_purge(do_recursive=True)

bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True, copy=True)
print("wrote", OUT, os.path.getsize(OUT) // 1024, "KB")
