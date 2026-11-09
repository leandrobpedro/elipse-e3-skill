#!/usr/bin/env python3
"""Read and edit Elipse E3 screen / XControl CSV exports without breaking them.

Studio exports a screen or XControl to CSV (one row per object, link and
sub-object) and imports it back, matching objects by name. The format is
fussy: ';' separator, decimal comma, CRLF, Windows-1252, strings in double
quotes with backslashes doubled, and a header that lists every property of
every class in the file in case-insensitive alphabetical order. This tool
keeps all of that intact and edits rows by column *name*, never by position.

Commands
  info   FILE                         objects with type, layer and geometry in px
  show   FILE NAME...                 non-empty properties of matching rows
  set    FILE NAME Col=Val...         change properties (NAME may be a glob)
  clone  FILE SRC NEW [options]       copy an object with its children and links
  delete FILE NAME                    remove an object with its children and links
  add-columns FILE Col...             add property columns in header order
  check  FILE                         validate structure and encoding

Value syntax for set / clone --set
  24px            -> himetric with decimal comma (636 -> "635")
  #1142FF         -> E3 colour Long (BGR)
  &h80000000      -> signed decimal layer mask
  True / 1,5 / 12 -> written unquoted;  anything else -> quoted string
  raw:<token>     -> written exactly as given (e.g. raw:"" or raw:)
  ""              -> empty string; an empty value (Col=) clears the field
Quoting follows the existing token, or the other rows of the same column.

clone options
  --from OTHER.CSV        take SRC from another export (screen <-> XControl ok)
  --dx PX --dy PX         move the copy (all rows: X, Y and line points)
  --set Col=Val           on the cloned root;  --set child.path:Col=Val on a child
  --before NAME | --after NAME   position (rows run front to back); default: after SRC

All writers take --dry-run. Nothing is written unless check passes afterwards.
"""
import argparse
import fnmatch
import os
import re
import sys
import tempfile

HM_PER_PX = 2540 / 96
FIXED = 2  # ObjectType;Name lead the header, the rest is sorted


class ToolError(Exception):
    pass


# ------------------------------------------------------------- tokens ---

def split_row(line):
    """Split one CSV line on ';' outside quotes, keeping each raw token."""
    out, cur, q, i = [], [], False, 0
    n = len(line)
    while i < n:
        c = line[i]
        if q:
            if c == '"':
                if i + 1 < n and line[i + 1] == '"':
                    cur.append('""'); i += 2; continue
                q = False
            cur.append(c)
        else:
            if c == ";":
                out.append("".join(cur)); cur = []; i += 1; continue
            if c == '"':
                q = True
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def unescape(raw):
    """Raw token -> Python value (str)."""
    if not (len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"'):
        return raw
    s = raw[1:-1].replace('""', '"')
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"\\": "\\", "r": "\r", "n": "\n", "t": "\t"}.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(s[i]); i += 1
    return "".join(out)


def quote(text):
    s = (text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
         .replace("\t", "\\t").replace('"', '""'))
    return f'"{s}"'


def fmt_num(v):
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


NUM = re.compile(r"^-?\d+([.,]\d+)?$")


def encode_value(value, existing_raw, column_raws):
    """User value -> raw token, following the column's quoting habit."""
    if value.startswith("raw:"):
        return value[4:]
    if value == "":
        return ""
    if value == '""':
        return '""'
    m = re.fullmatch(r"(-?[\d.,]+)px", value)
    if m:
        return fmt_num(float(m.group(1).replace(",", ".")) * HM_PER_PX)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        h = value[1:]
        return str(int(h[0:2], 16) + (int(h[2:4], 16) << 8) + (int(h[4:6], 16) << 16))
    if re.fullmatch(r"&[hH][0-9a-fA-F]+", value):
        v = int(value[2:], 16) & 0xFFFFFFFF
        return str(v - (1 << 32) if v & 0x80000000 else v)
    quoted = None
    if existing_raw:
        quoted = existing_raw.startswith('"')
    else:
        others = [r for r in column_raws if r]
        if others:
            quoted = sum(r.startswith('"') for r in others) * 2 > len(others)
    if quoted is None:
        quoted = not (NUM.match(value) or value in ("True", "False"))
    if quoted:
        return quote(value)
    if NUM.match(value):
        return value.replace(".", ",")
    return value


# --------------------------------------------------------------- model ---

