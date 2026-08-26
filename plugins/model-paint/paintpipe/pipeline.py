"""The whole run: profile, observe, fuse, decide, realize (spec §2 figure 2).

Profile happens once; observe and fuse loop; the two backward edges -- resampling and
merge-back -- are the only ones in the system.

Every stage mints entities, so the finished export walks back through `inputs` to the
exact renders, masks, policy and profile that produced it. That is the whole of I7 in
practice: not that records have names, but that the names connect.
"""

import numpy as np

from . import agents as agents_module
from . import bands as bands_module
from . import entities as entities_module
from . import field as field_module
from . import frame as frame_module
from . import gates as gates_module
from . import limiter as limiter_module
from . import policy as policy_module
from . import views as views_module


def profile_object(bundle, profile, policy, store, log=print):
    """§4 / §12. Everything that happens once, before any agent considers semantics."""
    meshes = bundle.load()
    mesh = meshes[0]
    object_entity = store.mint("object", params=bundle.params(),
                               attrs={"paths": bundle.params()["paths"],
                                      "intent": bundle.intent})
    profile_entity = store.mint("profile", params=profile.params(),
                                attrs={"unconstrained": profile.unconstrained})
    policy_entity = store.mint("policy", params=policy.as_dict(),
                               attrs=policy.as_dict())

    frame = frame_module.build_frame(mesh, target_size_mm=bundle.target_size_mm)
    working = frame.working_mesh(mesh, store=store, inputs=[object_entity])
    identity = agents_module.DEFAULT_AGENTS["identity"].read(None, frame)
    frame_module.name_axes(frame, identity["axis_names"])
    frame_entity = store.mint("frame", inputs=[object_entity], params=frame.params(),
                              attrs={"extent_mm": frame.extent_mm.round(3).tolist(),
                                     "size_source": frame.size_source})
    log("frame: %s mm, size %s" % (frame.extent_mm.round(1).tolist(),
                                   frame.size_source))
    for check in frame.checks:
        if not check.passed:
            log("  validate %-18s %s  %s" % (check.name,
                                             "repaired" if check.repaired else "FAILED",
                                             check.detail))

    found, spectrum = bands_module.derive_bands(working, frame, policy, store=store,
                                                inputs=[object_entity])
    band_entities = [store.mint("band", inputs=[frame_entity], params=band.params(),
                                attrs=band.params()) for band in found]
    log("bands: %s" % ["%.2fmm" % band.wavelength_mm for band in found])

    rho, rho_paint, rho_work = bands_module.working_resolution(found, profile, policy)
    log("working resolution: rho %.4fmm, paint %s, rho_work %.4fmm"
        % (rho, "none" if rho_paint is None else "%.4fmm" % rho_paint, rho_work))
    return {"mesh": mesh, "working": working, "frame": frame, "bands": found,
            "spectrum": spectrum, "rho_work": rho_work,
            "entities": {"object": object_entity, "frame": frame_entity,
                         "profile": profile_entity, "policy": policy_entity,
                         "bands": band_entities}}


def run(bundle, profile, policy=None, root="run", rigs=("zenithal", "raking_a", "flat"),
        pixels=700, max_rounds=4, log=print):
    """The five phases end to end. Returns the export manifest and the store."""
    policy = policy or policy_module.DEFAULT
    store = entities_module.Store(root)
    run_entity = store.mint("run", params={"spec": "0.2"})

    # --- profile -----------------------------------------------------------------
    shape = profile_object(bundle, profile, policy, store, log=log)
    frame, working, found = shape["frame"], shape["working"], shape["bands"]

    plan = agents_module.DEFAULT_AGENTS["planner"].plan(found, profile, bundle.intent,
                                                        policy)
    log("planner: %s" % plan["reason"])
    for band, why in plan["skip"]:
        store.reject("band", why, inputs=[run_entity], count=1)
    attended = plan["attend"]

    # --- observe and fuse --------------------------------------------------------
    label_field = field_module.LabelField(working, frame, policy, store=store,
                                          inputs=[shape["entities"]["object"]])
    region_agent = agents_module.DEFAULT_AGENTS["region"]

    def labeller(bundle_buffers, band):
        return region_agent.propose(bundle_buffers, band)

    state, why = views_module.converge(label_field, working, frame, attended, policy,
                                       labeller, rigs=rigs, pixels=pixels, store=store,
                                       inputs=[run_entity], max_rounds=max_rounds,
                                       log=log)
    log("converge: %s after %d views, %d observations"
        % (why, state.views, label_field.count))

    # --- decide ------------------------------------------------------------------
    radius = float(np.median([band.wavelength_mm for band in attended]))
    critic = agents_module.DEFAULT_AGENTS["critic"].review(label_field, radius, policy)
    for node_id, action, reason in critic["edits"]:
        store.reject("region", "%s: %s" % (action, reason), inputs=[run_entity], count=1)
    dropped = {node_id for node_id, action, _ in critic["edits"] if action == "drop"}
    kept = [node_id for node_id in label_field.labels if node_id not in dropped]
    log("critic: %d regions checked, %d edits" % (critic["checked"],
                                                  len(critic["edits"])))

    scheme = agents_module.DEFAULT_AGENTS["painter"].colour(label_field, kept, radius,
                                                            bundle.intent)
    for entry in scheme:
        membership = label_field.region(entry["region"], radius)
        entry["area_mm2"] = float(np.sum(membership * label_field.vertex_area))
        store.mint("region", inputs=[run_entity],
                   params={"label": entry["region"], "radius_mm": radius},
                   attrs={"label": entry["region"], "role": entry["role"],
                          "area_mm2": round(entry["area_mm2"], 3)})

    # --- realize -----------------------------------------------------------------
    scheme = limiter_module.fit_palette(scheme, profile, label_field, radius, policy,
                                        store=store, inputs=[run_entity])
    tip = profile.finest_tip()
    for entry in scheme:
        membership = label_field.region(entry["region"], radius)
        entry["inscribed_radius_mm"] = limiter_module.min_feature(membership,
                                                                  label_field)
        if tip is not None:
            floor = policy.merge_ratio * tip.tip_radius_mm
            if entry["inscribed_radius_mm"] < floor:
                entry["realizable"] = False
                entry["note"] = "inscribed radius below the finest tip"
                store.reject("region", "below the minimum feature the brush can paint",
                             inputs=[run_entity], count=1)
            ok, fraction = limiter_module.reachability(membership, label_field, tip)
            entry["reachable_fraction"] = fraction
            if not ok:
                entry["realizable"] = False
                entry["note"] = "no unoccluded brush approach"
                store.reject("region", "unpaintable in place: no unoccluded approach",
                             inputs=[run_entity], count=1)

    colours, bake_info = limiter_module.bake(label_field, scheme, shape["rho_work"],
                                             radius)
    store.mint("bake", inputs=[run_entity], params=bake_info, attrs=bake_info)

    coverage = gates_module.coverage_gate(state, policy)
    manifest = limiter_module.export_guide(scheme, frame, label_field, radius, found,
                                           coverage, store=store, inputs=[run_entity])
    manifest["gates"] = {
        "coverage": coverage,
        "scale_coherence": gates_module.scale_coherence(label_field, attended),
        "palette_margin": gates_module.palette_margin(scheme, profile, label_field,
                                                      radius, policy),
        "realizability": gates_module.realizability(scheme),
        "boundary_stability": {
            entry["region"]: gates_module.boundary_stability(label_field,
                                                             entry["region"], radius)
            for entry in scheme[:3]},
    }
    manifest["converged"] = why
    store.write()
    return manifest, store, label_field, colours
