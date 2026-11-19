# Clothing Design - arrangement and garment assembly.
#
# Flat pattern pieces are wrapped onto the measured body (MD's "arrangement"),
# joined into one mesh, and the seams become loose edges. Blender's cloth solver
# treats loose edges as sewing springs, so the panels stitch themselves together
# during simulation the way real pattern pieces are sewn together.
import bpy, bmesh, math, bisect
from collections.abc import Mapping
from mathutils import Vector
from . import avatar, patterns, props

GARMENT_PREFIX = "CD_Garment_"

TORSO_ANCHORS = {
    'TORSO_FRONT': (0.0, 1.0),
    'TORSO_LEFT':  (math.pi * 0.5, 1.0),
    'TORSO_BACK':  (math.pi, -1.0),
    'TORSO_RIGHT': (-math.pi * 0.5, 1.0),
    'HIP_FRONT':   (0.0, 1.0),
    'HIP_BACK':    (math.pi, -1.0),
}
LIMB_ANCHORS = {
    'ARM_L': ("arm_l", "farm_l"),
    'ARM_R': ("arm_r", "farm_r"),
    'LEG_L': ("thigh_l", "calf_l"),
    'LEG_R': ("thigh_r", "calf_r"),
}


# ---------------------------------------------------------------- arc mapping

class ArcMap:
    """Arc length along a body cross-section <-> angle, at one height."""

    def __init__(self, m, z, base_theta, ease, steps=200, span=math.pi * 1.25):
        self.th, self.s = [], []
        prev, acc = None, 0.0
        for i in range(steps + 1):
            th = base_theta - span + 2.0 * span * i / steps
            r = avatar.radius_at(m, z, th) + ease
            p = Vector((math.cos(th) * r, math.sin(th) * r))
            if prev is not None:
                acc += (p - prev).length
            prev = p
            self.th.append(th)
            self.s.append(acc)
        s0 = self._interp(self.th, self.s, base_theta)
        self.s = [x - s0 for x in self.s]

    @staticmethod
    def _interp(xs, ys, x):
        i = bisect.bisect_left(xs, x)
        if i <= 0:
            return ys[0]
        if i >= len(xs):
            return ys[-1]
        f = (x - xs[i - 1]) / max(1e-12, xs[i] - xs[i - 1])
        return ys[i - 1] * (1 - f) + ys[i] * f

    def arc_at(self, theta):
        return self._interp(self.th, self.s, theta)

    def theta_of(self, s):
        if s <= self.s[0]:
            return self.th[0]
        if s >= self.s[-1]:
            return self.th[-1]
        i = bisect.bisect_left(self.s, s)
        f = (s - self.s[i - 1]) / max(1e-12, self.s[i] - self.s[i - 1])
        return self.th[i - 1] * (1 - f) + self.th[i] * f


class LimbChain:
    """Polyline axis through one or more limb segments, with radius along it."""

    def __init__(self, m, keys):
        self.segs = []
        total = 0.0
        for k in keys:
            lp = m.get("limbs", {}).get(k)
            if lp:
                self.segs.append(lp)
                total += lp["len"]
        self.total = total

    def valid(self):
        return self.total > 1e-6

    def sample(self, t):
        """t in 0..1 along the whole chain -> (point, radius, axis)."""
        d = t * self.total
        for lp in self.segs:
            if d <= lp["len"] or lp is self.segs[-1]:
                p0, p1 = Vector(lp["p0"]), Vector(lp["p1"])
                ax = (p1 - p0)
                L = max(1e-9, ax.length)
                ax = ax / L
                u = d / lp["len"]
                return p0 + ax * d, avatar.limb_radius_at(lp, min(1.0, max(0.0, u))), ax
            d -= lp["len"]
        p0 = Vector(self.segs[0]["p0"])
        return p0, avatar.limb_radius_at(self.segs[0], 0.0), Vector((0, 0, -1))


# ---------------------------------------------------------------- wrapping

def _dir(fwd, side, th):
    return fwd * math.cos(th) + side * math.sin(th)


def piece_transform(ob, m, fwd, side):
    """Return f(Vector local) -> Vector world for one pattern piece."""
    f = _piece_transform(ob, m, fwd, side)
    if ob.cd.anchor == 'FREE' or m is None:
        return f                     # matrix_world already carries the scale
    # Width / Length (and the garment's Size) live in the object scale; the
    # pattern is in the local XZ plane
    sx, sz = ob.scale.x, ob.scale.z
    if abs(sx - 1.0) < 1e-6 and abs(sz - 1.0) < 1e-6:
        return f
    return lambda p: f(Vector((p.x * sx, p.y, p.z * sz)))


