#!/usr/bin/env python3
"""Builds assets.db — the discovery database behind the MCP server.

Joins three sources:
  INDEX.tsv        what packs exist, their size and internal file mix
  licences.json    licence classification + commercial-use verdict + excerpt
  pipeline.py      what must be DONE to a pack before it is a usable game asset

Everything unknown stays unknown. No field is inferred into a confident value.
"""
import json, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pipeline

ROOT = Path.home() / "GameAssets"
DB   = ROOT / "assets.db"

CATEGORY_RULES = [
 ("tileset",     r'tile|tilemap|tileset|terrain'),
 ("character",   r'character|hero|npc|monster|creature|enemy|people|human|animal|avatar|skeleton'),
 ("environment", r'environment|village|town|city|dungeon|castle|interior|exterior|building|house|world|forest|island|harbour|harbor|temple|prison|cave|arena'),
 ("ui",          r'\bui\b|gui|hud|interface|icon|button|menu|cursor|crosshair'),
 ("vfx",         r'vfx|effect|particle|smoke|fire|explosion|spell|magic'),
 ("weapon",      r'weapon|sword|gun|bow|shield|armor|armour'),
 ("prop",        r'\bprops?\b|furniture|decoration|barrel|crate|chest|container|debris|clutter'),
 ("audio-sfx",   r'sfx|sound|foley|ambience|ambient|effect'),
 ("audio-music", r'music|ost|soundtrack|score|piano|string|orchestr|choir|voice'),
 ("font",        r'font|typeface'),
 ("texture",     r'texture|material|pbr|pattern|brush|paper'),
 ("template",    r'template|starter|sample|demo|tutorial|project'),
 ("vehicle",     r'vehicle|car|ship|spaceship|plane|boat'),
]

EXT_CATEGORY = {
 "3d":    {"fbx","obj","gltf","glb","blend","dae","stl","uasset"},
 "2d":    {"png","jpg","jpeg","gif","webp","psd","aseprite","svg"},
 "audio": {"wav","mp3","ogg","flac","aiff","ncw","nki"},
 "font":  {"ttf","otf"},
 "video": {"mp4","webm","ogv","mov"},
}

def flat(v):
    """itch metadata fields arrive as str, list or dict depending on the page."""
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, (list, tuple)): return " ".join(flat(x) for x in v)
    if isinstance(v, dict): return " ".join(f"{k} {flat(x)}" for k, x in v.items())
    return str(v)

def parse_types(s):
    out = {}
    for part in (s or "").split(","):
        if ":" in part:
            k, v = part.rsplit(":", 1)
            try: out[k.strip().lower()] = int(v)
            except ValueError: pass
    return out

def categorise(path, ext_counts):
    name = path.lower()
    cats = {c for c, pat in CATEGORY_RULES if re.search(pat, name)}
    present = set(ext_counts)
    for c, exts in EXT_CATEGORY.items():
        if present & exts:
            cats.add(c)
    return sorted(cats)

def main():
    lic = json.loads((ROOT/"_tools"/"licences.json").read_text()) if (ROOT/"_tools"/"licences.json").exists() else {}
    desc = json.loads((ROOT/"_tools"/"descriptions.json").read_text()) if (ROOT/"_tools"/"descriptions.json").exists() else {}
    db = sqlite3.connect(DB)
    db.executescript("""
    DROP TABLE IF EXISTS packs;
    DROP TABLE IF EXISTS packs_fts;
    CREATE TABLE packs(
      id INTEGER PRIMARY KEY, source TEXT, path TEXT UNIQUE, kind TEXT,
      size_mb INTEGER, files INTEGER, top_types TEXT, categories TEXT,
      licence TEXT, commercial TEXT, licence_file TEXT, licence_excerpt TEXT,
      tier TEXT, tools TEXT, steps TEXT, notes TEXT,
      title TEXT, description TEXT, author TEXT, url TEXT, tags TEXT,
      folders TEXT, contents TEXT, dims TEXT);
    CREATE INDEX ix_source ON packs(source);
    CREATE INDEX ix_tier   ON packs(tier);
    CREATE INDEX ix_comm   ON packs(commercial);
    CREATE VIRTUAL TABLE packs_fts USING fts5(path, categories, notes, content='');
    """)

    rows = (ROOT/"INDEX.tsv").read_text().split("\n")[1:]
    n = 0
    for line in rows:
        if not line.strip(): continue
        f = line.split("\t")
        if len(f) < 6: continue
        source, path, kind, size_mb, files, top_types = f[:6]
        ext = parse_types(top_types)
        tier, matched = pipeline.analyse(ext)
        if tier == "unknown" and not ext and (files in ("0", "", "?") or int(files or 0) == 0):
            tier = "empty"
        tools = "; ".join(sorted({m[3] for m in matched if m[3]})) or None
        steps = " | ".join(m[4] for m in matched) or None
        notes = " | ".join(m[5] for m in matched) or None
        L = lic.get(path, [])
        best = None
        for h in L:
            if h["licence"] not in ("UNKNOWN", "BINARY-UNREAD"): best = h; break
        if best is None and L: best = L[0]
        D  = desc.get(path, {})
        it = D.get("itch") or {}
        iv = D.get("internals") or {}
        # categorise from EVIDENCE (description, tags, folder names, filenames
        # found inside the archive) rather than from the pack's filename alone
        evidence = " ".join(filter(None, [
            path, flat(it.get("title")), flat(it.get("description")),
            flat(it.get("tags")), flat(it.get("category")),
            " ".join(iv.get("top_folders") or []), " ".join(iv.get("sub_folders") or []),
            " ".join(iv.get("common_names") or [])]))
        cats = categorise(evidence, iv.get("extensions") or ext)
        db.execute("INSERT OR IGNORE INTO packs(source,path,kind,size_mb,files,top_types,"
                   "categories,licence,commercial,licence_file,licence_excerpt,tier,tools,steps,notes,"
                   "title,description,author,url,tags,folders,contents,dims)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (source, path, kind, int(size_mb or 0), None if files=="?" else int(files or 0),
           top_types, ",".join(cats),
           (best or {}).get("licence") or (flat(it.get("asset_license")) or None), (best or {}).get("commercial"),
           (best or {}).get("file"), (best or {}).get("excerpt"),
           tier, tools, steps, notes,
           flat(it.get("title")) or None, flat(it.get("description")) or None,
           flat(it.get("author")) or None, flat(it.get("url")) or None,
           flat(it.get("tags")) or None,
           ", ".join((iv.get("top_folders") or [])[:8]) or None,
           ", ".join((iv.get("common_names") or [])[:12]) or None,
           ", ".join((iv.get("png_dims") or [])[:5]) or None))
        n += 1
    db.execute("INSERT INTO packs_fts(rowid,path,categories,notes) "
               "SELECT id, path, categories, "
               "COALESCE(title,'')||' '||COALESCE(description,'')||' '||COALESCE(tags,'')"
               "||' '||COALESCE(folders,'')||' '||COALESCE(contents,'') FROM packs")
    db.commit()

    print(f"packs: {n}")
    for label, q in [("by tier","SELECT tier,COUNT(*),SUM(size_mb)/1024 FROM packs GROUP BY tier ORDER BY 2 DESC"),
                     ("commercial","SELECT COALESCE(commercial,'(no licence file)'),COUNT(*) FROM packs GROUP BY 1 ORDER BY 2 DESC")]:
        print(f"\n{label}:")
        for r in db.execute(q): print("   ", "  ".join(str(x) for x in r))

if __name__ == "__main__":
    main()
