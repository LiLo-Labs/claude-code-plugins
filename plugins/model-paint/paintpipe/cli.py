"""One command: a mesh and a brief in, a painted 3MF and guide renders out.

This is the plugin's interface. A user does not write Python and does not get a
bespoke script; they name a model, say what it is, and list the filament they have
loaded. Everything the spec describes happens behind that.

    python3 -m paintpipe.cli --input dragon.stl --intent "a baby dragon" \
        --colors "white:#FFFFFF, black:#000000, orange:#FF8000, grey:#808080" \
        --size-mm 187 --out dragon-paint/

The two stages are kept separate in the output because they answer different
questions (§10, §11). The CONTINUOUS render shows what the model should look like and
is the honest test of whether the segmentation found real parts. The LIMITED render
shows what this printer can actually lay down. Judging the second without the first
tells you nothing about which stage a disappointment came from.
"""

import argparse
import json
import os
import time

import numpy as np


def parse_colors(text):
    """`name:#RRGGBB, ...` or just `#RRGGBB, ...` into Paint objects."""
    from . import inputs as inputs_module
    from .agents import _hex_to_lab
    out = []
    for index, chunk in enumerate((text or "").split(",")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            name, value = chunk.split(":", 1)
        else:
            name, value = "filament-%d" % (index + 1), chunk
        name, value = name.strip(), value.strip()
        out.append(inputs_module.Paint("FIL-%d" % (index + 1), name,
                                       _hex_to_lab(value)))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="STL or 3MF")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--intent", default="",
                        help="what the piece is, in the user's own words; this is the "
                             "cheapest disambiguation available for a grey render")
    parser.add_argument("--size-mm", type=float, default=None,
                        help="real printed height; inferred and flagged when absent")
    parser.add_argument("--colors", default="",
                        help="loaded filaments as 'name:#RRGGBB, ...'; without them the "
                             "run produces a design rather than a plan and says so")
    parser.add_argument("--nozzle-mm", type=float, default=0.4)
    parser.add_argument("--viewing-mm", type=float, default=500.0)
    parser.add_argument("--pixels", type=int, default=700)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--rigs", default="zenithal,raking_a,raking_b,flat")
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--model", default="claude-opus-5",
                        help="vision model for the identity, region and painter agents")
    parser.add_argument("--no-vision", action="store_true",
                        help="run the deterministic stand-ins instead of a model")
    args = parser.parse_args(argv)

    import trimesh
    from . import (agents, bands as bands_module, entities, field as field_module,
                   frame as frame_module, inputs as inputs_module, limiter,
                   policy as policy_module, preview, render as render_module,
                   views as views_module, vision)

    started = time.time()
    os.makedirs(args.out, exist_ok=True)
    policy = policy_module.DEFAULT
    palette = parse_colors(args.colors)
    profile = inputs_module.PainterProfile(
        tips=[inputs_module.Tip("nozzle", tip_radius_mm=args.nozzle_mm,
                                half_angle_deg=45.0)],
        palette=palette,
        viewing=inputs_module.ViewingCondition(distance_mm=args.viewing_mm))

    def log(message):
        print(message, flush=True)

    # -- profile (§4) ------------------------------------------------------------
    source = trimesh.load(args.input, process=False, force="mesh")
    store = entities.Store(os.path.join(args.out, "entities"))
    run = store.mint("run", params={"spec": "0.2", "input": os.path.basename(args.input)})
    frame = frame_module.build_frame(source, target_size_mm=args.size_mm)
    working = frame.working_mesh(source, store=store, inputs=[run])
    for check in frame.checks:
        if not check.passed:
            log("  validate %-18s %-9s %s"
                % (check.name, "repaired" if check.repaired else "FAILED", check.detail))
    log("frame %s mm (%s)" % (frame.extent_mm.round(1).tolist(), frame.size_source))

    field = field_module.LabelField(working, frame, policy, store=store, inputs=[run])
    found, spectrum = bands_module.derive_bands(working, frame, policy, store=store,
                                                inputs=[run])
    log("bands %s" % ["%.2fmm" % band.wavelength_mm for band in found])

    # -- observe and fuse (§5-§9) ------------------------------------------------
    centre = working.vertices.mean(axis=0)
    span = float(np.ptp(working.vertices, axis=0).max()) / 2.0 * 1.05
    overviews = [vision.render_png(render_module.render_bundle(
        working, render_module.Camera(-d, [0, 0, 1], centre, span, 640), "zenithal",
        frame)) for d in render_module.fibonacci_directions(5)]

    if args.no_vision:
        region_agent = agents.DEFAULT_AGENTS["region"]
        vocabulary, backend = [], None
    else:
        backend = vision.HeadlessBackend(os.path.join(args.out, "vision"),
                                         model=args.model)
        args._backend = backend
        region_agent = agents.VisionRegion(backend, intent=args.intent, policy=policy,
                                           store=store).bind(working, frame)
        vocabulary = region_agent.learn_vocabulary(overviews)
        args._vocabulary = vocabulary
        log("parts %s" % [part["label"] for part in vocabulary])

    state, why = views_module.converge(
        field, working, frame, found, policy,
        lambda bundle, band: region_agent.propose(bundle, band),
        rigs=tuple(args.rigs.split(",")), pixels=args.pixels, store=store,
        inputs=[run], max_rounds=args.rounds, log=log, sample_stride=args.stride,
        prefetch=getattr(region_agent, "prefetch", None))
    log("converge %s | %d views | %d observations" % (why, state.views, field.count))

    radius = float(np.median([band.wavelength_mm for band in found]))
    posterior = field.posterior(radius)
    labels = list(field.labels)
    if not labels:
        log("no regions were claimed; nothing to paint")
        return 1

    # §13. A run can look healthy in every other number and still have concluded nothing.
    from . import gates as gates_module
    claim = gates_module.claimed_area(field, radius)
    log("claimed area: %s" % claim["verdict"])
    if not claim["healthy"]:
        store.reject("run", "claimed area %.1f%% -- masks too small for the model"
                     % (100 * claim["claimed_fraction"]), inputs=[run], count=1)
        log("  WARNING: this run will produce a mostly unpainted model. The usual cause "
            "is a band ladder that does not reach the size of the parts.")

    np.savez_compressed(os.path.join(args.out, "field.npz"),
                        posterior=posterior, vertices=field.substrate.vertices,
                        faces=field.substrate.faces, vertex_area=field.vertex_area,
                        labels=np.array(labels, dtype=object),
                        vocabulary=np.array(json.dumps(vocabulary), dtype=object),
                        radius_mm=radius)

    # -- decide (§10) ------------------------------------------------------------
    critic = agents.DEFAULT_AGENTS["critic"].review(field, radius, policy)
    dropped = {node for node, action, _ in critic["edits"] if action == "drop"}
    kept = [label for label in labels if label not in dropped] or labels
    painter = agents.VisionPainter(backend) if backend is not None \
        else agents.DEFAULT_AGENTS["painter"]
    scheme = painter.colour(field, kept, radius, args.intent,
                            **({"vocabulary": vocabulary, "overviews": overviews}
                               if backend is not None else {}))
    log("\ncontinuous colour")
    for entry in scheme:
        log("  %-24s %-8s %-10s" % (entry["region"], entry.get("hex", ""),
                                    entry["role"]))

    # -- realize (§11) -----------------------------------------------------------
    result = _finish(args, store, run, field, frame, posterior, labels, scheme,
                     profile, policy, radius, source, log)
    result["claimed_area"] = claim
    result["converged"] = why
    result["views"] = state.views
    result["observations"] = field.count
    result["seconds"] = round(time.time() - started, 1)
    if backend is not None:
        result["vision_calls"] = backend.calls
        result["vision_cost_usd"] = round(backend.cost_usd, 3)
    store.write()
    with open(os.path.join(args.out, "scheme.json"), "w") as handle:
        json.dump(entities._plain(result), handle, indent=2, default=str)
    log("\ndone in %.0fs -- %s" % (result["seconds"], args.out))
    return 0


