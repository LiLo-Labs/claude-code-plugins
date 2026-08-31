"""Hex to CIE Lab. The only colour conversion this needs."""

import numpy as np


def hex_to_lab(value):
    from colour import XYZ_to_Lab, sRGB_to_XYZ
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    rgb = np.array([int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    return np.asarray(XYZ_to_Lab(sRGB_to_XYZ(rgb)), dtype=float)


def lab_to_hex(lab):
    from colour import Lab_to_XYZ, XYZ_to_sRGB
    rgb = np.clip(XYZ_to_sRGB(Lab_to_XYZ(np.asarray(lab, dtype=float))), 0, 1)
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in rgb)