class Csv:
    def __init__(self, path):
        self.path = path
        data = open(path, "rb").read()
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError as e:
            raise ToolError(f"{path}: not Windows-1252 ({e})")
        self.crlf = text.count("\r\n")
        self.lf_only = text.count("\n") - self.crlf
        lines = text.replace("\r\n", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        self.header = split_row(lines[0])
        self.rows = [split_row(l) for l in lines[1:]]
        self.col = {h: i for i, h in enumerate(self.header)}
        if "ObjectType" not in self.col or "Name" not in self.col:
            raise ToolError(f"{path}: header lacks ObjectType/Name - not an E3 screen export")

    # accessors
    def get(self, row, col):
        i = self.col.get(col)
        return unescape(row[i]) if i is not None and i < len(row) else ""

    def raw(self, row, col):
        i = self.col.get(col)
        return row[i] if i is not None and i < len(row) else ""

    def name(self, row):
        return self.get(row, "Name")

    def kind(self):
        return self.rows[0][0] if self.rows else "?"

    def column_raws(self, col):
        i = self.col[col]
        return [r[i] for r in self.rows if i < len(r)]

    def set(self, row, col, value):
        if col not in self.col:
            raise ToolError(f"column '{col}' is not in this file's header. Add it first with "
                            f"add-columns (only if the object's class really has it)")
        i = self.col[col]
        row[i] = encode_value(value, row[i], self.column_raws(col))

    def find(self, pattern):
        # a glob never reaches link rows unless the pattern names them
        links_ok = ".Links." in pattern or pattern.startswith("Links.")
        hits = [k for k, r in enumerate(self.rows) if self.name(r) and
                (self.name(r) == pattern or
                 (fnmatch.fnmatchcase(self.name(r), pattern) and
                  (links_ok or ".Links." not in "." + self.name(r))))]
        if not hits:
            raise ToolError(f"no row named '{pattern}'")
        return hits

    def subtree(self, k):
        """Row indices of object k, its children, links and nameless sub-rows."""
        base = self.name(self.rows[k])
        out = [k]
        j = k + 1
        while j < len(self.rows):
            n = self.name(self.rows[j])
            if n.startswith(base + ".") or (n == "" and j > 0):
                out.append(j); j += 1
            else:
                break
        return out

    def prefix(self):
        """PathName prefix, PathContainer and PathVolume used by this file's objects."""
        for r in self.rows[1:]:
            n, pn = self.name(r), self.get(r, "PathName")
            if n and pn.endswith(n):
                return (pn[: len(pn) - len(n)], self.raw(r, "PathContainer"),
                        self.raw(r, "PathVolume"))
        return None, None, None

    def add_columns(self, cols):
        added = []
        for c in cols:
            if c in self.col:
                continue
            rest = self.header[FIXED:]
            pos = FIXED + sum(1 for h in rest if h.lower() < c.lower())
            self.header.insert(pos, c)
            for r in self.rows:
                r.insert(pos, "")
            added.append(c)
            self.col = {h: i for i, h in enumerate(self.header)}
        return added

    def serialize(self):
        lines = [";".join(self.header)] + [";".join(r) for r in self.rows]
        return ("\r\n".join(lines) + "\r\n").encode("cp1252")

    def save(self):
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".e3csv_")
        with os.fdopen(fd, "wb") as f:
            f.write(self.serialize())
        os.replace(tmp, self.path)


# ------------------------------------------------------------- checking ---