def _piece_transform(ob, m, fwd, side):
    cd = ob.cd
    shift = Vector(cd.shift)

    if cd.anchor == 'FREE' or m is None:
        mw = ob.matrix_world.copy()
        return lambda p: mw @ p

    if cd.anchor in LIMB_ANCHORS:
        chain = LimbChain(m, LIMB_ANCHORS[cd.anchor])
        if not chain.valid():
            mw = ob.matrix_world.copy()
            return lambda p: mw @ p
        # outward direction: away from the body axis at the limb root
        root = Vector(chain.segs[0]["p0"])
        c = avatar.center_at(m, root.z)
        out = Vector((root.x - c.x, root.y - c.y, 0.0))
        if out.length < 1e-6:
            out = side.copy()
        out.normalize()
        spin = cd.spin
        ease = cd.ease
        wrap = cd.wrap

        base_t = cd.height          # fraction along the limb of the piece's centre
        # Reference radius taken once at the piece's centre. Deriving the wrap
        # angle from the local radius instead makes the tube spiral as the limb
        # tapers, so the fabric overlaps itself and self-collision shreds it.
        _p, _r, _a = chain.sample(max(0.0, min(1.0, base_t)))
        r_ref = max(1e-4, _r + ease)
        taper = cd.taper

        def limb_f(p):
            t = max(-0.25, min(1.25, base_t + (-p.z) / chain.total))
            pos, r, ax = chain.sample(max(0.0, min(1.0, t)))
            if t < 0.0 or t > 1.0:                       # extend past the ends
                pos = pos + ax * ((t - (0.0 if t < 0 else 1.0)) * chain.total)
            u = out - ax * out.dot(ax)
            if u.length < 1e-6:
                u = side - ax * side.dot(ax)
            u.normalize()
            v = ax.cross(u)
            if v.dot(fwd) > 0.0:
                v = -v
            rr = r + ease
            # A constant angular span keeps a sleeve from spiralling, but a
            # trouser leg's pattern already tapers with the limb, so following
            # the local radius is what keeps its top edge the drafted length.
            r_ang = r_ref * (1.0 - taper) + rr * taper
            th = spin + (p.x / max(1e-4, r_ang)) * wrap
            wrapped = pos + (u * math.cos(th) + v * math.sin(th)) * rr
            if wrap < 0.999:
                # blend to a flat plate tangent to the limb; without this a Wrap of
                # 0 folds every vert onto one angle and the piece collapses to a line
                d0 = u * math.cos(spin) + v * math.sin(spin)
                tangent = -u * math.sin(spin) + v * math.cos(spin)
                flat = pos + d0 * rr + tangent * p.x
                wrapped = flat.lerp(wrapped, wrap)
            return wrapped + shift

        return limb_f

    base_theta, xsign = TORSO_ANCHORS.get(cd.anchor, (0.0, 1.0))
    base_theta += cd.spin
    clamp = math.radians(95.0)   # past this the panel leaves the body tangentially
                                 # instead of wrapping onto the opposite side
    # Above the shoulder joint the cross-section shrinks to the neck, so a panel
    # mapped by arc length there would wind around the throat. Hold the section
    # at its shoulder size instead: the panel floats over the shoulder shelf and
    # the simulation drops it onto the shoulders, which is where a collar belongs.
    z_cap = avatar.z_of(m, "shoulder") + 0.02
    z_anchor = m["zmin"] + cd.height * m["height"]
    ease, wrap = cd.ease, cd.wrap
    cache = {}

    def torso_f(p):
        z = z_anchor + p.z
        zq = min(z, z_cap)
        key = round(zq * 200.0)                           # 5 mm height buckets
        am = cache.get(key)
        if am is None:
            am = ArcMap(m, zq, base_theta, ease)
            cache[key] = am
        s = p.x * xsign
        c = avatar.center_at(m, zq)
        c.z = z
        s_max = am.arc_at(base_theta + clamp)
        s_min = am.arc_at(base_theta - clamp)
        if s > s_max or s < s_min:
            th_c = base_theta + (clamp if s > s_max else -clamp)
            r_c = avatar.radius_at(m, zq, th_c) + ease
            edge = c + _dir(fwd, side, th_c) * r_c
            tang = _dir(fwd, side, th_c + math.pi * 0.5)
            wrapped = edge + tang * (s - (s_max if s > s_max else s_min))
            th = th_c
        else:
            th = am.theta_of(s)
            r = avatar.radius_at(m, zq, th) + ease
            wrapped = c + _dir(fwd, side, th) * r
        if wrap < 0.999:
            r0 = avatar.radius_at(m, zq, base_theta) + ease
            flat = c + _dir(fwd, side, base_theta) * r0 + _dir(fwd, side, base_theta + math.pi * 0.5) * s
            wrapped = flat.lerp(wrapped, wrap)
        return wrapped + shift

    return torso_f


