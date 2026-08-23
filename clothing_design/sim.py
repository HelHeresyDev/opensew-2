# Clothing Design - cloth simulation, draping and finalising.
import bpy, bmesh, math
from contextlib import contextmanager
from mathutils import Vector
from . import patterns, build

COLLIDER_COLL = "CD_Colliders"


def collider_collection(context):
    """Collection holding the avatar. Must stay linked to the scene or Blender
    purges it on save and the cloth silently reverts to colliding with the
    whole scene."""
    coll = patterns.get_collection(context, COLLIDER_COLL)
    try:
        coll.hide_render = True
    except Exception:
        pass
    return coll


def garment_layers(context):
    """Every garment in the scene, innermost first."""
    gs = [o for o in context.scene.objects
          if o.cd.is_garment and o.data and len(o.data.vertices)]
    gs.sort(key=lambda o: (o.cd.layer, o.name))
    return gs


def make_collidable(ob):
    """Let other cloth collide with this garment."""
    mod = next((m for m in ob.modifiers if m.type == 'COLLISION'), None)
    if mod is None:
        mod = ob.modifiers.new("CD_Collision", 'COLLISION')
    cs = ob.collision
    if cs:
        cs.thickness_outer = 0.002
        cs.thickness_inner = 0.006
        cs.damping_factor = 0.25
        cs.cloth_friction = 5.0
    return mod


def setup_layers(context):
    """Point each garment's cloth at the body plus everything worn under it.

    The collision is deliberately one-directional: an outer layer sees the
    inner ones, never the reverse. Letting two cloth objects collide with each
    other makes the depsgraph cyclic and Blender drops the relationship.
    """
    scn = context.scene
    av = scn.cd.avatar
    gs = garment_layers(context)
    if not gs:
        return 0
    for g in gs:
        make_collidable(g)
    n = 0
    for g in gs:
        coll = patterns.get_collection(context, "CD_Colliders_L%d" % g.cd.layer)
        try:
            coll.hide_render = True
        except Exception:
            pass
        for o in list(coll.objects):
            coll.objects.unlink(o)
        if av is not None:
            coll.objects.link(av)
        for other in gs:
            if other is not g and other.cd.layer < g.cd.layer:
                coll.objects.link(other)
        for mod in g.modifiers:
            if mod.type == 'CLOTH':
                mod.collision_settings.collection = coll
                n += 1
    return n


def ensure_collider(context, av):
    if av is None:
        return None
    coll = collider_collection(context)
    if av.name not in coll.objects:
        coll.objects.link(av)
    mod = next((m for m in av.modifiers if m.type == 'COLLISION'), None)
    if mod is None:
        mod = av.modifiers.new("CD_Collision", 'COLLISION')
    cs = av.collision
    if cs:
        cs.thickness_outer = 0.002
        cs.thickness_inner = 0.02
        cs.damping_factor = 0.3
        cs.cloth_friction = 5.0
    return mod


def setup_cloth(context, ob):
    scn = context.scene
    cd = scn.cd
    mod = next((m for m in ob.modifiers if m.type == 'CLOTH'), None)
    if mod is None:
        mod = ob.modifiers.new("CD_Cloth", 'CLOTH')
    s = mod.settings
    s.quality = cd.quality
    s.mass = cd.mass
    s.air_damping = cd.air_damping
    s.bending_model = 'ANGULAR'
    s.tension_stiffness = cd.stiff_tension
    s.compression_stiffness = cd.stiff_compress
    s.shear_stiffness = cd.stiff_shear
    s.bending_stiffness = cd.stiff_bend
    s.tension_damping = 15.0
    s.compression_damping = 15.0
    s.shear_damping = 5.0
    s.bending_damping = 0.5
    s.use_sewing_springs = True
    s.sewing_force_max = cd.sew_force
    # Taking the fabric in while the seams are still open fights the stitching,
    # so it is applied at the weld instead (see close_seams).
    s.shrink_min = 0.0

    cs = mod.collision_settings
    cs.collision_quality = 4
    cs.distance_min = cd.coll_distance
    cs.damping = 0.3
    cs.friction = 5.0
    cs.use_self_collision = cd.self_collision
    cs.self_distance_min = max(0.001, cd.coll_distance * 0.5)
    cs.self_friction = 2.0
    layered = [o for o in scn.objects if o.cd.is_garment and o.data and len(o.data.vertices)]
    if len(layered) > 1:
        cs.collection = patterns.get_collection(context, "CD_Colliders_L%d" % ob.cd.layer)
    else:
        cs.collection = collider_collection(context)

    order_modifiers(ob)
    pc = mod.point_cache
    pc.frame_start = scn.frame_current
    pc.frame_end = scn.frame_current + max(cd.stitch_frames + cd.settle_frames, 250)
    return mod


