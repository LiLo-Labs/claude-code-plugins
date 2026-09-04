#!/usr/bin/env python3
"""Loads the taxonomy into assets.db as a concept graph and tags every file.

Tables:
  concepts(name, parent)                    IS_A hierarchy
  edges(src, rel, dst)                      IS_A and HAS_PART, queryable together
  file_concepts(file_id, concept, term)     which term matched, for auditability

Tagging is token-based: each filename is split once and its tokens looked up in a
term->concept map, so cost is O(files x tokens), not O(files x terms).
Multi-word terms are checked as substrings against the whole path.
"""
import re, sqlite3, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from taxonomy import T

ROOT = Path.home() / "GameAssets"
DB   = ROOT / "assets.db"

def main():
    db = sqlite3.connect(DB)
    db.executescript("""
    DROP TABLE IF EXISTS concepts; DROP TABLE IF EXISTS edges;
    DROP TABLE IF EXISTS file_concepts;
    CREATE TABLE concepts(name TEXT PRIMARY KEY, parent TEXT, terms TEXT, domain TEXT);
    CREATE TABLE edges(src TEXT, rel TEXT, dst TEXT);
    CREATE INDEX ix_e_src ON edges(src, rel);
    CREATE INDEX ix_e_dst ON edges(dst, rel);
    CREATE TABLE file_concepts(file_id INTEGER, concept TEXT, term TEXT);
    CREATE INDEX ix_fc_c ON file_concepts(concept);
    CREATE INDEX ix_fc_f ON file_concepts(file_id);
    """)
    for name, (parent, terms, parts, domain) in T.items():
        db.execute("INSERT INTO concepts VALUES(?,?,?,?)", (name, parent, ",".join(terms), domain))
        if parent: db.execute("INSERT INTO edges VALUES(?,?,?)", (name, "IS_A", parent))
        for p in parts: db.execute("INSERT INTO edges VALUES(?,?,?)", (name, "HAS_PART", p))
    db.commit()

    # term -> concepts (a term may legitimately serve several concepts)
    # domain gate: which file-extension classes may a concept apply to
    EXT_DOMAIN = {}
    for e in "png jpg jpeg gif bmp tga webp psd svg aseprite ase".split(): EXT_DOMAIN[e] = "visual"
    for e in "fbx obj gltf glb dae blend stl mtl".split():                 EXT_DOMAIN[e] = "model"
    for e in "wav mp3 ogg flac aiff ncw nki nkx".split():                  EXT_DOMAIN[e] = "audio"

    single, multi = collections.defaultdict(set), []
    domain_of = {}
    for name, (_, terms, _, dom) in T.items():
        domain_of[name] = set(dom.split("|")) if dom != "any" else None
        for t in terms:
            if " " in t: multi.append((t, name))
            else: single[t].add(name)

    def allowed(concept, ext):
        d = domain_of.get(concept)
        if d is None: return True            # "any" concept
        fd = EXT_DOMAIN.get(ext)
        if fd is None: return True           # unknown extension: do not gate
        return fd in d

    rows, n, tagged = [], 0, 0
    cur = db.execute("SELECT id, name, inner_path, ext FROM files")
    for fid, fname, ipath, fext in cur:
        text = f"{ipath} {fname}".lower()
        toks = set(re.split(r'[^a-z]+', text))
        hits = set()
        for tk in toks:
            if tk in single:
                for c in single[tk]:
                    if allowed(c, fext): hits.add((c, tk))
        for t, c in multi:
            if t in text and allowed(c, fext): hits.add((c, t))
        if hits:
            tagged += 1
            for c, t in hits: rows.append((fid, c, t))
        n += 1
        if len(rows) >= 50000:
            db.executemany("INSERT INTO file_concepts VALUES(?,?,?)", rows); rows = []
        if n % 200000 == 0:
            print(f"  {n} files scanned, {tagged} tagged", flush=True)
    if rows: db.executemany("INSERT INTO file_concepts VALUES(?,?,?)", rows)
    db.commit()

    total = db.execute("SELECT COUNT(*) FROM file_concepts").fetchone()[0]
    print(f"\nfiles scanned: {n}   tagged: {tagged} ({100*tagged/max(n,1):.0f}%)")
    print(f"concept assignments: {total}")
    print("\ntop concepts:")
    for r in db.execute("SELECT concept, COUNT(DISTINCT file_id) c FROM file_concepts "
                        "GROUP BY concept ORDER BY c DESC LIMIT 18"):
        print(f"  {r[1]:7d}  {r[0]}")

if __name__ == "__main__":
    main()
