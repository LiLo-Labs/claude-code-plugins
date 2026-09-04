#!/usr/bin/env python3
"""Deep description pass — replaces filename-guessing with evidence.

Three evidence sources, in order of trust:
  1. itch metadata.json  — the creator's own title, description, tags, licence
  2. archive internals   — top-level folders, representative filenames, full
                           extension histogram, and PNG pixel dimensions read
                           from the 24-byte header (no image decoding)
  3. the pack's path      — last resort only

Writes _tools/descriptions.json. Nothing is invented: a pack with no evidence
gets no description rather than a guess assembled from its filename.
"""
import json, re, struct, zipfile, tarfile, collections
from pathlib import Path

ROOT = Path.home() / "GameAssets"
OUT  = ROOT / "_tools" / "descriptions.json"

def png_size(raw):
    """width,height from a PNG header without decoding the image."""
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    try:
        w, h = struct.unpack('>II', raw[16:24])
        return (w, h)
    except Exception:
        return None

def archive_internals(path, max_dims=12):
    p = str(path)
    names = []
    try:
        if p.endswith('.zip'):
            z = zipfile.ZipFile(p)
            names = [n for n in z.namelist() if not n.endswith('/')]
            opener = lambda n: z.open(n)
        elif p.endswith(('.tar', '.tar.gz', '.tgz', '.unitypackage')):
            t = tarfile.open(p)
            names = [m.name for m in t.getmembers() if m.isfile()]
            opener = lambda n: t.extractfile(n)
        else:
            return None
    except Exception:
        return None
    if not names:
        return None

    exts = collections.Counter()
    for n in names:
        m = re.search(r'\.([A-Za-z0-9]{1,13})$', n)
        if m: exts[m.group(1).lower()] += 1

    # top-level folders are far more descriptive than the zip's own filename
    tops = collections.Counter(n.split('/')[0] for n in names if '/' in n)
    # second level too — that is usually where the real taxonomy lives
    seconds = collections.Counter(n.split('/')[1] for n in names
                                  if n.count('/') >= 2 and len(n.split('/')[1]) > 1)

    # representative leaf names, collapsed so 200 numbered variants show as one
    stems = collections.Counter()
    for n in names:
        leaf = n.split('/')[-1]
        stem = re.sub(r'[\d_\-]*\.[A-Za-z0-9]+$', '', leaf)
        stem = re.sub(r'[\s_\-]*\d+$', '', stem).strip()
        if 2 < len(stem) < 40: stems[stem] += 1

    dims = collections.Counter()
    pngs = [n for n in names if n.lower().endswith('.png')][:max_dims]
    for n in pngs:
        try:
            with opener(n) as fh:
                d = png_size(fh.read(24))
            if d: dims[d] += 1
        except Exception:
            pass

    return {"file_count": len(names),
            "extensions": dict(exts.most_common(20)),
            "top_folders": [k for k, _ in tops.most_common(8)],
            "sub_folders": [k for k, _ in seconds.most_common(12)],
            "common_names": [k for k, _ in stems.most_common(15)],
            "png_dims": [f"{w}x{h}" for (w, h), _ in dims.most_common(5)]}

def itch_metadata(pack_path):
    """Walk up from the pack looking for the metadata.json itch-dl saved."""
    p = (ROOT / pack_path)
    for parent in [p] + list(p.parents):
        if ROOT not in parent.parents and parent != ROOT:
            pass
        m = parent / "metadata.json"
        if m.exists():
            try: d = json.loads(m.read_text())
            except Exception: return None
            e = d.get("extra") or {}
            return {"title": d.get("title"), "description": d.get("description"),
                    "author": d.get("author"), "url": d.get("url"),
                    "rating": d.get("rating"),
                    "tags": e.get("tags"), "category": e.get("category"),
                    "asset_license": e.get("asset_license"), "genre": e.get("genre")}
        if parent == ROOT: break
    return None

def main():
    import sys
    packs = [l.split("\t")[1] for l in (ROOT/"INDEX.tsv").read_text().split("\n")[1:]
             if l.strip() and len(l.split("\t")) > 1]
    out = {}
    for i, rel in enumerate(packs, 1):
        full = ROOT / rel
        rec = {}
        meta = itch_metadata(rel)
        if meta and any(meta.values()): rec["itch"] = meta
        if full.is_file():
            ai = archive_internals(full)
            if ai: rec["internals"] = ai
        if rec: out[rel] = rec
        if i % 250 == 0:
            print(f"  {i}/{len(packs)}  ({len(out)} described)", flush=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"\ndescribed {len(out)} / {len(packs)} packs")
    print(f"  with itch metadata: {sum(1 for v in out.values() if 'itch' in v)}")
    print(f"  with archive internals: {sum(1 for v in out.values() if 'internals' in v)}")

if __name__ == "__main__":
    main()