def problems(c):
    out, warn = [], []
    rest = c.header[FIXED:]
    if c.header[:FIXED] != ["ObjectType", "Name"]:
        out.append("header must start with ObjectType;Name")
    if rest != sorted(rest, key=str.lower):
        bad = next(a for a, b in zip(rest, rest[1:]) if a.lower() > b.lower())
        out.append(f"header not in case-insensitive alphabetical order (near '{bad}')")
    if len(set(c.header)) != len(c.header):
        out.append("duplicate header columns")
    seen = {}
    for k, r in enumerate(c.rows):
        line = k + 2
        if len(r) != len(c.header):
            out.append(f"line {line}: {len(r)} fields, header has {len(c.header)}")
            continue
        n = c.name(r)
        if n:
            if n in seen:
                out.append(f"line {line}: duplicate name '{n}' (also line {seen[n]})")
            seen[n] = line
            parent = n.rsplit(".Links.", 1)[0] if ".Links." in n else n.rpartition(".")[0]
            if parent and parent not in seen and parent != "Links":
                out.append(f"line {line}: '{n}' comes before (or without) its parent '{parent}'")
        for col in ("X", "Y", "Width", "Height"):
            v = c.raw(r, col)
            if v and not re.fullmatch(r"-?\d+(,\d+)?", v):
                out.append(f"line {line}: {col}={v!r} - numbers use a decimal comma")
        lay = c.raw(r, "Layer")
        if lay and not re.fullmatch(r"-?\d+", lay):
            out.append(f"line {line}: Layer={lay!r} must be a signed decimal Long")
        for i, tok in enumerate(r):
            if tok.startswith('"') and (len(tok) < 2 or not tok.endswith('"')):
                out.append(f"line {line}: unterminated quote in column {c.header[i]}")
    if c.lf_only:
        out.append(f"{c.lf_only} lines end in LF only - E3 writes CRLF")
    return out, warn


# ------------------------------------------------------------- commands ---

def px(c, r, col):
    v = c.raw(r, col)
    try:
        return f"{float(v.replace(',', '.')) / HM_PER_PX:.0f}"
    except ValueError:
        return "-"


def cmd_info(a):
    c = Csv(a.file)
    print(f"{a.file}: {c.kind()} export, {len(c.rows)} rows, {len(c.header)} columns, "
          f"{'CRLF' if not c.lf_only else 'MIXED line endings'}")
    pfx, cont, vol = c.prefix()
    print(f"PathName prefix: {pfx}   PathContainer: {cont}")
    print(f"{'line':>5} {'type':16} {'layer':>12} {'x':>5} {'y':>5} {'w':>5} {'h':>5}  name")
    for k, r in enumerate(c.rows):
        n = c.name(r)
        if a.no_links and ".Links." in f".{n}":
            continue
        lay = c.raw(r, "Layer")
        lay_s = f"&h{int(lay) & 0xFFFFFFFF:X}" if re.fullmatch(r"-?\d+", lay or "") else ""
        print(f"{k + 2:>5} {r[0][:16]:16} {lay_s:>12} {px(c, r, 'X'):>5} {px(c, r, 'Y'):>5} "
              f"{px(c, r, 'Width'):>5} {px(c, r, 'Height'):>5}  {n}")


def cmd_show(a):
    c = Csv(a.file)
    for pat in a.names:
        for k in c.find(pat):
            r = c.rows[k]
            print(f"--- line {k + 2}: {r[0]} {c.name(r)}")
            for i, h in enumerate(c.header):
                if i < len(r) and r[i] != "" and h not in ("ObjectType", "Name"):
                    extra = ""
                    if h in ("X", "Y", "Width", "Height"):
                        extra = f"   ({px(c, r, h)} px)"
                    print(f"  {h} = {unescape(r[i])}{extra}")


def parse_assign(s):
    if "=" not in s:
        raise ToolError(f"expected Col=Value, got '{s}'")
    col, val = s.split("=", 1)
    target = None
    if ":" in col:
        target, col = col.rsplit(":", 1)
    return target, col.strip(), val


def commit(a, c, msg):
    errs, _ = problems(c)
    if errs:
        print("NOT WRITTEN:\n  " + "\n  ".join(errs[:20]))
        return 1
    if a.dry_run:
        print(msg + " (dry run - nothing written)")
        return 0
    c.save()
    print(msg + f" -> {c.path}")
    return 0


def cmd_set(a):
    c = Csv(a.file)
    hits = c.find(a.name)
    for k in hits:
        for s in a.assign:
            _, col, val = parse_assign(s)
            c.set(c.rows[k], col, val)
    return commit(a, c, f"set {len(a.assign)} value(s) on {len(hits)} row(s)")


def cmd_add_columns(a):
    c = Csv(a.file)
    added = c.add_columns(a.cols)
    return commit(a, c, f"added columns: {', '.join(added) or 'none (all present)'}")


def cmd_delete(a):
    c = Csv(a.file)
    ks = c.subtree(c.find(a.name)[0])
    names = [c.name(c.rows[k]) or "(sub-row)" for k in ks]
    for k in reversed(ks):
        del c.rows[k]
    rc = commit(a, c, f"deleted {len(ks)} row(s): {', '.join(names[:8])}{' ...' if len(names) > 8 else ''}")
    print("note: importing does NOT delete objects that are missing from the CSV - "
          "delete the object in Studio as well.")
    return rc


