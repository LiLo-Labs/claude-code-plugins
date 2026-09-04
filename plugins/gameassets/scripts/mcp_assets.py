#!/usr/bin/env python3
"""MCP stdio server over assets.db — asset discovery for the GameAssets library.

Dependency-free: speaks the MCP JSON-RPC protocol directly rather than pulling in
an SDK, so it runs on any Python 3.9+ with no install step.

Tools: search_assets, get_pack, how_to_use, list_categories, library_stats
"""
import json, os, sqlite3, sys
from pathlib import Path

# The library lives outside the plugin; GAMEASSETS_ROOT points at it so the
# plugin stays portable and the 300 GB of assets stay where they are.
ROOT = Path(os.environ.get("GAMEASSETS_ROOT", Path.home() / "GameAssets")).expanduser()
DB   = ROOT / "assets.db"
PROTOCOL = "2024-11-05"

def _require_db():
    if not DB.exists():
        raise RuntimeError(
            f"No asset database at {DB}. Set GAMEASSETS_ROOT to your library, "
            f"or build it with the scripts in this plugin's scripts/ directory.")

def q(sql, args=()):
    _require_db()
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()

TOOLS = [
 {"name":"search_assets",
  "description":"Search the asset library. Filter by free-text query (matches path and "
                "category), category, readiness tier, commercial-use verdict, or source "
                "collection. Returns packs ordered by size.",
  "inputSchema":{"type":"object","properties":{
     "query":{"type":"string","description":"free text, e.g. 'tileset', 'dungeon', 'ui'"},
     "category":{"type":"string","description":"one of: 2d, 3d, audio, font, video, tileset, character, environment, ui, vfx, weapon, prop, audio-sfx, audio-music, texture, template, vehicle"},
     "tier":{"type":"string","enum":["ready","unpack","tool","blocked","unknown"],
             "description":"ready = import directly; unpack = script we have; tool = needs an app; blocked = cannot reach a game engine without a project"},
     "commercial":{"type":"string","enum":["YES","NO","UNCLEAR","MIXED"],
             "description":"commercial-use verdict from the pack's own licence file. Absent means no licence file was found inside the archive."},
     "source":{"type":"string","description":"collection: cc0, humble, itch, fab, sonniss, 8dio, creativemarket, gumroad, asoundeffect, nested"},
     "limit":{"type":"integer","default":25}}}},
 {"name":"get_pack",
  "description":"Full detail for one pack including licence excerpt and usage steps.",
  "inputSchema":{"type":"object","properties":{
     "path":{"type":"string","description":"full or partial pack path"}},"required":["path"]}},
 {"name":"how_to_use",
  "description":"What must be DONE to a pack before it is a usable game asset: the tool "
                "required, the steps, and the caveats.",
  "inputSchema":{"type":"object","properties":{
     "path":{"type":"string"}},"required":["path"]}},
 {"name":"search_files",
  "description":"Search INDIVIDUAL asset files (814k of them) rather than packs. "
                "Matches on filename and path inside the archive. Filter by extension "
                "and by real pixel dimensions — e.g. exactly 16x16 tiles, or images "
                "larger than 1024px. Returns the file and the pack it lives in.",
  "inputSchema":{"type":"object","properties":{
     "query":{"type":"string","description":"matches filename or path inside the archive, e.g. 'autumn', 'sword', 'autotile'"},
     "ext":{"type":"string","description":"file extension, e.g. png, fbx, wav, gltf"},
     "min_width":{"type":"integer"},"max_width":{"type":"integer"},
     "exact_size":{"type":"string","description":"e.g. '16x16' or '32x32'"},
     "pack":{"type":"string","description":"restrict to packs whose path matches this"},
     "limit":{"type":"integer","default":30}}}},
 {"name":"search_concept",
  "description":"Search assets by CONCEPT, walking the taxonomy. Asking for 'clothing' "
                "also returns belts, shirts, boots and everything else beneath it, because "
                "IS_A is transitive. Asking for 'belt' can also return its parts (buckle, "
                "strap) with include_parts.",
  "inputSchema":{"type":"object","properties":{
     "concept":{"type":"string","description":"e.g. belt, clothing, weapon, tileset, piano_family"},
     "include_descendants":{"type":"boolean","default":True,
        "description":"include everything IS_A beneath the concept"},
     "include_parts":{"type":"boolean","default":False,
        "description":"also match the concept's HAS_PART components"},
     "ext":{"type":"string"},"pack":{"type":"string"},
     "include_game_content":{"type":"boolean","default":False,
        "description":"By default, packs classified as shipped games or metadata are excluded, "
                      "because their story art swamps genuine asset packs. Set true to include them."},
     "limit":{"type":"integer","default":30}},"required":["concept"]}},
 {"name":"concept_tree",
  "description":"Show a concept's place in the graph: its ancestors (IS_A chain), its "
                "children, its parts, and how many assets carry it. Call with no concept "
                "to list the roots.",
  "inputSchema":{"type":"object","properties":{
     "concept":{"type":"string"}}}},
 {"name":"list_categories",
  "description":"All categories with pack counts and total size.",
  "inputSchema":{"type":"object","properties":{}}},
 {"name":"library_stats",
  "description":"Totals by source, readiness tier and commercial-use verdict.",
  "inputSchema":{"type":"object","properties":{}}},
]

