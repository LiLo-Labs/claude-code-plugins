"""The label field (spec §8).

A continuous function over the surface: f(p, r) -> Distribution[Label], for any surface
point and any query radius. Not a mesh attribute, not a texture, not a partition. This
is what makes I3 true -- scale is something a consumer ASKS at, never something the
store decided in advance -- and it is why a region can be named at two different radii
and still be the same region.

Two layers, and the separation is the point (§8.1, §8.2):

    evidence  -- append-only, authoritative, replayable. Every admitted observation,
                 with its exact surface point and everything about the look that
                 produced it. Never mutated. A correction is a LATER OBSERVATION, not
                 an edit, which is what keeps I5 intact and the run diffable.
    query     -- derived on demand. A kernel estimate at whatever radius was asked for,
                 over geodesic distance. Discards nothing and decides nothing; if it is
                 wrong it can be recomputed from the layer below.

Geodesic distance comes from the heat method, which needs manifold connectivity that the
raw file does not have -- STL carries no vertex sharing at all. The welded copy is a
`part_mesh` entity with a repair log (§4.1 step 1). The mesh that gets painted and
exported is never the welded one.
"""

import numpy as np


def quartic(u):
    """A compactly supported smoothing kernel. Zero beyond the query radius.

    Compact support is not an optimisation: an observation a hundred millimetres away
    must contribute exactly nothing to a one-millimetre query, or "at radius r" stops
    meaning anything.
    """
    inside = u < 1.0
    out = np.zeros_like(u)
    out[inside] = (1.0 - u[inside] ** 2) ** 2
    return out


