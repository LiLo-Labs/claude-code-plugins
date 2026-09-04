"""Paid text-to-3D providers: Meshy, Tripo and Hyper3D Rodin.

All three are the same shape — submit a job, poll it, download a GLB — so they
share `poll` and `download` from base and differ only in endpoint, auth header
and where the finished URL sits in the reply. Each adapter keeps that difference
in one small, obvious place so a provider changing its response schema is a
five-line fix rather than a rewrite.

Cost is real here and the skill is expected to say so before spending: these are
per-generation charges on the user's own API key, not something the plugin can
absorb. The cost hints below are order-of-magnitude, not quotes.
"""

import os

from .base import BackendError, GenerationResult, MeshBackend, download, http_json, poll


def _env(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return None


class MeshyBackend(MeshBackend):
    name = "meshy"
    kind = "paid API"
    cost_hint = 0.20
    BASE = "https://api.meshy.ai/openapi/v2/text-to-3d"

    def __init__(self):
        self.key = _env("MESHY_API_KEY")

    def available(self):
        return bool(self.key)

    def why_unavailable(self):
        return "set MESHY_API_KEY (https://www.meshy.ai — Settings > API)"

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.key}

    def generate(self, prompt, out_dir, image=None, options=None):
        options = options or {}
        if image:
            raise BackendError("meshy backend here covers text-to-3D only; pass a text prompt")

        # Meshy is two-phase: a fast untextured preview, then an optional refine
        # that textures it. Preview alone is the right default for a critique
        # loop — you find out the silhouette is wrong before paying to texture it.
        preview = http_json(
            self.BASE,
            method="POST",
            headers=self._headers(),
            payload={
                "mode": "preview",
                "prompt": prompt,
                "art_style": options.get("art_style", "realistic"),
                "should_remesh": True,
                "topology": options.get("topology", "quad"),
                "target_polycount": int(options.get("target_polycount", 30000)),
            },
        )
        task_id = preview.get("result") or preview.get("id")
        if not task_id:
            raise BackendError("meshy did not return a task id: %r" % preview)

        finished = poll(
            lambda: self._check(task_id), timeout=int(options.get("timeout", 900)), label="meshy preview"
        )

        if options.get("texture", True):
            refine = http_json(
                self.BASE,
                method="POST",
                headers=self._headers(),
                payload={"mode": "refine", "preview_task_id": task_id},
            )
            refine_id = refine.get("result") or refine.get("id")
            if refine_id:
                finished = poll(
                    lambda: self._check(refine_id),
                    timeout=int(options.get("timeout", 900)),
                    label="meshy refine",
                )

        urls = finished.get("model_urls") or {}
        url = urls.get("glb") or urls.get("fbx") or urls.get("obj")
        if not url:
            raise BackendError("meshy finished but returned no downloadable model")
        path = download(url, os.path.join(out_dir, "meshy.glb"))
        return GenerationResult(
            path,
            self.name,
            {"task_id": task_id, "prompt": prompt, "textured": bool(options.get("texture", True))},
        )

    def _check(self, task_id):
        state = http_json("%s/%s" % (self.BASE, task_id), headers=self._headers())
        status = (state.get("status") or "").upper()
        if status in ("SUCCEEDED", "SUCCESS", "COMPLETED"):
            return state
        if status in ("FAILED", "CANCELED", "EXPIRED"):
            raise BackendError("meshy task %s %s: %s" % (task_id, status, state.get("task_error")))
        return None