def t_search(a):
    sql = "SELECT path,source,size_mb,files,categories,tier,licence,commercial,top_types,description FROM packs WHERE 1=1"
    args = []
    if a.get("query"):
        sql += (" AND (path LIKE ? OR categories LIKE ? OR COALESCE(title,'') LIKE ?"
                " OR COALESCE(description,'') LIKE ? OR COALESCE(tags,'') LIKE ?"
                " OR COALESCE(folders,'') LIKE ? OR COALESCE(contents,'') LIKE ?)")
        args += [f"%{a['query']}%"] * 7
    for col in ("tier", "commercial", "source"):
        if a.get(col):
            sql += f" AND {col}=?"; args.append(a[col])
    if a.get("category"):
        sql += " AND categories LIKE ?"; args.append(f"%{a['category']}%")
    sql += " ORDER BY size_mb DESC LIMIT ?"
    args.append(int(a.get("limit", 25)))
    rows = q(sql, args)
    if not rows:
        return "No packs matched."
    out = [f"{len(rows)} pack(s):"]
    for r in rows:
        out.append(f"\n{r['path']}"
                   + (f"\n  \"{r['description'][:160]}\"" if r.get('description') else "")
                   + f"\n  {r['size_mb']} MB · {r['files']} files · {r['tier']}"
                   f" · {r['categories']}"
                   + (f" · licence={r['licence']}" if r['licence'] else "")
                   + (f" · commercial={r['commercial']}" if r['commercial'] else "")
                   + f"\n  contents: {r['top_types']}")
    return "\n".join(out)

def _one(path):
    # prefer an exact hit, then the largest pack that matches — a bare collection
    # name like "8dio" should resolve to a real pack, not the empty parent row
    r = q("SELECT * FROM packs WHERE path=? LIMIT 1", (path,))
    if not r:
        r = q("SELECT * FROM packs WHERE path LIKE ? AND files>0 "
              "ORDER BY size_mb DESC LIMIT 1", (f"%{path}%",))
    return r[0] if r else None

def t_get(a):
    r = _one(a["path"])
    if not r: return f"No pack matching '{a['path']}'."
    lines = [r["path"]]
    if r["title"]:       lines.append(f"  title: {r['title']}")
    if r["description"]: lines.append(f"  description: {r['description'][:500]}")
    if r["author"]:      lines.append(f"  author: {r['author']}")
    if r["tags"]:        lines.append(f"  tags: {r['tags'][:250]}")
    if r["url"]:         lines.append(f"  url: {r['url']}")
    if r["folders"]:     lines.append(f"  folders inside: {r['folders']}")
    if r["contents"]:    lines.append(f"  contents: {r['contents']}")
    if r["dims"]:        lines.append(f"  image sizes: {r['dims']}")
    lines += [f"  source: {r['source']}   size: {r['size_mb']} MB   files: {r['files']}",
             f"  categories: {r['categories']}", f"  contents: {r['top_types']}",
             f"  readiness: {r['tier']}"]
    if r["tools"]: lines.append(f"  tool needed: {r['tools']}")
    if r["steps"]: lines.append(f"  steps: {r['steps']}")
    if r["notes"]: lines.append(f"  notes: {r['notes']}")
    lines.append(f"  licence: {r['licence'] or 'no licence file found inside the archive'}")
    if r["commercial"]: lines.append(f"  commercial use: {r['commercial']}")
    if r["licence_file"]: lines.append(f"  licence file: {r['licence_file']}")
    if r["licence_excerpt"]: lines.append(f"  excerpt: {r['licence_excerpt'][:400]}")
    return "\n".join(lines)

