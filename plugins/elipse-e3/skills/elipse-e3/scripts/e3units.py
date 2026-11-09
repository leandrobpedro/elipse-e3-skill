#!/usr/bin/env python3
"""Unit helpers for Elipse E3 / Elipse Power screens.

E3 positions and sizes are in himetric (1/100 mm) almost everywhere, fonts in
points, colours in a BGR Long, and layers in a 32-bit mask that the screen CSV
stores as a *signed* decimal. This script converts between all of them so no
one has to do it by hand.

Usage
  e3units.py 24px                 -> himetric, pt
  e3units.py 635hm                -> px
  e3units.py 9pt                  -> px, himetric
  e3units.py 8 24 120 32 --px     -> a whole x y w h set in himetric (CSV form)
  e3units.py "#1141FF"            -> E3 colour Long
  e3units.py color 16728593       -> #RRGGBB
  e3units.py layer "&h80000000"   -> signed decimal for the CSV Layer column, bits
  e3units.py layer 3 32           -> mask for layers 3 and 32 (1-based)
  e3units.py label "Ordenar por" [--font Verdana] [--size 8.25] [--bold]
                                  -> suggested DrawString width in px and himetric

Pure standard library; works on Windows Python without extra packages.
"""
import argparse
import os
import re
import struct
import sys

HM_PER_PX = 2540 / 96          # 26.4583... himetric per pixel at 96 dpi
PT_PER_PX = 0.75               # 96 dpi: 1 px = 0.75 pt

# Measured on a real application: Verdana renders ~15 % wider in E3 than its metrics say,
# and a DrawString adds ~5 px of left inset. Labels sized to the metrics clipped.
RENDER_FACTOR = 1.15
LEFT_INSET_PX = 5
SAFETY_PX = 6


def fmt(v, decimals=6):
    """Number as E3's CSV writes it: decimal comma, trailing zeros trimmed."""
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if s else "0"


def px_to_hm(px):
    return px * HM_PER_PX


def hm_to_px(hm):
    return hm / HM_PER_PX


def parse_number(s):
    return float(str(s).replace(",", "."))


# ---------------------------------------------------------------- colours ---

def hex_to_e3(hexstr):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"not a #RRGGBB colour: {hexstr}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r + (g << 8) + (b << 16)


def e3_to_hex(value):
    v = int(value)
    if v < 0:
        # Negative values are system colours (&h80000000 + index), not RGB.
        return f"system colour index {v & 0xFF} (value {v})"
    r, g, b = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


# ----------------------------------------------------------------- layers ---

def parse_mask(s):
    s = s.strip()
    if s.lower().startswith("&h"):
        v = int(s[2:], 16)
    elif s.lower().startswith("0x"):
        v = int(s[2:], 16)
    else:
        v = int(s)
    return v & 0xFFFFFFFF


def signed32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def describe_mask(v):
    bits = [i + 1 for i in range(32) if v & (1 << i)]
    return (f"CSV Layer value : {signed32(v)}\n"
            f"VBScript literal: &h{v:X}\n"
            f"layers (1-based): {bits if len(bits) < 32 else 'all (-1)'}")


# ------------------------------------------------------------ font metrics --

FONT_FILES = {
    ("verdana", False): "verdana.ttf", ("verdana", True): "verdanab.ttf",
    ("tahoma", False): "tahoma.ttf", ("tahoma", True): "tahomabd.ttf",
    ("segoe ui", False): "segoeui.ttf", ("segoe ui", True): "segoeuib.ttf",
    ("arial", False): "arial.ttf", ("arial", True): "arialbd.ttf",
}


def _font_path(name, bold):
    fname = FONT_FILES.get((name.lower(), bold))
    if not fname:
        return None
    windir = os.environ.get("WINDIR", r"C:\Windows")
    p = os.path.join(windir, "Fonts", fname)
    return p if os.path.exists(p) else None