class TripoBackend(MeshBackend):
    name = "tripo"
    kind = "paid API"
    cost_hint = 0.15
    BASE = "https://api.tripo3d.ai/v2/openapi"

    def __init__(self):
        self.key = _env("TRIPO_API_KEY")

    def available(self):
        return bool(self.key)

    def why_unavailable(self):
        return "set TRIPO_API_KEY (https://platform.tripo3d.ai)"

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.key}

    def generate(self, prompt, out_dir, image=None, options=None):
        options = options or {}
        payload = {"type": "text_to_model", "prompt": prompt}
        if options.get("quad", True):
            payload["quad"] = True
        if options.get("face_limit"):
            payload["face_limit"] = int(options["face_limit"])

        created = http_json(
            "%s/task" % self.BASE, method="POST", headers=self._headers(), payload=payload
        )
        task_id = (created.get("data") or {}).get("task_id")
        if not task_id:
            raise BackendError("tripo did not return a task id: %r" % created)

        finished = poll(
            lambda: self._check(task_id), timeout=int(options.get("timeout", 900)), label="tripo task"
        )
        output = finished.get("output") or {}
        url = (
            (output.get("pbr_model") if isinstance(output.get("pbr_model"), str) else None)
            or (output.get("model") if isinstance(output.get("model"), str) else None)
            or output.get("base_model")
        )
        if not url:
            raise BackendError("tripo finished but returned no model url")
        path = download(url, os.path.join(out_dir, "tripo.glb"))
        return GenerationResult(path, self.name, {"task_id": task_id, "prompt": prompt})

    def _check(self, task_id):
        state = (http_json("%s/task/%s" % (self.BASE, task_id), headers=self._headers()).get("data")) or {}
        status = (state.get("status") or "").lower()
        if status in ("success", "succeeded", "completed"):
            return state
        if status in ("failed", "cancelled", "banned", "expired", "unknown"):
            raise BackendError("tripo task %s %s" % (task_id, status))
        return None


class RodinBackend(MeshBackend):
    name = "rodin"
    kind = "paid API"
    cost_hint = 0.40
    BASE = "https://hyperhuman.deemos.com/api/v2"

    def __init__(self):
        self.key = _env("RODIN_API_KEY", "HYPER3D_API_KEY")

    def available(self):
        return bool(self.key)

    def why_unavailable(self):
        return "set RODIN_API_KEY (https://hyper3d.ai — Rodin API)"

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.key}

    def generate(self, prompt, out_dir, image=None, options=None):
        options = options or {}
        created = http_json(
            "%s/rodin" % self.BASE,
            method="POST",
            headers=self._headers(),
            payload={
                "prompt": prompt,
                "tier": options.get("tier", "Regular"),
                "geometry_file_format": "glb",
                "quality": options.get("quality", "medium"),
                "mesh_mode": "Quad" if options.get("quad", True) else "Raw",
            },
        )
        uuid = created.get("uuid")
        subscription = (created.get("jobs") or {}).get("subscription_key")
        if not uuid:
            raise BackendError("rodin did not return a job uuid: %r" % created)

        poll(
            lambda: self._check(subscription),
            timeout=int(options.get("timeout", 900)),
            label="rodin job",
        )
        listing = http_json(
            "%s/download" % self.BASE,
            method="POST",
            headers=self._headers(),
            payload={"task_uuid": uuid},
        )
        files = listing.get("list") or []
        glb = next((f for f in files if str(f.get("name", "")).lower().endswith(".glb")), None)
        if not glb:
            raise BackendError("rodin produced no .glb in %r" % [f.get("name") for f in files])
        path = download(glb["url"], os.path.join(out_dir, "rodin.glb"))
        return GenerationResult(path, self.name, {"uuid": uuid, "prompt": prompt})

    def _check(self, subscription):
        if not subscription:
            raise BackendError("rodin returned no subscription key to poll")
        state = http_json(
            "%s/status" % self.BASE,
            method="POST",
            headers=self._headers(),
            payload={"subscription_key": subscription},
        )
        jobs = state.get("jobs") or []
        statuses = {str(j.get("status", "")).lower() for j in jobs}
        if statuses and statuses <= {"done", "succeed", "succeeded"}:
            return state
        if statuses & {"failed", "error", "cancelled"}:
            raise BackendError("rodin job failed: %r" % jobs)
        return None