# ---------------------------------------------------------------- assembly

def garment_pieces(context, garment=None):
    g = garment or context.scene.cd.garment_name
    return [ob for ob in context.scene.objects
            if ob.cd.is_pattern and ob.cd.garment == g]


def garment_object(context, garment=None, create=True):
    g = garment or context.scene.cd.garment_name
    name = GARMENT_PREFIX + g
    ob = bpy.data.objects.get(name)
    if ob is None and create:
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        ob.cd.is_garment = True
        ob.cd.garment = g
        me.materials.append(patterns.fabric_material())
        patterns.move_to_collection(ob, patterns.get_collection(context, patterns.GARMENT_COLL))
    return ob


def activate_garment(context, garment):
    """Select an arranged garment by its OpenSew name or Blender mesh object."""
    ob = garment_object(context, garment, create=False) if isinstance(garment, str) else garment
    if ob is None or not ob.cd.is_garment or context.scene.objects.get(ob.name) != ob:
        raise ValueError("Select an arranged garment in the current scene")
    context.scene.cd.active_garment = bpy.data.objects.find(ob.name)
    return ob


def _pattern_data(spec):
    if not isinstance(spec, Mapping) or not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ValueError("Pattern specification needs a non-empty garment name")
    pieces = spec.get("pieces", [])
    seams = spec.get("seams", [])
    if not isinstance(pieces, (list, tuple)) or not pieces:
        raise ValueError("Provide at least one pattern piece")
    if not isinstance(seams, (list, tuple)):
        raise ValueError("Seams must be an array")
    anchors = {entry[0] for entry in props.ANCHORS}
    prepared = {}
    for piece in pieces:
        if not isinstance(piece, Mapping):
            raise ValueError("Each piece must be an object")
        name = piece.get("name")
        if not isinstance(name, str) or not name.strip() or name in prepared:
            raise ValueError("Each piece needs a unique non-empty name")
        anchor = piece.get("anchor", "TORSO_FRONT")
        if not isinstance(anchor, str) or anchor not in anchors:
            raise ValueError(f"Unknown anchor on {name}: {anchor!r}")
        segments = {}
        edges = piece.get("segs")
        if not isinstance(edges, (list, tuple)):
            raise ValueError(f"Provide an ordered edge array for {name}")
        for label, points in edges:
            if not isinstance(label, str) or not label.strip() or label in segments:
                raise ValueError(f"Each edge on {name} needs a unique non-empty name")
            coords = [Vector(point) for point in points]
            if len(coords) < 2 or any(len(point) != 2 or not all(map(math.isfinite, point))
                                      for point in coords):
                raise ValueError(f"{name}.{label} needs finite 2D points")
            segments[label] = coords
        outline = list(segments.values())
        if len(outline) < 2 or any((points[-1] - outline[(i + 1) % len(outline)][0]).length > 1e-6
                                   for i, points in enumerate(outline)):
            raise ValueError(f"Edges on {name} must form a closed outline in order")
        prepared[name] = (piece, segments)

    for seam in seams:
        if not isinstance(seam, (list, tuple)) or len(seam) not in (4, 5):
            raise ValueError("Each seam needs two piece/edge pairs and optional flip")
        a, edge_a, b, edge_b = seam[:4]
        if (not all(isinstance(key, str) for key in seam[:4])
                or edge_a not in prepared.get(a, ({}, {}))[1]
                or edge_b not in prepared.get(b, ({}, {}))[1]):
            raise ValueError(f"Seam references an unknown piece or edge: {seam!r}")
        if len(seam) == 5 and type(seam[4]) is not bool:
            raise ValueError("Seam flip must be true or false when supplied")
    if type(spec.get("shoulder_pins", True)) is not bool:
        raise ValueError("shoulder_pins must be true or false")
    return prepared, seams