def _advance_widths(path):
    """Return (unitsPerEm, {codepoint: advance}) from a TrueType file."""
    data = open(path, "rb").read()
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(num_tables):
        tag, _, off, length = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tables[tag.decode("latin-1")] = (off, length)
    head = tables["head"][0]
    upem = struct.unpack(">H", data[head + 18: head + 20])[0]
    hhea = tables["hhea"][0]
    n_hmetrics = struct.unpack(">H", data[hhea + 34: hhea + 36])[0]
    hmtx = tables["hmtx"][0]
    adv = [struct.unpack(">H", data[hmtx + 4 * i: hmtx + 4 * i + 2])[0]
           for i in range(n_hmetrics)]
    cmap = tables["cmap"][0]
    n_sub = struct.unpack(">H", data[cmap + 2: cmap + 4])[0]
    sub = None
    for i in range(n_sub):
        pid, eid, off = struct.unpack(">HHI", data[cmap + 4 + 8 * i: cmap + 12 + 8 * i])
        if pid == 3 and eid == 1:
            sub = cmap + off
    if sub is None or struct.unpack(">H", data[sub: sub + 2])[0] != 4:
        raise RuntimeError("no Unicode BMP (format 4) cmap")
    segx2 = struct.unpack(">H", data[sub + 6: sub + 8])[0]
    seg = segx2 // 2
    ends = struct.unpack(f">{seg}H", data[sub + 14: sub + 14 + segx2])
    p = sub + 16 + segx2
    starts = struct.unpack(f">{seg}H", data[p: p + segx2]); p += segx2
    deltas = struct.unpack(f">{seg}h", data[p: p + segx2]); p += segx2
    ro_pos = p
    ros = struct.unpack(f">{seg}H", data[p: p + segx2])
    widths = {}
    for i in range(seg):
        for c in range(starts[i], min(ends[i], 0x2FF) + 1):
            if ros[i] == 0:
                gid = (c + deltas[i]) & 0xFFFF
            else:
                gpos = ro_pos + 2 * i + ros[i] + 2 * (c - starts[i])
                gid = struct.unpack(">H", data[gpos: gpos + 2])[0]
                if gid:
                    gid = (gid + deltas[i]) & 0xFFFF
            widths[c] = adv[min(gid, n_hmetrics - 1)]
    return upem, widths


def label_width(text, font="Verdana", size_pt=8.25, bold=False):
    px_size = size_pt / PT_PER_PX
    path = _font_path(font, bold)
    if path:
        upem, widths = _advance_widths(path)
        default = widths.get(ord("n"), upem // 2)
        metric = sum(widths.get(ord(c), default) for c in text) * px_size / upem
        how = f"metrics from {os.path.basename(path)}"
    else:
        metric = len(text) * px_size * (0.62 if bold else 0.58)
        how = "rough estimate (font file not found)"
    suggested = metric * RENDER_FACTOR + LEFT_INSET_PX + SAFETY_PX
    suggested = int(-(-suggested // 2) * 2)  # round up to an even pixel
    return metric, suggested, how


# --------------------------------------------------------------------- CLI --

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0].lower()

    if cmd == "color":
        print(e3_to_hex(argv[1]))
        return 0
    if cmd == "layer":
        if len(argv) == 2 and not re.fullmatch(r"\d{1,2}", argv[1]):
            print(describe_mask(parse_mask(argv[1])))
        else:
            v = 0
            for n in argv[1:]:
                k = int(n)
                if not 1 <= k <= 32:
                    raise SystemExit("layer numbers are 1..32")
                v |= 1 << (k - 1)
            print(describe_mask(v))
        return 0
    if cmd == "label":
        ap = argparse.ArgumentParser(prog="e3units.py label")
        ap.add_argument("text")
        ap.add_argument("--font", default="Verdana")
        ap.add_argument("--size", type=float, default=8.25, help="points")
        ap.add_argument("--bold", action="store_true")
        a = ap.parse_args(argv[1:])
        metric, suggested, how = label_width(a.text, a.font, a.size, a.bold)
        print(f"text width ({how}): {metric:.1f} px")
        print(f"suggested DrawString width: {suggested} px = {fmt(px_to_hm(suggested))} hm")
        return 0
    if argv[0].startswith("#"):
        print(hex_to_e3(argv[0]))
        return 0
    if "--px" in argv or "--hm" in argv:
        to_hm = "--px" in argv
        vals = [parse_number(a) for a in argv if not a.startswith("--")]
        names = ["X", "Y", "Width", "Height"] if len(vals) == 4 else [f"v{i}" for i in range(len(vals))]
        for n, v in zip(names, vals):
            print(f"{n}: {fmt(px_to_hm(v)) + ' hm' if to_hm else fmt(hm_to_px(v), 2) + ' px'}")
        return 0

    m = re.fullmatch(r"(-?[\d.,]+)\s*(px|hm|pt)", argv[0].lower())
    if not m:
        print(__doc__)
        return 2
    v, unit = parse_number(m.group(1)), m.group(2)
    if unit == "px":
        print(f"{fmt(v, 2)} px = {fmt(px_to_hm(v))} hm = {fmt(v * PT_PER_PX, 2)} pt")
    elif unit == "hm":
        print(f"{fmt(v)} hm = {fmt(hm_to_px(v), 3)} px")
    else:
        px = v / PT_PER_PX
        print(f"{fmt(v, 2)} pt = {fmt(px, 2)} px = {fmt(px_to_hm(px))} hm")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
