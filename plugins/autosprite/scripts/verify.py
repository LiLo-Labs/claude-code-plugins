#!/usr/bin/env python3
"""Prove an output directory's sheet, atlas and engine files all agree.

    verify.py --dir hero-sprites/ --reference hero.png
"""

import argparse
import json
import sys

import _bootstrap  # noqa: F401
from spritepipe import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--name", help="sheet name; found automatically if omitted")
    parser.add_argument("--reference", help="the source image, to check the palette")
    parser.add_argument("--rig", help="the rig.json, to check the rest pose")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = verify.verify_directory(args.dir, args.name, args.reference, args.rig)
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.report())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
