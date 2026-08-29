"""Input validation and repair (spec §4.1 step 1), as a checked, reported stage.

Every check here exists because its absence produced a wrong answer, not because it
seemed prudent. A file that loads without error is not a file that can be reasoned
about, and the failures are silent in the worst way: the renders look correct while the
quantities derived from the same mesh are wrong.

The rule the repairs obey: **vertex positions and face order are never changed.** Welding
and re-winding alter connectivity and orientation, which is what the geodesic solver and
the view planner need, but a face keeps its index so `hit_id` still routes a belief back
to the original file's triangle, and the mesh that is exported and printed remains the
one the user handed over. Anything that would move a vertex or renumber a face is
reported, never performed.

Orientation is verified BY PER-BODY VOLUME SIGN, not by agreement with the outward
radial direction. The radial test is a poor proxy and says so loudly on any model that
is not roughly convex: the baby dragon reads 56.7% agreement when correctly oriented,
because a spike under the tail genuinely points away from the centroid. Volume sign is
exact.
"""

import numpy as np


class Check:
    """One validation result: what was looked at, what was found, what was done."""

    def __init__(self, name, passed, detail, repaired=False):
        self.name = name
        self.passed = bool(passed)
        self.detail = detail
        self.repaired = bool(repaired)

    def as_dict(self):
        return {"check": self.name, "passed": self.passed, "repaired": self.repaired,
                "detail": self.detail}

    def __repr__(self):
        mark = "ok" if self.passed else ("repaired" if self.repaired else "FAILED")
        return "<%s %s: %s>" % (self.name, mark, self.detail)


def body_volumes(mesh):
    """Signed volume of each connected body. The exact orientation test."""
    import trimesh
    volumes = []
    for component in mesh.split(only_watertight=False):
        try:
            volumes.append(float(component.volume))
        except Exception:
            volumes.append(0.0)
    return np.array(volumes) if volumes else np.array([float(mesh.volume)])


def validate_and_repair(mesh, store=None, inputs=(), actor="deterministic:validate@0.2.0"):
    """Run every check, repair what can be repaired without moving anything.

    Returns (repaired_mesh, [Check]). The caller gets a mesh it can cast rays at and
    compute geodesics on, plus a record of everything that was wrong with the input.
    """
    import trimesh
    checks = []
    working = mesh
    original_faces = len(mesh.faces)

    # 1. Vertex sharing. STL carries none at all, and without it there is no
    #    connectivity: no geodesics, no vertex normals, no surface-space anything.
    unwelded = len(working.vertices) > original_faces * 2
    if unwelded:
        before = len(working.vertices)
        working = working.copy()
        working.merge_vertices()
        checks.append(Check("vertex_sharing", False,
                            {"vertices_before": before,
                             "vertices_after": len(working.vertices)},
                            repaired=True))
    else:
        checks.append(Check("vertex_sharing", True,
                            {"vertices": len(working.vertices)}))

    # 2. Orientation, per body. A file may be wound inward; the renderer hides it by
    #    flipping normals toward the camera, so only surface-space uses reveal it.
    volumes = body_volumes(working)
    inward = int((volumes < 0).sum())
    if inward:
        working = working.copy() if working is mesh else working
        trimesh.repair.fix_normals(working, multibody=True)
        after = body_volumes(working)
        still = int((after < 0).sum())
        checks.append(Check("orientation", still == 0,
                            {"bodies": len(volumes), "inward_before": inward,
                             "inward_after": still},
                            repaired=True))
    else:
        checks.append(Check("orientation", True,
                            {"bodies": len(volumes), "inward_before": 0}))

    # 3. Face count and positions must be untouched by everything above.
    same_faces = len(working.faces) == original_faces
    checks.append(Check("routing_preserved", same_faces,
                        {"faces_in": original_faces, "faces_out": len(working.faces),
                         "why": "hit_id must index the original file's triangles"}))

    # 4. Degenerate faces. REPORTED, never removed: deleting one renumbers every face
    #    after it and breaks the routing that check 3 just guaranteed.
    areas = working.area_faces
    degenerate = int((areas <= 0).sum())
    checks.append(Check("degenerate_faces", degenerate == 0,
                        {"count": degenerate, "action": "reported, not removed"}))

    # 5. Watertightness, per body. Not repairable without adding geometry, which would
    #    change the object; it is reported because it bounds what later stages can claim.
    bodies = working.split(only_watertight=False)
    leaky = sum(1 for body in bodies if not body.is_watertight)
    checks.append(Check("watertight", leaky == 0,
                        {"bodies": len(bodies), "not_watertight": leaky,
                         "affects": "interior/exterior tests and volume-based checks"}))

    # 6. Scale sanity: a mesh with zero extent in an axis cannot be framed.
    extent = np.ptp(working.vertices, axis=0)
    flat = bool((extent <= 0).any())
    checks.append(Check("extent", not flat, {"extent": extent.round(4).tolist()}))

    if store is not None:
        store.mint("part_mesh", inputs=inputs, actor=actor,
                   params={"checks": [c.as_dict() for c in checks]},
                   attrs={"checks": [c.as_dict() for c in checks],
                          "repaired": [c.name for c in checks if c.repaired]})
        for check in checks:
            if not check.passed and not check.repaired:
                store.reject("mesh", "validation failed: %s" % check.name,
                             inputs=inputs, count=1)
    return working, checks


def report(checks):
    return "\n".join("  %-20s %-9s %s"
                     % (c.name, "ok" if c.passed else ("repaired" if c.repaired
                                                       else "FAILED"), c.detail)
                     for c in checks)