def cmd_clone(a):
    dst = Csv(a.file)
    src = Csv(a.src_file) if a.src_file else dst
    k = src.find(a.src)[0]
    if len(src.find(a.src)) > 1:
        raise ToolError(f"'{a.src}' matches several rows - name one object")
    old = src.name(src.rows[k])
    new = a.new
    if any(dst.name(r) == new for r in dst.rows):
        raise ToolError(f"'{new}' already exists in {a.file}")
    sub = src.subtree(k)

    # map columns by name; add what the destination lacks
    needed = [h for i, h in enumerate(src.header)
              if any(i < len(src.rows[j]) and src.rows[j][i] != "" for j in sub)]
    added = dst.add_columns([h for h in needed if h not in dst.col])
    if added:
        print(f"added columns to {a.file}: {', '.join(added)}")
    pfx, cont, vol = dst.prefix()

    clones = []
    for j in sub:
        sr = src.rows[j]
        nr = [""] * len(dst.header)
        for i, h in enumerate(src.header):
            if i < len(sr) and sr[i] != "":
                nr[dst.col[h]] = sr[i]
        n = src.name(sr)
        if n:
            nn = new + n[len(old):]
            nr[dst.col["Name"]] = quote(nn)
            # rebase the paths on the destination file's own convention
            if "PathName" in dst.col and src.raw(sr, "PathName") and pfx is not None:
                nr[dst.col["PathName"]] = quote(pfx + nn)
            if "PathContainer" in dst.col and src.raw(sr, "PathContainer") and cont:
                nr[dst.col["PathContainer"]] = cont
            if "PathVolume" in dst.col and src.raw(sr, "PathVolume") and vol:
                nr[dst.col["PathVolume"]] = vol
        for col, d in (("X", a.dx), ("Y", a.dy)):
            if d and col in dst.col and nr[dst.col[col]]:
                v = float(nr[dst.col[col]].replace(",", ".")) + d * HM_PER_PX
                nr[dst.col[col]] = fmt_num(v)
        clones.append(nr)

    for s in a.set or []:
        target, col, val = parse_assign(s)
        want = new if not target else f"{new}.{target}"
        rows = [r for r in clones if dst.name(r) == want]
        if not rows:
            raise ToolError(f"--set target '{want}' is not among the cloned rows")
        dst.set(rows[0], col, val)

    if a.before or a.after:
        ref = dst.find(a.before or a.after)[0]
        pos = ref if a.before else dst.subtree(ref)[-1] + 1
    elif src is dst:
        pos = dst.subtree(dst.find(old)[0])[-1] + 1
    else:
        pos = len(dst.rows)
    dst.rows[pos:pos] = clones
    return commit(a, dst, f"cloned {old} -> {new} ({len(clones)} rows) at line {pos + 2}")


def cmd_check(a):
    c = Csv(a.file)
    errs, warns = problems(c)
    print(f"{a.file}: {c.kind()}, {len(c.rows)} rows, {len(c.header)} columns")
    for e in errs:
        print("ERROR:", e)
    for w in warns:
        print("warning:", w)
    if not errs:
        print("OK")
    return 1 if errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("info"); p.add_argument("file")
    p.add_argument("--no-links", action="store_true", help="hide link rows")
    p.set_defaults(fn=cmd_info)
    p = sp.add_parser("show"); p.add_argument("file"); p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_show)
    p = sp.add_parser("set"); p.add_argument("file"); p.add_argument("name")
    p.add_argument("assign", nargs="+"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_set)
    p = sp.add_parser("clone"); p.add_argument("file"); p.add_argument("src"); p.add_argument("new")
    p.add_argument("--from", dest="src_file"); p.add_argument("--dx", type=float, default=0)
    p.add_argument("--dy", type=float, default=0); p.add_argument("--set", action="append")
    g = p.add_mutually_exclusive_group(); g.add_argument("--before"); g.add_argument("--after")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_clone)
    p = sp.add_parser("delete"); p.add_argument("file"); p.add_argument("name")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_delete)
    p = sp.add_parser("add-columns"); p.add_argument("file"); p.add_argument("cols", nargs="+")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_add_columns)
    p = sp.add_parser("check"); p.add_argument("file"); p.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        return a.fn(a) or 0
    except ToolError as e:
        print("error:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