def t_how(a):
    r = _one(a["path"])
    if not r: return f"No pack matching '{a['path']}'."
    out = [f"{r['path']}", f"readiness: {r['tier']}"]
    out.append({"ready":"Import directly into Godot; no conversion.",
                "unpack":"Needs extraction/conversion with a script in _tools/.",
                "tool":"Needs a specific third-party application.",
                "blocked":"Cannot reach a game engine without a substantial separate project.",
                "unknown":"File types not recognised — inspect the archive."}[r["tier"]])
    if r["tools"]: out.append(f"\ntool: {r['tools']}")
    if r["steps"]: out.append(f"steps:\n  {r['steps']}")
    if r["notes"]: out.append(f"caveats:\n  {r['notes']}")
    if r["commercial"] == "NO":
        out.append("\n** This pack's licence FORBIDS commercial use. **")
    elif not r["licence"]:
        out.append("\nNote: no licence file inside this archive — check the purchase page before shipping.")
    return "\n".join(out)

def t_files(a):
    sql = "SELECT name, ext, width, height, bytes, pack, inner_path FROM files WHERE 1=1"
    args = []
    if a.get("query"):
        sql += " AND (lower(name) LIKE ? OR lower(inner_path) LIKE ?)"
        v = f"%{a['query'].lower()}%"; args += [v, v]
    if a.get("ext"):
        sql += " AND ext=?"; args.append(a["ext"].lower().lstrip("."))
    if a.get("pack"):
        sql += " AND pack LIKE ?"; args.append(f"%{a['pack']}%")
    if a.get("exact_size"):
        try:
            w, h = a["exact_size"].lower().split("x")
            sql += " AND width=? AND height=?"; args += [int(w), int(h)]
        except Exception: pass
    if a.get("min_width"): sql += " AND width>=?"; args.append(int(a["min_width"]))
    if a.get("max_width"): sql += " AND width<=?"; args.append(int(a["max_width"]))
    sql += " ORDER BY bytes DESC LIMIT ?"; args.append(int(a.get("limit", 30)))
    rows = q(sql, args)
    if not rows: return "No files matched."
    out = [f"{len(rows)} file(s):"]
    for r in rows:
        dim = f"  {r['width']}x{r['height']}" if r["width"] else ""
        kb = f"{(r['bytes'] or 0)/1024:.0f} KB"
        out.append(f"  {r['name']}{dim}  ({kb})\n     in {r['pack']}\n     path {r['inner_path']}")
    return "\n".join(out)

def _descendants(concept):
    rows = q("""WITH RECURSIVE d(name) AS (
                  SELECT ? UNION
                  SELECT c.name FROM concepts c JOIN d ON c.parent = d.name)
                SELECT name FROM d""", (concept,))
    return [r["name"] for r in rows]

def t_concept_search(a):
    concept = a["concept"]
    names = _descendants(concept) if a.get("include_descendants", True) else [concept]
    if a.get("include_parts"):
        for r in q("SELECT dst FROM edges WHERE src=? AND rel='HAS_PART'", (concept,)):
            names.append(r["dst"])
    if not names: return f"Unknown concept '{concept}'."
    ph = ",".join("?" * len(names))
    sql = (f"SELECT f.name, f.ext, f.width, f.height, f.pack, f.inner_path, "
           f"GROUP_CONCAT(DISTINCT fc.concept) cs "
           f"FROM file_concepts fc JOIN files f ON f.id = fc.file_id "
           f"LEFT JOIN packs p ON p.path = f.pack "
           f"WHERE fc.concept IN ({ph})")
    args = list(names)
    if not a.get("include_game_content"):
        sql += " AND COALESCE(p.tier,'ready') NOT IN ('game','metadata')"
    if a.get("ext"):  sql += " AND f.ext=?";      args.append(a["ext"].lower().lstrip("."))
    if a.get("pack"): sql += " AND f.pack LIKE ?"; args.append(f"%{a['pack']}%")
    sql += " GROUP BY f.id ORDER BY f.bytes DESC LIMIT ?"; args.append(int(a.get("limit", 30)))
    rows = q(sql, args)
    if not rows: return f"No assets under '{concept}'."
    head = f"'{concept}' covers {len(names)} concept(s): {', '.join(names[:12])}"
    out = [head, f"{len(rows)} asset(s):"]
    for r in rows:
        dim = f" {r['width']}x{r['height']}" if r["width"] else ""
        out.append(f"  {r['name']}{dim}  [{r['cs']}]\n     {r['pack']}\n     {r['inner_path']}")
    return "\n".join(out)