def reset_cache(ob):
    for mod in ob.modifiers:
        if mod.type == 'CLOTH':
            try:
                mod.point_cache.frame_start = bpy.context.scene.frame_current
            except Exception:
                pass


DISPLAY_MODS = {'SUBSURF', 'SOLIDIFY'}


@contextmanager
def sim_cage_only(ob):
    """Temporarily switch off the modifiers that change the vertex count.

    Freezing the shape and the grab tool both map evaluated vertices back onto
    the base mesh one-for-one, which a subdivision surface would break.
    """
    off = []
    for m in ob.modifiers:
        if m.type in DISPLAY_MODS and m.show_viewport:
            m.show_viewport = False
            off.append(m)
    try:
        yield
    finally:
        for m in off:
            m.show_viewport = True


MOD_ORDER = ('ARMATURE', 'CLOTH', 'SUBSURF', 'SOLIDIFY')


def order_modifiers(ob):
    """Deform, then solve, then smooth, then thicken.

    The subdivision has to sit after the cloth or the solver runs on the
    subdivided mesh instead of the cage - same result, many times the cost.
    """
    desired = []
    for t in MOD_ORDER:
        desired += [m for m in ob.modifiers if m.type == t]
    desired += [m for m in ob.modifiers if m.type not in MOD_ORDER]
    try:
        with bpy.context.temp_override(object=ob, active_object=ob):
            for i, m in enumerate(desired):
                if ob.modifiers.find(m.name) != i:
                    bpy.ops.object.modifier_move_to_index(modifier=m.name, index=i)
    except Exception as e:
        print("[clothing_design] modifier ordering failed:", e)


def add_subdivision(ob, levels, render_levels):
    mod = next((m for m in ob.modifiers if m.type == 'SUBSURF'), None)
    if levels <= 0 and render_levels <= 0:
        if mod:
            ob.modifiers.remove(mod)
        return None
    if mod is None:
        mod = ob.modifiers.new("CD_Subdivision", 'SUBSURF')
    mod.subdivision_type = 'CATMULL_CLARK'
    mod.levels = levels
    mod.render_levels = max(levels, render_levels)
    mod.use_creases = True
    try:
        mod.boundary_smooth = 'PRESERVE_CORNERS'
    except Exception:
        pass
    order_modifiers(ob)
    return mod


def bake_shape(context, ob):
    """Copy the simulated shape into the base mesh."""
    with sim_cage_only(ob):
        context.view_layer.update()
        dg = context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except Exception:
            return False
        if len(me.vertices) != len(ob.data.vertices):
            ev.to_mesh_clear()
            return False
        coords = [v.co.copy() for v in me.vertices]
        ev.to_mesh_clear()
    for v, c in zip(ob.data.vertices, coords):
        v.co = c
    ob.data.update()
    return True


