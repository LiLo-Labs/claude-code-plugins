#!/usr/bin/env python3
"""Extract and classify the licence of every pack in the library.

Reads licence/EULA/readme files *out of* each archive without extracting the
payload (zipfile.open on the single member). Classification is deliberately
conservative: anything it cannot positively identify is UNKNOWN, never guessed
into a permissive bucket, because the whole point is deciding what is safe to ship.
"""
import json, os, re, sqlite3, sys, tarfile, zipfile
from pathlib import Path

ROOT = Path.home() / "GameAssets"
OUT  = ROOT / "_tools" / "licences.json"

LICENCE_RE = re.compile(r'(licen[cs]e|eula|terms|copyright|readme|attribution)', re.I)

# ordered: first match wins, most specific first
# Commercial-use detection is NEGATION-AWARE. Substring matching is actively
# dangerous here: "YOU CAN'T USE THE ASSET IN COMMERCIAL PROJECTS" contains
# "use the asset in commercial", and a naive matcher reads a prohibition as a
# grant. Every occurrence of "commercial" is therefore judged by the words that
# precede it, and a document containing both grants and prohibitions is reported
# as UNCLEAR rather than resolved by guesswork.
NEG = re.compile(r"(can'?t|cannot|can not|may not|not (be )?(allowed|permitted)|"
                 r"no[t]? for|prohibit|forbid|restrict|except|without)", re.I)
BOTH_OK = re.compile(r"(any|both)\s+(non[- ]?)?commercial\s+(or|and)\s+(non[- ]?)?commercial", re.I)

def commercial_status(text):
    """Judge each mention of "commercial" by its surrounding words.

    Three traps this handles, all of which a substring matcher gets wrong:
      * "CAN'T USE THE ASSET IN COMMERCIAL PROJECTS" contains "use...in commercial"
      * "you can use this in NON commercial projects" grants nothing about commercial
      * "Commercial use is permitted" puts the verb AFTER the noun
    Any explicit prohibition wins, because under-claiming rights is safe and
    over-claiming them is not.
    """
    t = re.sub(r'\s+', ' ', text)
    grants = denies = 0
    for m in re.finditer(r'commercial', t, re.I):
        before = t[max(0, m.start() - 70):m.start()]
        after  = t[m.end():m.end() + 45]
        ctx    = before + " " + after

        if BOTH_OK.search(t[max(0, m.start() - 45):m.end() + 45]):
            grants += 1
            continue
        # "non commercial" / "non-commercial": says nothing about commercial rights
        if re.search(r'non[- ]?$', before, re.I):
            continue
        if NEG.search(before) or re.search(r'^\s*(use )?(is|are) (not|never)', after, re.I):
            denies += 1
        elif re.search(r'\b(can|may|are able to|permitted|allowed|free to|granted)\b', ctx, re.I):
            grants += 1

    if denies:
        return "NO" if not grants else "MIXED"
    return "YES" if grants else "UNCLEAR"

RULES = [
    ("CC0-1.0",        r'\bCC0\b|creative commons zero|public domain dedication'),
    ("CC-BY-SA",       r'attribution[- ]sharealike|CC[- ]BY[- ]SA'),
    ("CC-BY-4.0",      r'creative commons attribution 4\.0|CC[- ]BY[- ]4\.0'),
    ("CC-BY-3.0",      r'creative commons attribution 3\.0|CC[- ]BY[- ]3\.0'),
    ("MIT",            r'\bMIT License\b'),
    ("Apache-2.0",     r'Apache License,? Version 2\.0'),
    ("GPL",            r'GNU General Public License'),
    ("OFL",            r'SIL Open Font License'),
    ("Epic-Fab-Std",   r'Fab End User License|Epic Marketplace|Unreal Engine End User'),
    ("Unity-AssetStore", r'Unity Asset Store (End User )?License|Asset Store Terms'),
    ("8dio-EULA",      r'8Dio Productions|8dio\.com'),
    ("Royalty-Free",   r'royalty[- ]free|royalty free'),
    ("Custom-EULA",    r'end user licen[cs]e agreement|licence agreement|license agreement'),
]

def is_binary(raw):
    """Word .doc/OLE and other binaries decode to noise; do not classify them."""
    if raw[:4] in (b'\xd0\xcf\x11\xe0', b'%PDF', b'PK\x03\x04'):
        return True
    sample = raw[:4000]
    if not sample:
        return True
    nonprint = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return nonprint / len(sample) > 0.05

def classify(text):
    t = text[:20000]
    for name, pat in RULES:
        if re.search(pat, t, re.I):
            return name
    return "UNKNOWN"

def members(path):
    """(name, reader) for licence-looking files inside an archive."""
    p = str(path)
    try:
        if p.endswith('.zip'):
            z = zipfile.ZipFile(p)
            for n in z.namelist():
                if LICENCE_RE.search(os.path.basename(n)) and not n.endswith('/'):
                    yield n, (lambda n=n: z.read(n))
        elif p.endswith(('.tar', '.tar.gz', '.tgz', '.unitypackage')):
            tf = tarfile.open(p)
            for m in tf.getmembers():
                if m.isfile() and LICENCE_RE.search(os.path.basename(m.name)):
                    yield m.name, (lambda m=m: tf.extractfile(m).read())
    except Exception:
        return

def scan_archive(path):
    hits = []
    for name, read in members(path):
        try:
            raw = read()[:200000]
        except Exception:
            continue
        if is_binary(raw):
            hits.append({"file": name, "licence": "BINARY-UNREAD",
                         "commercial": "UNCLEAR", "excerpt": ""})
            continue
        text = raw.decode('utf-8', 'ignore')
        if len(text.strip()) < 20:
            continue
        hits.append({"file": name, "licence": classify(text),
                     "commercial": commercial_status(text),
                     "excerpt": re.sub(r'\s+', ' ', text.strip())[:400]})
    return hits

def main():
    archives = []
    for ext in ('*.zip', '*.tar', '*.tgz', '*.tar.gz', '*.unitypackage'):
        archives += list(ROOT.rglob(ext))
    archives = [a for a in archives if '_tools' not in a.parts]
    print(f"scanning {len(archives)} archives", flush=True)

    results = {}
    for i, a in enumerate(archives, 1):
        rel = str(a.relative_to(ROOT))
        hits = scan_archive(a)
        if hits:
            results[rel] = hits
        if i % 200 == 0:
            print(f"  {i}/{len(archives)}  ({len(results)} with licence files)", flush=True)

    OUT.write_text(json.dumps(results, indent=1))
    from collections import Counter
    c = Counter(h["licence"] for v in results.values() for h in v)
    cc = Counter(h.get("commercial","?") for v in results.values() for h in v)
    print(f"\narchives with a licence file: {len(results)} / {len(archives)}")
    for k, n in c.most_common():
        print(f"  {n:6d}  {k}")
    print("\ncommercial use:")
    for k, n in cc.most_common():
        print(f"  {n:6d}  {k}")

if __name__ == "__main__":
    main()
