#!/usr/bin/env python3
"""Extract matching assets out of their archives into a project folder.

Design points that matter:
  * Extracts individual members (zipfile.open) — never unpacks a whole archive.
  * Writes CREDITS.md recording every source pack and its licence position,
    because most packs carry no licence file at all, and that fact must travel
    with the files rather than being lost at copy time.
  * REFUSES packs whose licence forbids commercial use unless explicitly
    overridden, and always says which files it skipped and why.
  * Never writes outside `dest`.
"""
import argparse, json, os, re, sqlite3, sys, zipfile, tarfile
from pathlib import Path
from collections import defaultdict

ROOT = Path(os.environ.get("GAMEASSETS_ROOT", Path.home()/"GameAssets")).expanduser()
DB   = ROOT / "assets.db"

def db():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row; return c

def descendants(con, concept):
    return [r["name"] for r in con.execute(
        "WITH RECURSIVE d(name) AS (SELECT ? UNION "
        "SELECT c.name FROM concepts c JOIN d ON c.parent=d.name) SELECT name FROM d",
        (concept,))]

def pick(con, concept=None, query=None, ext=None, pack=None, limit=50,
         allow_noncommercial=False, include_game_content=False):
    sql = ("SELECT f.id,f.name,f.inner_path,f.pack,f.ext,f.width,f.height,"
           "p.licence,p.commercial,p.tier,p.title,p.url "
           "FROM files f LEFT JOIN packs p ON p.path=f.pack WHERE 1=1")
    args = []
    if concept:
        names = descendants(con, concept)
        ph = ",".join("?"*len(names))
        sql += (f" AND f.id IN (SELECT file_id FROM file_concepts WHERE concept IN ({ph}))")
        args += names
    if query:
        sql += " AND (lower(f.name) LIKE ? OR lower(f.inner_path) LIKE ?)"
        args += [f"%{query.lower()}%"]*2
    if ext:  sql += " AND f.ext=?";        args.append(ext.lower().lstrip("."))
    if pack: sql += " AND f.pack LIKE ?";  args.append(f"%{pack}%")
    if not include_game_content:
        sql += " AND COALESCE(p.tier,'ready') NOT IN ('game','metadata')"
    if not allow_noncommercial:
        sql += " AND COALESCE(p.commercial,'') != 'NO'"
    sql += " ORDER BY f.bytes DESC LIMIT ?"; args.append(limit)
    return [dict(r) for r in con.execute(sql, args)]

def pack_label(packrel):
    """A readable name for a pack.

    An archive is named by its own filename. A loose directory is named by its
    collection plus the pack folder — `fab/dark_fantasy_weapons/.../1024Textures`
    should read "dark_fantasy_weapons", not "1024Textures", which is an interior
    folder that says nothing about provenance.
    """
    p = Path(packrel)
    if p.suffix.lower() in (".zip", ".tar", ".tgz", ".unitypackage", ".7z"):
        return re.sub(r'[^A-Za-z0-9._-]+', '_', p.stem)[:60]
    parts = [x for x in p.parts if x]
    return re.sub(r'[^A-Za-z0-9._-]+', '_', "_".join(parts[:2]))[:60] or "assets"

def extract(rows, dest, flat=False):
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    by_pack = defaultdict(list)
    for r in rows: by_pack[r["pack"]].append(r)
    written, failed = [], []
    for packrel, items in by_pack.items():
        src = ROOT / packrel
        try:
            if src.is_file() and str(src).endswith(".zip"):
                z = zipfile.ZipFile(src)
                read = lambda n: z.read(n)
            elif src.is_file() and str(src).endswith((".tar",".tgz",".tar.gz",".unitypackage")):
                t = tarfile.open(src)
                read = lambda n: t.extractfile(n).read()
            elif src.is_dir() or src.is_file():
                read = None            # already loose on disk
            else:
                failed.append((packrel, "source not found")); continue
        except Exception as e:
            failed.append((packrel, f"{type(e).__name__}: {e}")); continue

        sub = dest / pack_label(packrel)
        for r in items:
            try:
                data = read(r["inner_path"]) if read else (ROOT / r["inner_path"]).read_bytes()
            except Exception as e:
                failed.append((r["inner_path"], f"{type(e).__name__}")); continue
            out = (dest / r["name"]) if flat else (sub / r["name"])
            out = out.resolve()
            if dest not in out.parents and out != dest:      # never escape dest
                failed.append((r["inner_path"], "path escape refused")); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            written.append((r, out))
    return written, failed

def credits(written, dest):
    packs = {}
    for r, _ in written:
        packs.setdefault(r["pack"], r)
    lines = ["# Asset credits", "",
             f"{len(written)} files from {len(packs)} pack(s), delivered from the local library.",
             "", "**Verify each licence before shipping.** Where the licence column reads",
             "*no licence file in archive*, the terms live on the original purchase page,",
             "not in the download — absence of a licence file is not permission.", ""]
    for path, r in sorted(packs.items()):
        n = sum(1 for x, _ in written if x["pack"] == path)
        lines.append(f"## {r['title'] or pack_label(path)}")
        lines.append(f"- pack: `{path}`")
        lines.append(f"- files used: {n}")
        lines.append(f"- licence: {r['licence'] or '**no licence file in archive**'}")
        lines.append(f"- commercial use: {r['commercial'] or 'unknown — check the purchase page'}")
        if r["url"]: lines.append(f"- source: {r['url']}")
        lines.append("")
    (Path(dest)/"CREDITS.md").write_text("\n".join(lines))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--concept"); ap.add_argument("--query"); ap.add_argument("--ext")
    ap.add_argument("--pack"); ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--allow-noncommercial", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (a.concept or a.query or a.pack):
        sys.exit("give at least one of --concept / --query / --pack")
    con = db()
    rows = pick(con, a.concept, a.query, a.ext, a.pack, a.limit, a.allow_noncommercial)
    if not rows: sys.exit("nothing matched")
    # how many rows this same query would have returned if non-commercial were allowed
    skipped = 0
    if not a.allow_noncommercial:
        widened = pick(con, a.concept, a.query, a.ext, a.pack, a.limit,
                       allow_noncommercial=True)
        got = {r["id"] for r in rows}
        skipped = sum(1 for r in widened if r["id"] not in got)
    if a.dry_run:
        for r in rows[:40]:
            d = f" {r['width']}x{r['height']}" if r["width"] else ""
            print(f"  {r['name']}{d}  <- {r['pack']}")
        print(f"\n{len(rows)} file(s) would be written to {a.dest}")
        return
    written, failed = extract(rows, a.dest, a.flat)
    credits(written, a.dest)
    print(f"delivered {len(written)} file(s) to {a.dest}")
    print(f"  CREDITS.md written")
    if not a.allow_noncommercial:
        if skipped:
            print(f"  ({skipped} further match(es) withheld: their pack's licence forbids "
                  f"commercial use — pass --allow-noncommercial to include them)")
    for what, why in failed[:10]: print(f"  FAILED {what}: {why}")

if __name__ == "__main__":
    main()