def weld_seams(ob, max_gap):
    """Close every stitch: each sewing edge's two ends are merged at their
    midpoint. Distance-based merging alone leaves stitches wider than the
    threshold open, so the seam has to be followed explicitly."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    sew = [e for e in bm.edges if not e.link_faces]
    parent = {}

    def find(v):
        root = v
        while parent.get(root, root) is not root:
            root = parent[root]
        while parent.get(v, v) is not v:          # path compression
            parent[v], v = root, parent[v]
        return root

    skipped = 0
    for e in sew:
        a, b = e.verts
        if (a.co - b.co).length > max_gap:
            skipped += 1
            continue
        ra, rb = find(a), find(b)
        if ra is not rb:
            parent[rb] = ra

    groups = {}
    for e in sew:
        for v in e.verts:
            groups.setdefault(find(v), set()).add(v)

    targetmap = {}
    merged = 0
    for root, members in groups.items():
        if len(members) < 2:
            continue
        mid = Vector((0, 0, 0))
        for v in members:
            mid += v.co
        mid /= len(members)
        root.co = mid
        for v in members:
            if v is not root:
                targetmap[v] = root
                merged += 1
    if targetmap:
        bmesh.ops.weld_verts(bm, targetmap=targetmap)

    leftovers = [e for e in bm.edges if not e.link_faces]
    if leftovers:
        bmesh.ops.delete(bm, geom=leftovers, context='EDGES')
    stray = [v for v in bm.verts if not v.link_edges]
    if stray:
        bmesh.ops.delete(bm, geom=stray, context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()
    return merged, skipped


def close_stray_holes(ob, stretch=2.5, tiny=12):
    """Fill boundary loops left behind by the weld.

    A real opening - neck, cuff, hem - has edges at the mesh resolution. A slit
    left by a stitch that had to span a long gap has edges several times that,
    and corner junctions leave holes of only a few edges. Both get filled; the
    genuine openings are left alone.
    """
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.edges.ensure_lookup_table()

    lengths = sorted(e.calc_length() for e in bm.edges)
    if not lengths:
        bm.free()
        return 0
    median = lengths[len(lengths) // 2]

    bnd = [e for e in bm.edges if len(e.link_faces) == 1]
    adj = {}
    for e in bnd:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    seen, loops = set(), []
    for e in bnd:
        if e in seen:
            continue
        stack, comp = [e], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            for v in x.verts:
                for y in adj[v]:
                    if y not in seen:
                        stack.append(y)
        loops.append(comp)

    filled = 0
    for comp in loops:
        mean_len = sum(e.calc_length() for e in comp) / len(comp)
        if mean_len > median * stretch or len(comp) <= tiny:
            try:
                bmesh.ops.holes_fill(bm, edges=comp, sides=0)
                filled += 1
            except Exception:
                pass
    if filled:
        tris = [f for f in bm.faces if len(f.verts) > 4]
        if tris:
            bmesh.ops.triangulate(bm, faces=tris)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        me.update()
    bm.free()
    return filled


def add_thickness(ob, thickness):
    mod = next((m for m in ob.modifiers if m.type == 'SOLIDIFY'), None)
    if thickness <= 0.0:
        if mod:
            ob.modifiers.remove(mod)
        return None
    if mod is None:
        mod = ob.modifiers.new("CD_Thickness", 'SOLIDIFY')
    mod.thickness = thickness
    mod.offset = 0.0
    mod.use_even_offset = False      # blows up on tight folds
    mod.use_rim = True
    mod.use_quality_normals = True
    order_modifiers(ob)
    return mod


def smooth_skin_weights(ob, arm, iterations=20, factor=0.5, min_weight=1e-4):
    """Blend bone influences across neighbouring vertices.

    The weight transfer maps each vertex to the nearest body polygon, so at the
    crotch - where the two thighs nearly touch - neighbouring vertices land on
    opposite legs. As the legs separate those neighbours fly apart and tear the
    garment open. Blender's vertex_group_smooth operator does nothing when
    driven headlessly, so the smoothing is done here directly.
    """
    bones = {b.name for b in arm.data.bones}
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    bone_groups = {i for i, n in names.items() if n in bones}
    if not bone_groups:
        return 0

    me = ob.data
    adj = [[] for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)

    W = [{g.group: g.weight for g in v.groups if g.group in bone_groups}
         for v in me.vertices]

    for _ in range(iterations):
        nxt = []
        for i, w in enumerate(W):
            neigh = adj[i]
            if not neigh:
                nxt.append(w)
                continue
            acc = {}
            for j in neigh:
                for k, val in W[j].items():
                    acc[k] = acc.get(k, 0.0) + val
            inv = 1.0 / len(neigh)
            new = {}
            for k in set(w) | set(acc):
                v = (1.0 - factor) * w.get(k, 0.0) + factor * acc.get(k, 0.0) * inv
                if v > min_weight:
                    new[k] = v
            nxt.append(new)
        W = nxt

    groups = {i: ob.vertex_groups[i] for i in bone_groups}
    changed = 0
    for i, w in enumerate(W):
        total = sum(w.values())
        if total <= 1e-9:
            continue
        had = {g.group for g in me.vertices[i].groups if g.group in bone_groups}
        for k, val in w.items():
            groups[k].add([i], val / total, 'REPLACE')
        for k in had - set(w):
            groups[k].remove([i])
        changed += 1
    return changed


def bind_to_armature(context, ob, av):
    """Transfer skin weights from the avatar so the garment follows the rig."""
    from . import avatar as av_mod
    arm = av_mod.find_armature(av)
    if arm is None:
        return False, "avatar has no armature"

    for vg in list(ob.vertex_groups):
        if vg.name in {b.name for b in arm.data.bones}:
            ob.vertex_groups.remove(vg)

    prev_active = context.view_layer.objects.active
    prev_sel = [o for o in context.selected_objects]
    try:
        for o in prev_sel:
            o.select_set(False)
        av.select_set(True)
        ob.select_set(True)
        context.view_layer.objects.active = av
        with context.temp_override(object=av, active_object=av,
                                   selected_objects=[av, ob],
                                   selected_editable_objects=[av, ob]):
            bpy.ops.object.data_transfer(
                data_type='VGROUP_WEIGHTS',
                use_create=True,
                vert_mapping='POLYINTERP_NEAREST',
                layers_select_src='ALL',
                layers_select_dst='NAME',
                mix_mode='REPLACE')
    except Exception as e:
        return False, "weight transfer failed: %s" % e
    finally:
        for o in context.selected_objects:
            o.select_set(False)
        for o in prev_sel:
            try:
                o.select_set(True)
            except Exception:
                pass
        context.view_layer.objects.active = prev_active

    mod = next((m for m in ob.modifiers if m.type == 'ARMATURE'), None)
    if mod is None:
        mod = ob.modifiers.new("CD_Armature", 'ARMATURE')
    mod.object = arm
    order_modifiers(ob)

    smooth_skin_weights(ob, arm)
    return True, "bound to %s" % arm.name


def close_seams(context, ob):
    """Freeze the stitched shape, weld the seams into real shared edges and put a
    fresh cloth solver on the result. Without this the sewing springs keep pulling
    for the rest of the simulation and crush the garment into wrinkles."""
    scn = context.scene
    bake_shape(context, ob)
    for mod in list(ob.modifiers):
        if mod.type == 'CLOTH':
            ob.modifiers.remove(mod)
    merged, skipped = weld_seams(ob, scn.cd.weld_dist)
    setup_cloth(context, ob)
    for mod in ob.modifiers:
        if mod.type == 'CLOTH':
            mod.settings.shrink_min = scn.cd.shrink
    # Force the fresh solver to initialise at this frame. Stepping straight on to
    # the next frame leaves the new cache uninitialised and the garment drops off
    # the body in a single step.
    scn.frame_set(scn.frame_current)
    try:
        dg = context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        ev.to_mesh()
        ev.to_mesh_clear()
    except Exception:
        pass
    return merged, skipped


def set_gravity(ob, factor):
    for mod in ob.modifiers:
        if mod.type == 'CLOTH':
            try:
                mod.settings.effector_weights.gravity = factor
            except Exception:
                pass