def draft_garment(context, spec, *, report=None):
    """Create a garment from a JSON-compatible pattern specification in metres."""
    from . import sim

    scn = context.scene
    if scn.cd.avatar is None:
        raise ValueError("Set an avatar before drafting")
    pieces, seams = _pattern_data(spec)
    base = spec["name"]
    name = base
    i = 1
    while garment_pieces(context, name) or garment_object(context, name, create=False):
        i += 1
        name = f"{base}{i}"

    existing = sim.garment_layers(context)
    seam_start = len(scn.cd.seams)
    made = {}
    garment = None
    try:
        with props.muted():
            for label, (piece, segments) in pieces.items():
                made[label] = patterns.create_panel(
                    context, f"{name}_{label}", list(segments.items()), garment=name,
                    anchor=piece.get("anchor", "TORSO_FRONT"), height=piece.get("height", 0.5),
                    ease=piece.get("ease", 0.02), wrap=piece.get("wrap", 1.0),
                    spin=piece.get("spin", 0.0), taper=piece.get("taper", 0.0))
            for entry in seams:
                a, edge_a, b, edge_b = entry[:4]
                seam = scn.cd.seams.add()
                seam.name = f"{a}.{edge_a} - {b}.{edge_b}"
                seam.obj_a, seam.seg_a = made[a], edge_a
                seam.obj_b, seam.seg_b = made[b], edge_b
                if len(entry) == 5:
                    seam.flip = entry[4]
                    seam.auto_flip = False

        garment = garment_object(context, name)
        garment.cd.layer = max((ob.cd.layer for ob in existing), default=-1) + 1
        garment.cd.shoulder_pins = spec.get("shoulder_pins", True)
        sync_garment(context, report, name)
        sim.setup_cloth(context, garment)
        sim.ensure_collider(context, scn.cd.avatar)
        sim.setup_layers(context)
        return activate_garment(context, garment)
    except Exception:
        for index in range(len(scn.cd.seams) - 1, seam_start - 1, -1):
            scn.cd.seams.remove(index)
        for ob in list(made.values()) + ([garment] if garment is not None else []):
            mesh = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise


def _chain_bmverts(ob, seg, vmap):
    idx = patterns.segment_verts(ob, seg)
    return [vmap[i] for i in idx if i in vmap]


def under_bvh(context, garment):
    """BVH of the body plus every garment worn under this one, at their
    current shapes.

    An outer garment arranged against the bare body starts only its own ease
    away from the skin, while the shirt beneath it occupies a shell several
    times thicker than that - so the jacket is laid out inside the shirt and
    the simulation has no way to sort that out afterwards. Arranging against
    what is actually underneath is what makes layering hold.
    """
    from mathutils.bvhtree import BVHTree
    scn = context.scene
    av = scn.cd.avatar
    ob_g = bpy.data.objects.get(GARMENT_PREFIX + garment)
    layer = ob_g.cd.layer if ob_g is not None else 0
    unders = [o for o in scn.objects
              if o.cd.is_garment and o.data and len(o.data.vertices)
              and o.cd.garment != garment and o.cd.layer < layer]
    if not unders:
        return avatar.body_bvh(context)
    from . import sim as _sim
    verts, tris = [], []
    for src in [av] + unders:
        if src is None or src.type != 'MESH':
            continue
        # Measure the under-layer by its simulation cage, not its display
        # shape. A finalized garment carries subdivision and solidify, and
        # arranging the next layer against that inflated shell laid a
        # t-shirt 20 cm low - the same garment sewn over an unfinalized one
        # sat correctly. What is underneath should not depend on whether it
        # happens to have been finalized yet.
        with _sim.sim_cage_only(src):
            context.view_layer.update()
            dg = context.evaluated_depsgraph_get()
            ev = src.evaluated_get(dg)
            try:
                me = ev.to_mesh()
                me.calc_loop_triangles()
            except Exception:
                continue
            mw = ev.matrix_world
            base = len(verts)
            verts += [mw @ v.co for v in me.vertices]
            tris += [tuple(base + i for i in t.vertices) for t in me.loop_triangles]
            ev.to_mesh_clear()
    if not tris:
        return avatar.body_bvh(context)
    return BVHTree.FromPolygons(verts, tris)


