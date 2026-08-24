"""Codec for the per-triangle paint state strings used by OrcaSlicer / Bambu Studio.

A painted 3MF stores paint as a `paint_color` attribute on each `<triangle>`
element (PrusaSlicer calls the same thing `slic3rpe:mmu_segmentation`). The value
is a hex string encoding a recursive triangle-subdivision tree.

The encoding is ported verbatim from OrcaSlicer:
  - TriangleSelector::serialize()            (src/libslic3r/TriangleSelector.cpp)
  - FacetsAnnotation::get_triangle_as_string()  (src/libslic3r/Model.cpp)

Bit layout, per triangle, LSB-first within the stream:
  2 bits  split_sides (0 for an unsplit/leaf triangle)
  if split_sides:
      2 bits  special_side, then split_sides+1 children, serialized in
              REVERSE child order (child_idx counts down to 0)
  else (leaf):
      if state >= 3:  bits `11` then 4 bits of (state - 3)
      else:           2 bits of state

The bitstream is then chunked into nibbles; each nibble is rendered as a hex
digit and PREPENDED to the output, so the string reads back-to-front.

State values are `EnforcerBlockerType`: 0 = unpainted (falls back to the
object's own filament), n = Extruder n for n in 1..16.
"""

MAX_FILAMENT = 16


class PaintEncodingError(ValueError):
    """Raised when a paint_color string cannot be decoded."""


# --------------------------------------------------------------------------
# bitstream <-> hex string
# --------------------------------------------------------------------------

def bits_to_string(bits):
    """Render a bitstream as OrcaSlicer's reversed-nibble hex string."""
    if len(bits) % 4 != 0:
        raise PaintEncodingError(
            "bitstream length %d is not a multiple of 4" % len(bits))
    out = []
    for offset in range(0, len(bits), 4):
        code = 0
        for i in (3, 2, 1, 0):
            code = (code << 1) | int(bool(bits[offset + i]))
        out.insert(0, "0123456789ABCDEF"[code])
    return "".join(out)


def string_to_bits(text):
    """Inverse of :func:`bits_to_string`."""
    bits = []
    for ch in reversed(text.strip()):
        try:
            dec = int(ch, 16)
        except ValueError:
            raise PaintEncodingError("invalid hex digit %r in %r" % (ch, text))
        if ch.islower():
            # OrcaSlicer only ever emits uppercase; accept lowercase on read.
            pass
        for i in range(4):
            bits.append(bool(dec & (1 << i)))
    return bits


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

def _leaf_bits(state):
    if not (0 <= state <= MAX_FILAMENT):
        raise PaintEncodingError("state %d out of range 0..%d" % (state, MAX_FILAMENT))
    bits = []
    if state >= 3:
        bits += [True, True]
        n = state - 3
        for i in range(4):
            bits.append(bool(n & (1 << i)))
    else:
        bits.append(bool(state & 0b01))
        bits.append(bool(state & 0b10))
    return bits


def encode_solid(filament):
    """Paint a whole triangle with one filament (1-based).

    Returns '' for filament 0 (unpainted), which means the attribute should be
    omitted entirely rather than written as an empty string.
    """
    if filament == 0:
        return ""
    return bits_to_string([False, False] + _leaf_bits(filament))


# Precomputed for the common case; also serves as a regression fixture.
SOLID = {n: encode_solid(n) for n in range(1, MAX_FILAMENT + 1)}


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------

class _Reader:
    def __init__(self, bits):
        self.bits = bits
        self.pos = 0

    def take(self, count):
        if self.pos + count > len(self.bits):
            raise PaintEncodingError("bitstream truncated")
        value = 0
        for i in range(count):
            if self.bits[self.pos + i]:
                value |= 1 << i
        self.pos += count
        return value


def decode(text):
    """Decode a paint_color string into a nested tree.

    Leaves are ``{'state': n}``; split nodes are
    ``{'special_side': s, 'children': [...]}`` with children in the order
    OrcaSlicer stores them (reverse child index).
    """
    reader = _Reader(string_to_bits(text))

    def read_node():
        split_sides = reader.take(2)
        if split_sides:
            special_side = reader.take(2)
            children = [read_node() for _ in range(split_sides + 1)]
            return {"special_side": special_side, "children": children}
        value = reader.take(2)
        if value == 0b11:
            return {"state": reader.take(4) + 3}
        return {"state": value}

    return read_node()


def filaments_used(text):
    """Set of filament indices referenced by a paint_color string."""
    found = set()

    def walk(node):
        if "state" in node:
            if node["state"]:
                found.add(node["state"])
        else:
            for child in node["children"]:
                walk(child)

    walk(decode(text))
    return found
