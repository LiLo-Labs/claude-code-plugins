"""Physical normalization and the intrinsic frame (spec §4.1, §4.2).

Two things happen here, and neither of them touches the geometry that will be exported.

The frame is a RECORD, not an edit. §4.1 says to record (R, t, s) as a `frame` entity,
and that is exactly what it is: a transform carried alongside the mesh so that reasoning
can happen in a normalized space while the file that gets painted and printed stays
byte-for-byte the thing the user handed over. A pipeline that rescales or recentres the
export has changed the object it was asked to describe.

World axes mean nothing to a painter (§4.2). "The left greave" and "the upper third of
the cloak" resolve through an object-owned frame or they do not resolve at all. The hull
OBB supplies an unsigned axis triad; PCA is deliberately not used, being sign-ambiguous
and unstable on near-symmetric bodies -- which is most of what gets painted.
"""

import numpy as np


class Frame:
    """An intrinsic frame: a rotation, a translation, a scale, and axis names.

    `to_local` maps world coordinates into the normalized frame. `scale` is uniform by
    construction -- anisotropic scaling is prohibited (§4.1) because it destroys
    geodesic distance, and every physical threshold downstream is a geodesic length.
    """

    def __init__(self, rotation, translation, scale, extent_mm, axis_names=None,
                 size_source="declared", size_uncertainty=None):
        self.rotation = np.asarray(rotation, dtype=float)      # 3x3, rows are axes
        self.translation = np.asarray(translation, dtype=float)
        self.scale = float(scale)
        self.extent_mm = np.asarray(extent_mm, dtype=float)
        self.axis_names = axis_names or {}
        self.size_source = size_source
        self.size_uncertainty = size_uncertainty
        self.symmetry = None

    def to_local(self, points):
        return (np.asarray(points) - self.translation) @ self.rotation.T * self.scale

    def to_world(self, points):
        return np.asarray(points) / self.scale @ self.rotation + self.translation

    def direction_to_world(self, vector):
        return np.asarray(vector, dtype=float) @ self.rotation

    @property
    def diagonal_mm(self):
        return float(np.linalg.norm(self.extent_mm))

    def working_mesh(self, mesh, store=None, inputs=()):
        """A copy of the mesh expressed in this frame's millimetres. RAY TARGET ONLY.

        Every length above this line is in millimetres and every length below it is in
        whatever units the file happened to use. Keeping both in play was a live bug:
        the band gate compared a footprint in file units against a wavelength in
        millimetres, so on a model whose file units ran 1.48 to the millimetre every
        gate was wrong by that factor, and the dragon's ladder collapsed to its finest
        rung. One conversion, in one place, and the ambiguity is gone.

        The original mesh is never modified and is what gets painted and exported. This
        copy exists so rays can be cast in the units the rest of the system speaks.
        """
        import trimesh
        from . import validate as validate_module
        working = trimesh.Trimesh(vertices=self.to_local(mesh.vertices),
                                  faces=mesh.faces, process=False)
        working, checks = validate_module.validate_and_repair(working, store=store,
                                                              inputs=inputs)
        self.checks = checks
        return working

    def params(self):
        return {"rotation": self.rotation.round(9).tolist(),
                "translation": self.translation.round(9).tolist(),
                "scale": round(self.scale, 12),
                "extent_mm": self.extent_mm.round(6).tolist(),
                "axis_names": self.axis_names, "size_source": self.size_source}


def oriented_axes(mesh):
    """An unsigned axis triad from the convex hull's oriented bounding box.

    The hull is used rather than the raw mesh so that surface detail -- a thousand
    barnacles, a spiked back -- cannot rotate the frame. What defines "up" for a
    painter is the silhouette, and the silhouette is the hull.
    """
    hull = mesh.convex_hull
    transform, extents = trimesh_obb(hull)
    rotation = transform[:3, :3].T
    centre = transform[:3, 3]
    order = np.argsort(extents)[::-1]
    return rotation[order], centre, np.asarray(extents)[order]


def trimesh_obb(hull):
    """(transform, extents) of the hull's oriented box, as trimesh reports it."""
    to_origin, extents = hull.bounding_box_oriented.primitive.transform, \
        hull.bounding_box_oriented.primitive.extents
    return np.asarray(to_origin, dtype=float), np.asarray(extents, dtype=float)


def build_frame(mesh, target_size_mm=None, estimator=None):
    """§4.1 steps 2-5 plus §4.2 step 1.

    When `target_size_mm` is absent the identity agent is asked, on overview renders
    only, to classify the object and estimate its real size with an uncertainty range
    (§4.1 step 3). The median is used and FLAGGED -- `size_source` records which
    happened, so every millimetre downstream can be traced to either a measurement or
    an admitted guess.
    """
    rotation, centre, extents = oriented_axes(mesh)
    hull_centroid = np.asarray(mesh.convex_hull.centroid, dtype=float)

    longest = float(extents.max())
    uncertainty, source = None, "declared"
    if target_size_mm is None:
        if estimator is None:
            scale, source = 1.0, "file_units_assumed"
        else:
            estimate = estimator()
            target_size_mm = float(estimate["median_mm"])
            uncertainty = estimate.get("range_mm")
            scale, source = target_size_mm / longest, "estimated"
    if target_size_mm is not None:
        scale = target_size_mm / longest
        source = source if source == "estimated" else "declared"

    extent_mm = extents * scale
    return Frame(rotation, hull_centroid, scale, extent_mm,
                 size_source=source, size_uncertainty=uncertainty)


def name_axes(frame, names):
    """Attach semantic axis names from the identity agent (§4.2 step 2)."""
    frame.axis_names = dict(names)
    return frame


def verify_symmetry(cue_left, cue_right):
    """§4.2 step 3: symmetry is confirmed by comparing CUE MAPS, never vertices.

    A mirrored mesh half can differ vertex for vertex and still be visually identical,
    and an asymmetric tessellation of a symmetric form is the normal case rather than an
    exotic one. What matters to a painter is whether the two halves LOOK the same, so
    that is what is measured. Returns agreement in [0, 1].
    """
    left = np.asarray(cue_left, dtype=float)
    right = np.asarray(cue_right, dtype=float)
    both = np.isfinite(left) & np.isfinite(right)
    if not both.any():
        return 0.0
    left, right = left[both], right[both]
    spread = float(np.hypot(left.std(), right.std()))
    if spread <= 0:
        return 1.0
    return float(np.clip(1.0 - np.abs(left - right).mean() / spread, 0.0, 1.0))