def _finish(args, store, run, field, frame, posterior, labels, scheme, profile, policy,
            radius, source, log):
    """Limiter, renders and export. Split out only to keep `main` readable."""
    import trimesh
    from . import entities, limiter, preview
    from PIL import Image

    mesh = trimesh.Trimesh(vertices=field.substrate.vertices,
                           faces=field.substrate.faces, process=False)
    order = {entry["region"]: i for i, entry in enumerate(scheme)}
    index = np.array([order[label] for label in labels if label in order])
    live_labels = [label for label in labels if label in order]
    owner = index[np.argmax(posterior[[labels.index(l) for l in live_labels]], axis=0)]
    claimed = posterior.max(axis=0) > 0

    occlusion = preview.ambient_occlusion(mesh, samples=40)
    up = preview.up_axis(frame)
    names = [entry["region"] for entry in scheme]

    def write(lab, stem):
        rgb = preview.face_colours(mesh, lab)
        preview.contact_sheet(mesh, rgb, preview.orbit(8, 18.0, up=up), size=470,
                              occlusion=occlusion, columns=4).save(
            os.path.join(args.out, "%s-turnaround.png" % stem))
        Image.fromarray(preview.render_asset(
            mesh, rgb, preview.orbit(1, 24.0, start_deg=200.0, up=up)[0], size=950,
            occlusion=occlusion, up=up, zoom=1.2)).save(
            os.path.join(args.out, "%s-hero.png" % stem))

    wanted = np.array([entry["lab"] for entry in scheme])
    lab = posterior[[labels.index(l) for l in live_labels]].T @ wanted[index]
    lab[~claimed] = np.array([64.0, 1.0, 2.0])
    write(lab, "continuous")
    log("wrote continuous-turnaround.png, continuous-hero.png")

    if not profile.palette:
        log("no filaments given: design only, not a plan (§3.2)")
        return {"regions": scheme, "realizable": False}

    edges = mesh.edges_unique
    a, b = owner[edges[:, 0]], owner[edges[:, 1]]
    both = claimed[edges[:, 0]] & claimed[edges[:, 1]] & (a != b)
    pairs = np.unique(np.stack([np.minimum(a[both], b[both]),
                                np.maximum(a[both], b[both])], axis=1), axis=0)
    touching = [(names[int(x)], names[int(y)]) for x, y in pairs]
    share = {label: float(np.sum(posterior[labels.index(label)] * field.vertex_area))
             for label in live_labels}
    chosen, clashes = limiter.assign_paints(scheme, profile.palette, touching, policy,
                                            profile.viewing.distance_mm, areas=share)
    for entry in scheme:
        entry["area_mm2"] = round(share.get(entry["region"], 0.0), 2)
    log("\nlimited to %d filament(s)" % len(profile.palette))
    for entry in scheme:
        paint = chosen[entry["region"]]
        log("  %-24s %-8s -> %-8s dE %5.1f"
            % (entry["region"], entry.get("hex", ""), paint.name,
               limiter.delta_e(entry["lab"], paint.lab)))
    if clashes:
        log("  boundaries the palette cannot separate: %s" % clashes)
        for left, right in clashes:
            store.reject("scheme_entry", "%s and %s could not be separated"
                         % (left, right), inputs=[run], count=1)

    # Commit at the nozzle's scale, not per vertex (§11 minimum feature).
    tip = profile.finest_tip()
    committed = limiter.consolidate(field, owner, claimed,
                                    tip.tip_radius_mm if tip else 0.4, policy)
    limited = np.array([chosen[entry["region"]].lab for entry in scheme])[committed]
    limited[~claimed] = np.array(profile.palette[-1].lab)
    write(limited, "limited")
    log("wrote limited-turnaround.png, limited-hero.png")

    # -- second pass (§10): sub-parts below patch resolution, then the critic ----
    # Any part the coarse pass left empty, whose parent has area, gets a zoomed
    # re-ask over the parent's own faces. Generic: driven by the vocabulary
    # hierarchy the identity agent returned, with nothing model-specific in it.
    backend = getattr(args, "_backend", None)
    vocabulary = getattr(args, "_vocabulary", None)
    if backend is not None and vocabulary:
        from . import refine as refine_module
        face_part = _face_parts(field, committed, claimed)
        face_part, recovered = refine_module.refine_subparts(
            mesh, face_part, names, vocabulary, backend, args.intent, frame=frame)
        if recovered:
            log("second pass recovered: %s" % recovered)
            committed, claimed = _vertex_parts(field, face_part, len(names))

        overrides, verdict = refine_module.review_scheme(
            backend, [os.path.join(args.out, "limited-hero.png"),
                      os.path.join(args.out, "limited-turnaround.png")],
            scheme, chosen, profile.palette, args.intent)
        if verdict:
            log("critic: %s" % verdict)
        for part, (paint, why) in overrides.items():
            log("  critic override %-22s -> %-7s %s" % (part, paint.name, why[:60]))
            chosen[part] = paint
        if overrides or recovered:
            limited = np.array([chosen[entry["region"]].lab
                                for entry in scheme])[committed]
            limited[~claimed] = np.array(profile.palette[-1].lab)
            write(limited, "final")
            log("wrote final-turnaround.png, final-hero.png")

    export = _export_3mf(args, field, chosen, names, committed, claimed, profile,
                         source, log)
    return {"regions": [{k: v for k, v in entry.items() if k != "actor"}
                        for entry in scheme],
            "filaments": {entry["region"]: chosen[entry["region"]].name
                          for entry in scheme},
            "unseparated": clashes, "export": export}


