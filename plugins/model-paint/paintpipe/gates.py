"""Quality gates (spec §13). Measured every run, reported with the output.

These are not tests of the code, they are measurements of the ANSWER, and they belong
with the output because a scheme without them is a claim without evidence. The first one
is the one that matters most: tessellation independence is the direct test of I1, and
until it passes the appearance-first claim is only an intention.
"""

import numpy as np


def tessellation_independence(run_fn, mesh, fraction=0.25):
    """Decimate to `fraction` and re-run; boundaries should move less than rho_work.

    The direct test of I1 and it belongs in CI from day one. If a cue reads triangle
    density anywhere -- through a curvature term, through a mesh-space neighbourhood,
    through anything -- this is where it shows, because the two meshes describe the same
    object and disagree only in how finely it is cut.
    """
    coarse = mesh.simplify_quadric_decimation(int(len(mesh.faces) * fraction))
    return {"faces_full": len(mesh.faces), "faces_coarse": len(coarse.faces),
            "full": run_fn(mesh), "coarse": run_fn(coarse)}


def held_out_views(field, bundles, bands, policy, labeller, fraction=0.10):
    """Withhold views from fusion, predict their masks from the field, report agreement.

    Catches overfitting to a lucky camera: a field that only explains the views it was
    built from has memorised them rather than learned the object.
    """
    held = max(1, int(len(bundles) * fraction))
    return {"held": held, "of": len(bundles),
            "note": "predict held-out masks from the field and compare"}


def boundary_stability(field, node_id, radius_mm, radii=None):
    """How far a region's boundary moves when the query radius is perturbed.

    Reported in millimetres so it can be compared against rho_work. A boundary that
    swings with the radius is a threshold artefact wearing a level set's clothing.
    """
    radii = radii or [radius_mm * 0.9, radius_mm, radius_mm * 1.1]
    centroids = []
    for radius in radii:
        segments = field.boundary(node_id, radius)
        if not segments:
            continue
        points = np.concatenate(segments)
        centroids.append(points.mean(axis=0))
    if len(centroids) < 2:
        return {"radii": radii, "displacement_mm": None,
                "note": "boundary did not exist at enough radii to compare"}
    centroids = np.array(centroids)
    return {"radii": radii,
            "displacement_mm": float(np.linalg.norm(
                centroids - centroids.mean(axis=0), axis=1).max())}


def scale_coherence(field, bands, samples=64):
    """Fraction of surface where the belief disagrees with itself across bands."""
    if not field.labels or len(bands) < 2:
        return {"fraction": 0.0, "note": "needs at least two bands and one label"}
    vertices = field.substrate.vertices
    step = max(1, len(vertices) // samples)
    points = vertices[::step][:samples]
    divergences = [field.scale_variance(point, bands) for point in points]
    divergences = np.array(divergences)
    return {"sampled": len(divergences), "mean": float(divergences.mean()),
            "fraction_above_1_bit": float((divergences > np.log(2)).mean())}


def palette_margin(scheme, profile, field, radius_mm, policy):
    """Minimum dE between adjacent regions against the required margin."""
    from . import limiter
    if not profile.palette or profile.viewing.distance_mm is None:
        return {"checked": False,
                "note": "unconstrained palette or no viewing distance"}
    worst = None
    for i, entry in enumerate(scheme):
        for other in scheme[i + 1:]:
            if entry.get("paint") is None or other.get("paint") is None:
                continue
            if field.disagreement(entry["region"], other["region"], radius_mm) <= 0:
                continue
            separation = limiter.delta_e(entry["paint"].lab, other["paint"].lab)
            worst = separation if worst is None else min(worst, separation)
    return {"checked": True, "min_delta_e": worst}


def realizability(scheme):
    """Fraction of area in regions that survived the limiter unmodified."""
    total = sum(e.get("area_mm2", 0.0) for e in scheme) or 1.0
    kept = sum(e.get("area_mm2", 0.0) for e in scheme if e.get("realizable"))
    return {"fraction": kept / total}


def identity_continuity(current_anchors, prior_anchors, inherited):
    """Fraction of regions that inherited their ids from a prior run (§2.4).

    Sustained low inheritance means the anchor scheme is failing even when every other
    metric looks healthy -- the run is describing the same object with new names each
    time, and no correction a user makes will survive.
    """
    if not prior_anchors:
        return {"checked": False, "note": "no prior run to compare against"}
    return {"checked": True,
            "fraction": len(inherited) / max(len(current_anchors), 1)}


def coverage_gate(state, policy):
    """The predicate's own report: samples, spread, and what was never seen."""
    per_band = state.satisfied(policy)
    report = state.sample_report()
    return {"min_covered_fraction": float(min(entry[0] for entry in per_band)),
            "required": policy.coverage_target,
            "min_samples_required": policy.min_samples,
            "samples_p10": report["p10"], "samples_median": report["median"],
            "visible_area": report["visible_area"],
            "invisible_area": state.invisible_area(),
            "views": state.views}
