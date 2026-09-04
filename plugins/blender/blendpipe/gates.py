"""What a mesh has to survive before anyone is told it is finished.

The difference between a toy that drives Blender and something you can ship
assets from is entirely here. A language model looking at a render is easy to
please — a shape that reads correctly at 640px can still be a non-manifold
triangle soup at 400k faces with a 1.7x scale baked into the object transform,
and it will fail in the engine, in the slicer, or three weeks later in someone
else's hands.

So the render is for judging *whether it is the right thing*, and this file is
for proving *whether it is a usable thing*. Neither substitutes for the other.

Every check is measured inside Blender by bmesh, not inferred. `blocking` gates
mean the mesh does not leave; the rest are reported and the caller decides.
"""

import json

#: Executed inside Blender by `execute`. Sets `result` to the raw measurements.
#: Kept as one string rather than assembled from fragments so that what runs in
#: Blender is exactly what you can paste into its own console to debug.
PROBE = r'''
import bmesh, math, bpy

names = TARGETS or [o.name for o in bpy.context.scene.objects if o.type == "MESH"]
report = {}

for name in names:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        continue

    # Measure the evaluated mesh: modifiers are part of what the user will
    # export, so a subdivision surface that quadruples the face count has to
    # count against the budget rather than hiding behind the cage.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()

    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    boundary     = sum(1 for e in bm.edges if e.is_boundary)
    wire         = sum(1 for e in bm.edges if e.is_wire)
    loose_verts  = sum(1 for v in bm.verts if not v.link_edges)
    ngons        = sum(1 for f in bm.faces if len(f.verts) > 4)
    quads        = sum(1 for f in bm.faces if len(f.verts) == 4)
    tris         = sum(1 for f in bm.faces if len(f.verts) == 3)
    zero_area    = sum(1 for f in bm.faces if f.calc_area() < 1e-9)

    # Duplicate vertices are the single most common defect in generated meshes
    # and the one that silently ruins subdivision and UV unwrapping later.
    seen, doubles = {}, 0
    for v in bm.verts:
        key = (round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
        if key in seen:
            doubles += 1
        else:
            seen[key] = True

    # A closed mesh whose signed volume is negative has its normals inside out.
    volume = bm.calc_volume(signed=True)

    report[name] = {
        "verts": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "tris": tris, "quads": quads, "ngons": ngons,
        "quad_ratio": round(quads / len(bm.faces), 4) if bm.faces else 0.0,
        "non_manifold_edges": non_manifold,
        "boundary_edges": boundary,
        "wire_edges": wire,
        "loose_verts": loose_verts,
        "zero_area_faces": zero_area,
        "duplicate_verts": doubles,
        "watertight": non_manifold == 0 and boundary == 0 and wire == 0,
        "signed_volume": round(volume, 9),
        "inverted_normals": non_manifold == 0 and boundary == 0 and volume < 0,
        "uv_layers": [l.name for l in mesh.uv_layers],
        "material_slots": len([s for s in obj.material_slots if s.material]),
        "dimensions": [round(float(c), 5) for c in obj.dimensions],
        "scale": [round(float(c), 5) for c in obj.scale],
        "unapplied_scale": any(abs(c - 1.0) > 1e-4 for c in obj.scale),
        "location": [round(float(c), 5) for c in obj.location],
        "modifiers": [m.type for m in obj.modifiers],
    }
    bm.free()
    evaluated.to_mesh_clear()

result = report
'''


class Budget:
    """What this particular asset is allowed to be.

    Defaults are aimed at a real-time game asset, because that is the most
    demanding common case and it is easier to relax a budget than to notice a
    missing one. Print and render work override `watertight` and `max_faces`.
    """

    def __init__(self, **kwargs):
        self.max_faces = kwargs.get("max_faces", 100_000)
        self.min_quad_ratio = kwargs.get("min_quad_ratio", 0.0)
        self.require_watertight = kwargs.get("require_watertight", False)
        self.require_uvs = kwargs.get("require_uvs", False)
        self.max_dimension = kwargs.get("max_dimension")
        self.min_dimension = kwargs.get("min_dimension")
        self.allow_ngons = kwargs.get("allow_ngons", True)
        self.allow_unapplied_scale = kwargs.get("allow_unapplied_scale", False)

    def as_dict(self):
        return {k: v for k, v in vars(self).items()}


class Finding:
    __slots__ = ("obj", "check", "severity", "detail", "fix")

    def __init__(self, obj, check, severity, detail, fix):
        self.obj, self.check, self.severity = obj, check, severity
        self.detail, self.fix = detail, fix

    def as_dict(self):
        return {
            "object": self.obj, "check": self.check, "severity": self.severity,
            "detail": self.detail, "fix": self.fix,
        }


