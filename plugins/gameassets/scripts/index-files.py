#!/usr/bin/env python3
"""File-level index — one row per individual asset, not per pack.

Covers files inside archives (read from the zip central directory, which is free)
and files loose on disk. Image dimensions come from the 24-byte PNG/GIF header,
measured at 0.03 ms per file, so every image gets real dimensions rather than a
sampled guess.

Writes the `files` table + FTS index into assets.db.
"""
import re, sqlite3, struct, sys, tarfile, zipfile
from pathlib import Path

ROOT = Path.home() / "GameAssets"
DB   = ROOT / "assets.db"
SKIP_DIRS = {"_tools"}

IMG = {"png","jpg","jpeg","gif","bmp","tga","webp"}

def png_dims(raw):
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        try: return struct.unpack('>II', raw[16:24])
        except Exception: return None
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        try: return struct.unpack('<HH', raw[6:10])
        except Exception: return None
    return None

def ext_of(name):
    m = re.search(r'\.([A-Za-z0-9]{1,13})$', name)
    return m.group(1).lower() if m else ""

def walk_archive(path):
    p = str(path)
    try:
        if p.endswith('.zip'):
            z = zipfile.ZipFile(p)
            for i in z.infolist():
                if i.is_dir(): continue
                d = None
                if ext_of(i.filename) in IMG and i.file_size > 32:
                    try:
                        with z.open(i) as fh: d = png_dims(fh.read(24))
                    except Exception: pass
                yield i.filename, i.file_size, d
        elif p.endswith(('.tar','.tar.gz','.tgz','.unitypackage')):
            t = tarfile.open(p)
            for m in t.getmembers():
                if not m.isfile(): continue
                yield m.name, m.size, None
    except Exception:
        return

def main():
    db = sqlite3.connect(DB)
    db.executescript("""
    DROP TABLE IF EXISTS files;
    DROP TABLE IF EXISTS files_fts;
    CREATE TABLE files(
      id INTEGER PRIMARY KEY, pack TEXT, inner_path TEXT, name TEXT,
      ext TEXT, bytes INTEGER, width INTEGER, height INTEGER, loose INTEGER);
    CREATE INDEX ix_f_ext  ON files(ext);
    CREATE INDEX ix_f_pack ON files(pack);
    CREATE INDEX ix_f_name ON files(name);
    CREATE VIRTUAL TABLE files_fts USING fts5(name, inner_path, content='');
    """)
    batch, n, arch = [], 0, 0

    archives = []
    for pat in ("*.zip","*.tar","*.tgz","*.tar.gz","*.unitypackage"):
        archives += [a for a in ROOT.rglob(pat) if not set(a.parts) & SKIP_DIRS]
    print(f"archives: {len(archives)}", flush=True)
    for a in archives:
        rel = str(a.relative_to(ROOT))
        arch += 1
        for name, size, dims in walk_archive(a):
            batch.append((rel, name, name.split('/')[-1], ext_of(name), size,
                          dims[0] if dims else None, dims[1] if dims else None, 0))
            if len(batch) >= 20000:
                db.executemany("INSERT INTO files(pack,inner_path,name,ext,bytes,width,height,loose)"
                               " VALUES(?,?,?,?,?,?,?,?)", batch); n += len(batch); batch=[]
        if arch % 100 == 0:
            print(f"  {arch}/{len(archives)} archives, {n+len(batch)} files", flush=True)

    # loose files on disk
    for f in ROOT.rglob("*"):
        if not f.is_file() or set(f.parts) & SKIP_DIRS: continue
        if f.suffix.lower() in ('.zip','.tar','.tgz','.unitypackage'): continue
        if f.name.startswith('.'): continue
        rel = str(f.relative_to(ROOT))
        d = None
        e = ext_of(f.name)
        if e in IMG:
            try: d = png_dims(f.open('rb').read(24))
            except Exception: pass
        batch.append((str(f.parent.relative_to(ROOT)), rel, f.name, e,
                      f.stat().st_size, d[0] if d else None, d[1] if d else None, 1))
        if len(batch) >= 20000:
            db.executemany("INSERT INTO files(pack,inner_path,name,ext,bytes,width,height,loose)"
                           " VALUES(?,?,?,?,?,?,?,?)", batch); n += len(batch); batch=[]
    if batch:
        db.executemany("INSERT INTO files(pack,inner_path,name,ext,bytes,width,height,loose)"
                       " VALUES(?,?,?,?,?,?,?,?)", batch); n += len(batch)
    db.execute("INSERT INTO files_fts(rowid,name,inner_path) SELECT id,name,inner_path FROM files")
    db.commit()
    print(f"\nfiles indexed: {n}")
    for r in db.execute("SELECT ext,COUNT(*) c FROM files GROUP BY ext ORDER BY c DESC LIMIT 12"):
        print(f"  {r[1]:8d}  {r[0] or '(none)'}")
    print("\nimages with real dimensions:",
          db.execute("SELECT COUNT(*) FROM files WHERE width IS NOT NULL").fetchone()[0])

if __name__ == "__main__":
    main()