def t_tree(a):
    c = a.get("concept")
    if not c:
        rows = q("SELECT name FROM concepts WHERE parent IS NULL ORDER BY name")
        return "roots: " + ", ".join(r["name"] for r in rows)
    row = q("SELECT * FROM concepts WHERE name=?", (c,))
    if not row: return f"Unknown concept '{c}'."
    row = row[0]
    anc, cur = [], row["parent"]
    while cur:
        anc.append(cur)
        nxt = q("SELECT parent FROM concepts WHERE name=?", (cur,))
        cur = nxt[0]["parent"] if nxt else None
    kids  = [r["name"] for r in q("SELECT name FROM concepts WHERE parent=? ORDER BY name", (c,))]
    parts = [r["dst"]  for r in q("SELECT dst FROM edges WHERE src=? AND rel='HAS_PART'", (c,))]
    n     = q("SELECT COUNT(DISTINCT file_id) n FROM file_concepts WHERE concept=?", (c,))[0]["n"]
    desc  = _descendants(c)
    ph = ",".join("?" * len(desc))
    nd = q(f"SELECT COUNT(DISTINCT file_id) n FROM file_concepts WHERE concept IN ({ph})", desc)[0]["n"]
    out = [f"{c}"]
    if anc:   out.append("  IS_A:      " + " -> ".join(anc))
    if kids:  out.append("  children:  " + ", ".join(kids))
    if parts: out.append("  HAS_PART:  " + ", ".join(parts))
    out.append(f"  domain:    {row['domain']}")
    out.append(f"  terms:     {row['terms'][:200]}")
    out.append(f"  assets:    {n} directly, {nd} including descendants")
    return "\n".join(out)

def t_cats(a):
    seen = {}
    for r in q("SELECT categories,size_mb FROM packs WHERE categories!=''"):
        for c in r["categories"].split(","):
            if not c: continue
            n, mb = seen.get(c, (0, 0)); seen[c] = (n+1, mb + (r["size_mb"] or 0))
    return "\n".join(f"{c:14s} {n:5d} packs   {mb/1024:7.1f} GB"
                     for c, (n, mb) in sorted(seen.items(), key=lambda x: -x[1][1]))

def t_stats(a):
    out = []
    for label, sql in [
      ("by source","SELECT source k, COUNT(*) n, SUM(size_mb)/1024.0 gb FROM packs GROUP BY 1 ORDER BY gb DESC"),
      ("by readiness","SELECT tier k, COUNT(*) n, SUM(size_mb)/1024.0 gb FROM packs GROUP BY 1 ORDER BY gb DESC"),
      ("commercial use","SELECT COALESCE(commercial,'(no licence file in archive)') k, COUNT(*) n, SUM(size_mb)/1024.0 gb FROM packs GROUP BY 1 ORDER BY n DESC")]:
        out.append(f"\n{label}:")
        for r in q(sql):
            out.append(f"  {str(r['k']):32s} {r['n']:5d} packs  {r['gb']:7.1f} GB")
    return "\n".join(out)

HANDLERS = {"search_assets":t_search, "search_files":t_files,
            "search_concept":t_concept_search, "concept_tree":t_tree, "get_pack":t_get, "how_to_use":t_how,
            "list_categories":t_cats, "library_stats":t_stats}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: msg = json.loads(line)
        except json.JSONDecodeError: continue
        mid, method = msg.get("id"), msg.get("method")
        try:
            if method == "initialize":
                res = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "gameassets", "version": "1.0.0"}}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                p = msg.get("params", {})
                fn = HANDLERS.get(p.get("name"))
                text = fn(p.get("arguments") or {}) if fn else f"unknown tool {p.get('name')}"
                res = {"content": [{"type": "text", "text": text}]}
            elif method in ("notifications/initialized", "initialized"):
                continue
            else:
                res = None
            if mid is not None and res is not None:
                print(json.dumps({"jsonrpc":"2.0","id":mid,"result":res}), flush=True)
        except Exception as e:
            if mid is not None:
                print(json.dumps({"jsonrpc":"2.0","id":mid,
                    "error":{"code":-32000,"message":str(e)}}), flush=True)

if __name__ == "__main__":
    main()