def _face_parts(field, owner, claimed):
    faces = field.substrate.faces
    face_claimed = claimed[faces]
    return np.where(face_claimed.any(axis=1),
                    np.take_along_axis(owner[faces],
                                       np.argmax(face_claimed, axis=1)[:, None],
                                       axis=1).ravel(), -1).astype(np.int32)


def _vertex_parts(field, face_part, count):
    votes = np.zeros((len(field.substrate.vertices), count))
    for column in range(3):
        v = field.substrate.faces[:, column]
        ok = face_part >= 0
        np.add.at(votes, (v[ok], face_part[ok]), 1.0)
    claimed = votes.sum(axis=1) > 0
    return np.where(claimed, np.argmax(votes, axis=1), 0).astype(np.int32), claimed


def _export_3mf(args, field, chosen, names, owner, claimed, profile, source, log):
    """Write the painted 3MF and verify the geometry never moved."""
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = os.path.join(here, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from paintlib import build as builder, orca, threemf
    except ImportError:
        log("3MF writer unavailable; skipping export")
        return {"written": False}

    base = os.path.join(args.out, "base.3mf")
    painted = os.path.join(args.out, "painted.3mf")
    builder.from_stl(args.input, base, name=os.path.splitext(
        os.path.basename(args.input))[0])

    slot = {paint.name: i + 1 for i, paint in enumerate(profile.palette)}
    faces = field.substrate.faces
    face_claimed = claimed[faces]
    face_label = np.where(
        face_claimed.any(axis=1),
        np.take_along_axis(owner[faces], np.argmax(face_claimed, axis=1)[:, None],
                           axis=1).ravel(), -1)
    default = slot[profile.palette[-1].name]
    assignments = {}
    for i in range(len(faces)):
        label = int(face_label[i])
        if label < 0:
            continue
        filament = slot[chosen[names[label]].name]
        if filament != default:
            assignments[i] = filament

    archive = threemf.ThreeMF(base)
    archive.paint_object(archive.mesh_objects()[0], assignments)
    orca.set_filaments(archive, [{"index": i + 1, "name": paint.name,
                                  "hex": _to_hex(paint.lab)}
                                 for i, paint in enumerate(profile.palette)],
                       default_filament=default)
    archive.save(painted)

    ok, why = threemf.geometry_matches(base, painted)
    out = threemf.ThreeMF(painted).mesh_objects()[0]
    vertices = np.array(out.vertices)
    triangles = np.array(out.triangles)
    deviation = float(np.abs(vertices - source.vertices).max()) \
        if len(vertices) == len(source.vertices) else float("inf")
    same = bool(len(triangles) == len(source.faces)
                and (triangles == np.asarray(source.faces)).all())
    log("\n3MF %s -- %s" % (os.path.basename(painted), why))
    log("  vertices %d==%d, triangles %d==%d, indices identical %s, max deviation %.1e mm"
        % (len(vertices), len(source.vertices), len(triangles), len(source.faces),
           same, deviation))
    return {"written": True, "path": painted, "geometry_identical": bool(ok and same),
            "max_vertex_deviation_mm": deviation,
            "histogram": out.filament_histogram()}


def _to_hex(lab):
    from colour import Lab_to_XYZ, XYZ_to_sRGB
    rgb = np.clip(XYZ_to_sRGB(Lab_to_XYZ(np.asarray(lab, dtype=float))), 0, 1)
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in rgb)


if __name__ == "__main__":
    raise SystemExit(main())