def sync_garment(context, report=None, garment=None):
    """Rebuild the 3D garment from its pattern pieces."""
    scn = context.scene
    g = garment or scn.cd.garment_name
    pieces = garment_pieces(context, g)
    if not pieces:
        if report:
            report({'WARNING'}, "No pattern pieces in garment '%s'" % g)
        return None

    m = avatar.measure(context)
    fwd, side = avatar.basis(scn.cd.facing)
    bvh = under_bvh(context, g) if scn.cd.keep_off_body else None

    bm = bmesh.new()
    dl = bm.verts.layers.deform.verify()
    vmaps = {}
    group_names = []
    for ob in pieces:
        gi = len(group_names)
        group_names.append(ob.name)
        f = piece_transform(ob, m, fwd, side)
        vmap = {}
        clear = max(ob.cd.ease, 0.002)
        for v in ob.data.vertices:
            p = f(v.co.copy())
            if bvh is not None:
                p = avatar.push_out(p, bvh, clear)
            nv = bm.verts.new(p)
            nv[dl][gi] = 1.0
            vmap[v.index] = nv
        bm.verts.ensure_lookup_table()
        for poly in ob.data.polygons:
            try:
                bm.faces.new([vmap[i] for i in poly.vertices])
            except ValueError:
                pass
        vmaps[ob.name] = vmap

    # --- sewing springs: loose edges between paired segment chains
    n_sew = 0
    for seam in scn.cd.seams:
        if not seam.enabled or not seam.obj_a or not seam.obj_b:
            continue
        if seam.obj_a.name not in vmaps or seam.obj_b.name not in vmaps:
            continue
        A = _chain_bmverts(seam.obj_a, seam.seg_a, vmaps[seam.obj_a.name])
        B = _chain_bmverts(seam.obj_b, seam.seg_b, vmaps[seam.obj_b.name])
        if len(A) < 2 or len(B) < 2:
            continue
        rev = seam.flip
        if seam.auto_flip:
            def _cost(bb):
                n, tot = 9, 0.0
                for k in range(n):
                    u = k / (n - 1)
                    pa = A[min(len(A) - 1, int(round(u * (len(A) - 1))))]
                    pb = bb[min(len(bb) - 1, int(round(u * (len(bb) - 1))))]
                    tot += (pa.co - pb.co).length
                return tot
            rev = _cost(list(reversed(B))) < _cost(B)
        Bc = list(reversed(B)) if rev else B
        N = max(len(A), len(Bc))
        made = set()
        for i in range(N):
            t = i / (N - 1)
            a = A[min(len(A) - 1, int(round(t * (len(A) - 1))))]
            b = Bc[min(len(Bc) - 1, int(round(t * (len(Bc) - 1))))]
            if a is b:
                continue
            key = (a, b) if id(a) < id(b) else (b, a)
            if key in made:
                continue
            made.add(key)
            try:
                bm.edges.new((a, b))
                n_sew += 1
            except ValueError:
                pass

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

    ob = garment_object(context, g)
    if ob.name not in scn.objects:
        patterns.move_to_collection(ob, patterns.get_collection(context, patterns.GARMENT_COLL))
    ob.matrix_world.identity()

    # keep modifiers, replace geometry
    for mod in ob.modifiers:
        if mod.type == 'CLOTH':
            try:
                mod.point_cache.frame_end = mod.point_cache.frame_start
            except Exception:
                pass
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    for name in group_names:
        ob.vertex_groups.new(name=name)

    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    if not ob.data.materials:
        ob.data.materials.append(patterns.fabric_material())
    for p in ob.data.polygons:
        p.use_smooth = True

    ob.cd.is_garment = True
    ob.cd.garment = g
    ob["cd_sewing_edges"] = n_sew
    try:
        from . import sim as _sim
        _sim.add_subdivision(ob, scn.cd.subdiv_levels, scn.cd.subdiv_render)
    except Exception as e:
        print("[clothing_design] subdivision failed:", e)
    if report:
        report({'INFO'}, "%s: %d verts, %d faces, %d sewing springs"
               % (ob.name, len(ob.data.vertices), len(ob.data.polygons), n_sew))
    return ob


def loose_edges(me):
    used = set()
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(len(vs)):
            used.add((min(vs[i], vs[i - 1]), max(vs[i], vs[i - 1])))
    return [e.index for e in me.edges
            if (min(e.vertices), max(e.vertices)) not in used]