def evaluate(report, budget=None):
    """Turn raw measurements into findings, ordered worst first."""
    budget = budget or Budget()
    findings = []

    for name, m in (report or {}).items():
        if m["faces"] == 0:
            findings.append(Finding(
                name, "empty", "blocking",
                "the object has no faces at all",
                "the operation that was meant to build geometry did not; do not export this"))
            continue

        if m["non_manifold_edges"]:
            findings.append(Finding(
                name, "non_manifold", "blocking",
                "%d non-manifold edges" % m["non_manifold_edges"],
                "select non-manifold in edit mode (Select > All by Trait) and inspect; "
                "usually interior faces or a boundary that should have been bridged"))

        if m["zero_area_faces"]:
            findings.append(Finding(
                name, "degenerate", "blocking",
                "%d zero-area faces" % m["zero_area_faces"],
                "bmesh.ops.dissolve_degenerate, or Mesh > Clean Up > Degenerate Dissolve"))

        if m["duplicate_verts"]:
            findings.append(Finding(
                name, "duplicate_verts", "warning",
                "%d vertices sit on top of another" % m["duplicate_verts"],
                "Mesh > Merge > By Distance — do this before any UV or subdivision work"))

        if m["loose_verts"] or m["wire_edges"]:
            findings.append(Finding(
                name, "loose_geometry", "warning",
                "%d loose vertices, %d wire edges" % (m["loose_verts"], m["wire_edges"]),
                "Mesh > Clean Up > Delete Loose"))

        if m["inverted_normals"]:
            findings.append(Finding(
                name, "inverted_normals", "blocking",
                "closed mesh with negative signed volume — normals point inward",
                "Mesh > Normals > Recalculate Outside (Shift+N)"))

        if m["faces"] > budget.max_faces:
            findings.append(Finding(
                name, "polycount", "blocking",
                "%d faces against a budget of %d" % (m["faces"], budget.max_faces),
                "decimate or remesh; if the budget is wrong, say so rather than raising it silently"))

        if budget.require_watertight and not m["watertight"]:
            findings.append(Finding(
                name, "not_watertight", "blocking",
                "%d boundary edges — the mesh is open" % m["boundary_edges"],
                "close the holes; an open mesh has no volume and will not slice"))

        if budget.min_quad_ratio and m["quad_ratio"] < budget.min_quad_ratio:
            findings.append(Finding(
                name, "topology", "warning",
                "%.0f%% quads against a floor of %.0f%%"
                % (m["quad_ratio"] * 100, budget.min_quad_ratio * 100),
                "this is triangle soup; ask the backend for a quad remesh, or run "
                "a Remesh/QuadriFlow pass before this is called clean topology"))

        if not budget.allow_ngons and m["ngons"]:
            findings.append(Finding(
                name, "ngons", "warning",
                "%d n-gons" % m["ngons"],
                "triangulate or re-loop them; n-gons deform badly once rigged"))

        if budget.require_uvs and not m["uv_layers"]:
            findings.append(Finding(
                name, "no_uvs", "blocking",
                "no UV layer",
                "Smart UV Project at minimum; nothing can be textured without one"))

        if not budget.allow_unapplied_scale and m["unapplied_scale"]:
            findings.append(Finding(
                name, "unapplied_scale", "warning",
                "object scale is %s, not 1.0" % m["scale"],
                "Object > Apply > Scale (Ctrl+A) — unapplied scale breaks modifiers, "
                "physics and most exporters"))

        longest = max(m["dimensions"]) if m["dimensions"] else 0
        if budget.max_dimension and longest > budget.max_dimension:
            findings.append(Finding(
                name, "too_large", "warning",
                "longest side %.3f exceeds %.3f" % (longest, budget.max_dimension),
                "generated meshes arrive at arbitrary scale; set real dimensions before export"))
        if budget.min_dimension and longest < budget.min_dimension:
            findings.append(Finding(
                name, "too_small", "warning",
                "longest side %.3f is under %.3f" % (longest, budget.min_dimension),
                "generated meshes arrive at arbitrary scale; set real dimensions before export"))

    order = {"blocking": 0, "warning": 1}
    findings.sort(key=lambda f: (order.get(f.severity, 2), f.obj))
    return findings


def probe_code(targets=None):
    """The snippet to hand to `execute`, with its target list bound in."""
    return "TARGETS = %s\n%s" % (json.dumps(list(targets) if targets else None), PROBE)


def verdict(findings):
    blocking = [f for f in findings if f.severity == "blocking"]
    return {
        "passed": not blocking,
        "blocking": len(blocking),
        "warnings": len(findings) - len(blocking),
        "findings": [f.as_dict() for f in findings],
    }