class LabelField:
    """Evidence and the estimator over it."""

    def __init__(self, working_mesh, frame, policy, store=None, inputs=()):
        self.frame = frame
        self.policy = policy
        self.store = store
        self.mesh = working_mesh
        self._build_substrate(inputs)

        # Evidence layer. Parallel arrays rather than objects: there are millions of
        # these and every one of them is immutable once written.
        self.obs_point = []          # exact surface point, millimetres, frame-local
        self.obs_vertex = []         # nearest substrate vertex, for the estimator only
        self.obs_label = []          # integer index into self.labels
        self.obs_weight = []
        self.obs_band = []
        self.obs_id = []             # observation entity id -- provenance (§8.3)
        self.obs_gsd = []            # §8.1: every observation carries the conditions
        self.obs_incidence = []      #       it was made under, per observation
        self.obs_confidence = []
        self.obs_rig = []
        self.labels = []             # label index -> node id
        self._label_index = {}
        self._packed = None

    # ---------------------------------------------------------------- substrate

    def _build_substrate(self, inputs):
        """A manifold copy for geodesics, and the repair recorded as an entity."""
        # The working mesh from `Frame.working_mesh` is already welded and outward
        # oriented, and its repair is already an entity. Welding again here would mint a
        # second, misleading repair record for work that was not done twice.
        welded = self.mesh
        if len(welded.vertices) == 3 * len(welded.faces):
            welded = welded.copy()
            welded.merge_vertices()
            if self.store is not None:
                self.store.mint("part_mesh", inputs=inputs,
                                params={"repair": "merge_vertices (late)"},
                                attrs={"repair": "merge_vertices (late)",
                                       "note": "field received an unwelded mesh"})
        self.substrate = welded
        self.vertex_area = _vertex_areas(welded)
        self.total_area_mm2 = float(self.vertex_area.sum())
        self._solver = None
        self._tree = None
        self._neighbours = None
        self._mean_edge = 1.0
        self.bands = []

    @property
    def solver(self):
        if self._solver is None:
            import potpourri3d as pp3d
            self._solver = pp3d.MeshHeatMethodDistanceSolver(
                np.asarray(self.substrate.vertices, dtype=np.float64),
                np.asarray(self.substrate.faces, dtype=np.int32))
        return self._solver

    @property
    def tree(self):
        if self._tree is None:
            from scipy.spatial import cKDTree
            self._tree = cKDTree(self.substrate.vertices)
        return self._tree

    def nearest_vertex(self, points):
        return self.tree.query(np.atleast_2d(points))[1]

    # ---------------------------------------------------------------- evidence

    def label_index(self, node_id):
        if node_id not in self._label_index:
            self._label_index[node_id] = len(self.labels)
            self.labels.append(node_id)
        return self._label_index[node_id]

    def observe(self, points, label, weights, band_index, gsd=None, incidence=None,
                mask_confidence=None, rig_id="", ids=None):
        """Append admitted votes (§8.1). NEVER mutates.

        Corrections arrive as NEW observations with later timestamps rather than as
        edits, which is what keeps I5 intact and the run replayable and diffable. There
        is no code path in this class that overwrites an observation, and there must not
        be one.
        """
        points = np.atleast_2d(np.asarray(points, dtype=float))
        weights = np.asarray(weights, dtype=float).reshape(-1)
        if len(points) == 0:
            return 0
        count = len(points)
        index = self.label_index(label)
        self.obs_point.append(points)
        self.obs_vertex.append(self.nearest_vertex(points))
        self.obs_label.append(np.full(count, index, dtype=np.int32))
        self.obs_weight.append(weights)
        self.obs_band.append(np.full(count, int(band_index), dtype=np.int32))
        self.obs_id.append(np.array(ids if ids is not None
                                    else [""] * count, dtype=object))
        self.obs_gsd.append(_as_column(gsd, count))
        self.obs_incidence.append(_as_column(incidence, count))
        self.obs_confidence.append(_as_column(mask_confidence, count, default=1.0))
        self.obs_rig.append(np.array([rig_id] * count, dtype=object))
        self._packed = None
        return count

    def _pack(self):
        if self._packed is None:
            if not self.obs_vertex:
                self._packed = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int32),
                                np.zeros(0), np.zeros(0, dtype=np.int32))
            else:
                self._packed = (np.concatenate(self.obs_vertex),
                                np.concatenate(self.obs_label),
                                np.concatenate(self.obs_weight),
                                np.concatenate(self.obs_band))
        return self._packed

    @property
    def count(self):
        return int(sum(len(v) for v in self.obs_vertex))

    # ---------------------------------------------------------------- query API

    def distance_from(self, vertices):
        """Geodesic distance to every substrate vertex from one or more sources."""
        sources = np.atleast_1d(np.asarray(vertices)).astype(np.int64)
        if len(sources) == 1:
            return np.asarray(self.solver.compute_distance(int(sources[0])))
        return np.asarray(self.solver.compute_distance_multisource(
            [int(v) for v in sources]))

    def at(self, point, radius_mm, bands=None):
        """f(p, r) -> Distribution[Label]. The reference estimator of §8.2.

            f(p, r) ~ sum_obs w * K(geodesic(p, obs) / r) * [obs.band admissible at r]

        A band is admissible at a query radius when the radius can express it: asking at
        one millimetre must not be answered with evidence gathered about ten-millimetre
        structure, because the answer would be about a different thing than the question.
        """
        vertex, label, weight, band = self._pack()
        if len(vertex) == 0:
            return {}
        source = int(self.nearest_vertex(np.atleast_2d(point))[0])
        distance = self.distance_from(source)
        near = distance[vertex]
        admissible = np.ones(len(vertex), dtype=bool)
        if bands is not None:
            wavelengths = np.array([b.wavelength_mm for b in bands])
            admissible = wavelengths[band] <= radius_mm
        inside = admissible & (near < radius_mm)
        if not inside.any():
            return {}
        contribution = weight[inside] * quartic(near[inside] / float(radius_mm))
        totals = np.bincount(label[inside], weights=contribution,
                             minlength=len(self.labels))
        mass = totals.sum()
        if mass <= 0:
            return {}
        return {self.labels[i]: float(totals[i] / mass)
                for i in np.flatnonzero(totals)}

    def density(self, node_id, radius_mm, bands=None):
        """Unnormalized kernel density of one label over every surface vertex.

        The estimator of §8.2 evaluated everywhere at once. Distance is taken from that
        label's own observations by a single multi-source solve, which is the
        nearest-source approximation to the full sum: beyond the nearest observation of
        the same label the kernel is already decaying, so the nearest source carries the
        shape. The approximation is stated because it is one -- the exact
        per-observation sum is `at()`, which stays the reference estimator and is what
        §13 validates against.

        Mass is the label's total admitted weight in the neighbourhood, so a label
        supported by four thousand confident votes outweighs one supported by six
        marginal ones. That is the mechanism by which imperfect masks become a reliable
        answer: no single mask has to be right, because none of them is trusted alone.
        """
        vertex, label, weight, band = self._pack()
        index = self._label_index.get(node_id)
        if index is None or len(vertex) == 0:
            return np.zeros(len(self.substrate.vertices))
        mine = label == index
        if bands is not None:
            wavelengths = np.array([b.wavelength_mm for b in bands])
            mine = mine & (wavelengths[band] <= radius_mm)
        if not mine.any():
            return np.zeros(len(self.substrate.vertices))
        sources = np.unique(vertex[mine])
        distance = self.distance_from(sources)
        kernel = quartic(np.clip(distance / float(radius_mm), 0.0, 1.0))
        mass = np.bincount(vertex[mine], weights=weight[mine],
                           minlength=len(self.substrate.vertices))
        return self._diffuse(mass, radius_mm) * kernel

    def _diffuse(self, values, radius_mm):
        """Spread per-vertex mass over one kernel radius along the surface.

        A graph diffusion over mesh edges rather than a second heat solve per label. The
        number of rounds is set by the query radius in units of mean edge length, so the
        spread is a geodesic radius and not a hop count that somebody chose.
        """
        if self._neighbours is None:
            self._build_neighbours()
        indptr, indices = self._neighbours
        rounds = int(np.clip(round(float(radius_mm) / self._mean_edge), 1, 48))
        current = np.asarray(values, dtype=float)
        degree = np.maximum(np.diff(indptr), 1)
        for _ in range(rounds):
            summed = np.add.reduceat(current[indices], indptr[:-1])
            current = 0.5 * current + 0.5 * (summed / degree)
        return current

    def _build_neighbours(self):
        edges = self.substrate.edges_unique
        both = np.vstack([edges, edges[:, ::-1]])
        both = both[np.argsort(both[:, 0], kind="stable")]
        counts = np.bincount(both[:, 0], minlength=len(self.substrate.vertices))
        self._neighbours = (np.concatenate([[0], np.cumsum(counts)]), both[:, 1])
        self._mean_edge = float(np.linalg.norm(
            self.substrate.vertices[edges[:, 0]] - self.substrate.vertices[edges[:, 1]],
            axis=1).mean())

    def posterior(self, radius_mm, bands=None):
        """Every label's posterior over every vertex: shape (labels, vertices).

        The mixture, normalized per vertex, and the object the critic and the limiter
        actually read. Where two labels overlap they SHARE mass rather than one winning,
        which is what lets a disagreement survive to be measured (§8.4) instead of being
        settled by whichever mask happened to be fused last.
        """
        if not self.labels:
            return np.zeros((0, len(self.substrate.vertices)))
        stack = np.stack([self.density(node_id, radius_mm, bands)
                          for node_id in self.labels])
        total = stack.sum(axis=0)
        live = total > 0
        out = np.zeros_like(stack)
        out[:, live] = stack[:, live] / total[live]
        return out

    def region(self, node_id, radius_mm, bands=None):
        """Membership field for one label: its posterior share at every vertex."""
        index = self._label_index.get(node_id)
        if index is None:
            return np.zeros(len(self.substrate.vertices))
        return self.posterior(radius_mm, bands)[index]

    def membership_all(self, radius_mm, bands=None):
        return self.posterior(radius_mm, bands)

    def confidence(self, point, radius_mm, bands=None):
        """Dirichlet concentration at a point: how much evidence the belief rests on."""
        vertex, label, weight, band = self._pack()
        if len(vertex) == 0:
            return 0.0
        source = int(self.nearest_vertex(np.atleast_2d(point))[0])
        distance = self.distance_from(source)
        near = distance[vertex]
        inside = near < radius_mm
        if not inside.any():
            return 0.0
        return float(np.sum(weight[inside] * quartic(near[inside] / float(radius_mm))))

    def scale_variance(self, point, bands=None, radii=None):
        """Divergence of f(p, .) across bands (§8.4). The ONLY resampling signal.

        High variance means the object looks like different things at different scales
        at this point, which is either a real nested structure or a disagreement that
        more looking would settle. Either way it is where the next camera should aim.
        """
        bands = bands if bands is not None else self.bands
        if not bands:
            return 0.0
        radii = radii or [b.wavelength_mm for b in bands]
        posteriors = [self.at(point, r, bands) for r in radii]
        keys = sorted({k for p in posteriors for k in p})
        if len(keys) <= 1 or len(posteriors) < 2:
            return 0.0
        matrix = np.array([[p.get(k, 0.0) for k in keys] for p in posteriors])
        mean = matrix.mean(axis=0)
        mean = mean / max(mean.sum(), 1e-12)
        divergence = 0.0
        for row in matrix:
            row = row / max(row.sum(), 1e-12)
            live = row > 0
            divergence += float(np.sum(row[live] * np.log(row[live] / np.maximum(
                mean[live], 1e-12))))
        return divergence / len(posteriors)

    def disagreement(self, node_a, node_b, radius_mm):
        """Area-weighted overlap between two regions, in mm^2 (§8.4).

        Millimetres squared and not pixels, which is the whole reason it is comparable
        between two views at different zooms: neither side is expressed in the units of
        a camera.
        """
        a = self.region(node_a, radius_mm)
        b = self.region(node_b, radius_mm)
        return float(np.sum(np.minimum(a, b) * self.vertex_area))

    def boundary(self, node_id, radius_mm, level=0.5):
        """A level set of the continuous field as 3D polylines -- not a mesh edge loop.

        Because it is a level set it inherits no tessellation artifacts and moves
        smoothly as the query radius changes, which is what §8.3 requires of it and what
        a mesh edge loop can never do.
        """
        membership = self.region(node_id, radius_mm)
        faces = self.substrate.faces
        values = membership[faces]
        above = values > level
        crossing = np.flatnonzero(above.any(axis=1) & ~above.all(axis=1))
        segments = []
        vertices = self.substrate.vertices
        for face_index in crossing:
            face = faces[face_index]
            value = membership[face]
            points = []
            for i in range(3):
                j = (i + 1) % 3
                if (value[i] > level) == (value[j] > level):
                    continue
                span = value[j] - value[i]
                t = 0.0 if abs(span) < 1e-12 else (level - value[i]) / span
                points.append(vertices[face[i]] * (1 - t) + vertices[face[j]] * t)
            if len(points) == 2:
                segments.append(np.array(points))
        return segments

    def provenance(self, point, radius_mm):
        """Every observation id supporting the belief at a point (I7, §8.3)."""
        if not self.obs_id:
            return []
        vertex, _label, _weight, _band = self._pack()
        ids = np.concatenate(self.obs_id)
        source = int(self.nearest_vertex(np.atleast_2d(point))[0])
        distance = self.distance_from(source)
        inside = distance[vertex] < radius_mm
        return [i for i in ids[inside].tolist() if i]


def _vertex_areas(mesh):
    """One third of each incident face's area, the standard barycentric lumping."""
    areas = np.zeros(len(mesh.vertices))
    face_area = mesh.area_faces
    for column in range(3):
        np.add.at(areas, mesh.faces[:, column], face_area / 3.0)
    return areas


def _as_column(values, count, default=np.nan):
    if values is None:
        return np.full(count, default)
    values = np.asarray(values, dtype=float).reshape(-1)
    if len(values) == count:
        return values
    return np.full(count, float(values[0]) if len(values) else default)
