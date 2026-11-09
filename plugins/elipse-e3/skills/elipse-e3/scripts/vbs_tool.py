#!/usr/bin/env python3
"""Read and edit Elipse E3 "Documentacao de Scripts" exports byte-safely.

The exports (<project>.prj.vbs, <library>.lib.vbs) are Windows-1252. Opening
them with a UTF-8 editor and saving rewrites every accented line, so this tool
works on bytes: it re-encodes only the lines you hand it, keeps every other
byte exactly as it was, and checks the E3 slot rules before it writes.

A slot starts at a marker line   <Object.Path:Handler(args)>
and runs until the next marker. E3 accepts a slot only if its first code line
starts with "Sub" and its last line is "End Sub".

Commands
  list   FILE [FILTER]              slots with their line numbers
  procs  FILE SLOT                  procedures inside one slot
  show   FILE SLOT [--proc NAME]    print a slot (or one procedure) as UTF-8
  put    FILE SLOT BLOCK [--before NAME | --after NAME] [--new-slot] [--dry-run]
                                    replace or add the procedures in BLOCK
  remove FILE SLOT NAME [--dry-run] delete one procedure from a slot
  check  FILE [--expect-nonascii N] encoding, slot rules and lint for the file

SLOT is the marker text with or without the angle brackets, or any substring
that matches exactly one marker (e.g. "Scripts_Functions").

BLOCK is a UTF-8 file (accents welcome) holding whole procedures. For each
procedure in it:
  * same name already in the slot -> that procedure is replaced in place.
    Comment lines directly above it in BLOCK replace the comment lines directly
    above the existing one; with no comments in BLOCK the old ones are kept.
  * new name -> inserted at the end of the slot, or at --before/--after.
Module-level lines (Dim g_x ...) in BLOCK travel with the procedure that
follows them, and are only allowed for new procedures.
--new-slot creates SLOT (give the full marker) if it does not exist.
"""
import argparse
import os
import re
import sys
import tempfile

MARKER = re.compile(rb"^<([^<>:]+):([^<>]*)>\s*$")
PROC_START = re.compile(
    r"^\s*(?:(Public|Private)\s+)?(?:Default\s+)?(Sub|Function)\s+([A-Za-z_]\w*)", re.I)
PROC_END = re.compile(r"^\s*End\s+(Sub|Function)\b", re.I)
COMMENT = re.compile(r"^\s*('|Rem\b)", re.I)


class ToolError(Exception):
    pass


# ------------------------------------------------------------------ model ---

def read_lines(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.splitlines(keepends=True)


def strip_eol(b):
    return b.rstrip(b"\r\n")


def dec(b):
    return strip_eol(b).decode("cp1252", errors="replace")


def slots(lines):
    """[(marker_index, end_index_exclusive, marker_text)]"""
    idx = [i for i, l in enumerate(lines) if MARKER.match(strip_eol(l))]
    out = []
    for k, i in enumerate(idx):
        end = idx[k + 1] if k + 1 < len(idx) else len(lines)
        out.append((i, end, dec(lines[i])))
    return out


def find_slot(lines, query, allow_missing=False):
    q = query.strip()
    q_full = q if q.startswith("<") else f"<{q}>"
    all_slots = slots(lines)
    exact = [s for s in all_slots if s[2].strip() == q_full]
    if exact:
        return exact[0]
    sub = [s for s in all_slots if q.lower() in s[2].lower()]
    if len(sub) == 1:
        return sub[0]
    if allow_missing and not sub:
        return None
    if not sub:
        raise ToolError(f"no slot matches '{query}'")
    raise ToolError(f"'{query}' matches {len(sub)} slots:\n  " +
                    "\n  ".join(f"{s[0] + 1}: {s[2]}" for s in sub[:20]))


def procedures(text_lines, offset=0):
    """Procedures in a list of decoded lines.
    -> [dict(name, kind, scope, start, end)] with absolute, inclusive indices."""
    out, cur = [], None
    for i, t in enumerate(text_lines):
        if cur is None:
            m = PROC_START.match(t)
            if m and not PROC_END.match(t):
                cur = dict(scope=(m.group(1) or "").title(), kind=m.group(2).title(),
                           name=m.group(3), start=i + offset)
        else:
            m = PROC_END.match(t)
            if m:
                cur["end"] = i + offset
                out.append(cur)
                cur = None
    if cur is not None:
        raise ToolError(f"procedure {cur['name']} (line {cur['start'] + 1}) has no End {cur['kind']}")
    return out


def eol_of(lines, i):
    l = lines[i] if 0 <= i < len(lines) else b"\r\n"
    return b"\r\n" if l.endswith(b"\r\n") else b"\n"


# -------------------------------------------------------------- checking ---

def audit_slot(lines, s):
    """Problems with one slot -> list of strings."""
    i, end, marker = s
    body = [dec(l) for l in lines[i + 1:end]]
    code = [t for t in body if t.strip()]
    problems = []
    if not code:
        return [f"{marker}  EMPTY SLOT"]
    if not re.match(r"^Sub\s", code[0]):
        problems.append(f"{marker}  BAD START (must open with 'Sub'): {code[0].strip()}")
    if code[-1].strip() != "End Sub":
        problems.append(f"{marker}  BAD END (must close with 'End Sub'): {code[-1].strip()}")
    try:
        procs = procedures(body, i + 1)
    except ToolError as e:
        return problems + [f"{marker}  {e}"]
    seen = {}
    for p in procs:
        k = p["name"].lower()
        if k in seen:
            problems.append(f"{marker}  DUPLICATE procedure {p['name']} "
                            f"(lines {seen[k] + 1} and {p['start'] + 1})")
        seen[k] = p["start"]
    return problems


def lint(lines):
    """Warnings that are not fatal but bite at runtime."""
    warns = []
    all_slots = slots(lines)
    private = {}
    for i, end, marker in all_slots:
        body = [dec(l) for l in lines[i + 1:end]]
        try:
            for p in procedures(body, i + 1):
                if p["scope"] == "Private":
                    private.setdefault(p["name"].lower(), []).append((p["start"], marker))
        except ToolError:
            pass
        for k, t in enumerate(body):
            if re.search(r"\b(Dim|For\s+Each|Set)\s+item\b(?!\s*[(.])", t, re.I) and not COMMENT.match(t):
                warns.append(f"line {i + 2 + k}: local named 'item' shadows the Item() child "
                             f"accessor on screens/XControls - rename it (e.g. itm)")
    for i, l in enumerate(lines):
        t = dec(l)
        for m in re.finditer(r'RunProcedure\s*\(?\s*"(\w+)"', t):
            hit = private.get(m.group(1).lower())
            if hit:
                warns.append(f"line {i + 1}: RunProcedure \"{m.group(1)}\" but it is declared "
                             f"Private at line {hit[0][0] + 1} - the call fails silently")
    return warns


def nonascii_lines(lines):
    return sum(1 for l in lines if any(b >= 0x80 for b in l))


def encoding_report(lines):
    data = b"".join(lines)
    has_high = any(b >= 0x80 for b in data)
    try:
        data.decode("utf-8")
        utf8_ok = True
    except UnicodeDecodeError:
        utf8_ok = False
    return has_high, utf8_ok


# ------------------------------------------------------------- the block ---

def load_block(path):
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ToolError(f"{path} is not UTF-8 ({e}). Write the block as UTF-8.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    for n, r in enumerate(rows, 1):
        try:
            r.encode("cp1252")
        except UnicodeEncodeError as e:
            bad = r[e.start:e.end]
            raise ToolError(f"{path}:{n}: character {bad!r} (U+{ord(bad[0]):04X}) does not exist "
                            f"in Windows-1252; replace it (smart quotes, emoji, arrows...)")
    return rows


def block_units(rows):
    """Split block rows into units: (preamble_comments, preamble_code, proc_rows, proc)."""
    procs = procedures(rows)
    if not procs:
        raise ToolError("the block holds no Sub/Function")
    units, cursor = [], 0
    for p in procs:
        pre = rows[cursor:p["start"]]
        # trailing comment lines directly above the procedure = its header
        k = len(pre)
        while k > 0 and pre[k - 1].strip() and COMMENT.match(pre[k - 1]):
            k -= 1
        header = pre[k:]
        lead = pre[:k]
        code = [t for t in lead if t.strip() and not COMMENT.match(t)]
        units.append(dict(name=p["name"], kind=p["kind"], lead=lead, has_code=bool(code),
                          header=header, body=rows[p["start"]:p["end"] + 1]))
        cursor = p["end"] + 1
    tail = rows[cursor:]
    if any(t.strip() for t in tail):
        units[-1]["tail"] = tail
    return units


def enc(rows, eol):
    return [r.encode("cp1252") + eol for r in rows]


# -------------------------------------------------------------- commands ---

def cmd_list(a):
    lines = read_lines(a.file)
    for i, end, m in slots(lines):
        if not a.filter or a.filter.lower() in m.lower():
            print(f"{i + 1:>6}  {m}   ({end - i - 1} lines)")


def cmd_procs(a):
    lines = read_lines(a.file)
    i, end, m = find_slot(lines, a.slot)
    print(m)
    for p in procedures([dec(l) for l in lines[i + 1:end]], i + 1):
        print(f"  {p['start'] + 1:>6}-{p['end'] + 1:<6} {p['scope'] or '':7} {p['kind']:8} {p['name']}")


def cmd_show(a):
    lines = read_lines(a.file)
    i, end, m = find_slot(lines, a.slot)
    lo, hi = i, end
    if a.proc:
        ps = [p for p in procedures([dec(l) for l in lines[i + 1:end]], i + 1)
              if p["name"].lower() == a.proc.lower()]
        if not ps:
            raise ToolError(f"no procedure {a.proc} in {m}")
        lo, hi = ps[0]["start"], ps[0]["end"] + 1
    out = sys.stdout
    for k in range(lo, hi):
        out.write(f"{k + 1:>6}\t{dec(lines[k])}\n")


def write_atomic(path, lines):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".vbs_tool_")
    with os.fdopen(fd, "wb") as f:
        f.write(b"".join(lines))
    os.replace(tmp, path)


def finish(a, before, after, touched_markers, added_nonascii):
    problems = []
    for s in slots(after):
        if s[2].strip() in touched_markers:
            problems += audit_slot(after, s)
    n0, n1 = nonascii_lines(before), nonascii_lines(after)
    has_high, utf8_ok = encoding_report(after)
    print(f"non-ASCII lines: {n0} -> {n1} (expected {n0 + added_nonascii})")
    if n1 != n0 + added_nonascii:
        problems.append("non-ASCII line count is off - bytes outside the edit changed")
    if has_high and utf8_ok:
        problems.append("result decodes as UTF-8 - the file looks re-encoded")
    if problems:
        print("NOT WRITTEN:\n  " + "\n  ".join(problems))
        return 1
    if a.dry_run:
        print("dry run - nothing written")
        return 0
    write_atomic(a.file, after)
    print(f"written: {a.file}")
    for w in lint(after):
        print("warning:", w)
    return 0


def cmd_put(a):
    lines = read_lines(a.file)
    rows = load_block(a.block)
    units = block_units(rows)
    s = find_slot(lines, a.slot, allow_missing=a.new_slot)
    new = list(lines)
    if s is None:
        marker = a.slot.strip()
        if not marker.startswith("<"):
            marker = f"<{marker}>"
        if not re.match(r"^<[^<>:]+:[^<>]+\([^<>]*\)>$", marker):
            raise ToolError("--new-slot needs the full marker, e.g. "
                            "'<Folder.Object:Object_Event()>'")
        all_slots = slots(lines)
        pos = len(lines)
        for i, end, m in all_slots:
            if m.lower() > marker.lower():
                pos = i
                break
        eol = eol_of(lines, all_slots[0][0] if all_slots else 0)
        new[pos:pos] = [marker.encode("cp1252") + eol, eol]
        s = (pos, pos + 2, marker)  # the blank line separates it from the next marker
        print(f"created slot {marker} at line {pos + 1}")
    i, end, marker = s
    eol = eol_of(new, i)
    added_nonascii = 0

    for u in units:
        body_text = [dec(l) for l in new[i + 1:end]]
        procs = procedures(body_text, i + 1)
        same = [p for p in procs if p["name"].lower() == u["name"].lower()]
        tail = u.get("tail", [])
        if same:
            if u["has_code"]:
                raise ToolError(f"{u['name']}: module-level code above it in the block, but the "
                                f"procedure already exists. Put Dims in their own put with --after.")
            p = same[0]
            lo = p["start"]
            if u["header"]:
                while lo - 1 > i and dec(new[lo - 1]).strip() and COMMENT.match(dec(new[lo - 1])):
                    lo -= 1
            repl = (u["header"] if u["header"] else []) + u["body"] + tail
            old = new[lo:p["end"] + 1]
            new[lo:p["end"] + 1] = enc(repl, eol)
            added_nonascii += nonascii_lines(enc(repl, eol)) - nonascii_lines(old)
            end += len(repl) - len(old)
            print(f"replaced {u['kind']} {u['name']} (lines {lo + 1}-{p['end'] + 1})")
        else:
            rows_in = u["lead"] + u["header"] + u["body"] + tail
            if a.before or a.after:
                ref = (a.before or a.after).lower()
                anchors = [p for p in procs if p["name"].lower() == ref]
                if not anchors:
                    raise ToolError(f"no procedure {a.before or a.after} in {marker}")
                if a.before:
                    pos = anchors[0]["start"]
                    while pos - 1 > i and dec(new[pos - 1]).strip() and COMMENT.match(dec(new[pos - 1])):
                        pos -= 1
                    chunk = rows_in + [""]
                    if strip_eol(new[pos - 1]).strip():
                        chunk = [""] + chunk
                else:
                    pos = anchors[0]["end"] + 1
                    chunk = [""] + rows_in if rows_in[0].strip() else rows_in
            else:
                pos = end
                while pos - 1 > i and not strip_eol(new[pos - 1]).strip():
                    pos -= 1
                empty_slot = pos == i + 1
                chunk = ([""] if rows_in[0].strip() and not empty_slot else []) + rows_in
            ins = enc(chunk, eol)
            new[pos:pos] = ins
            end += len(ins)
            added_nonascii += nonascii_lines(ins)
            print(f"added {u['kind']} {u['name']} at line {pos + 1}")
    return finish(a, lines, new, {marker.strip()}, added_nonascii)


def cmd_remove(a):
    lines = read_lines(a.file)
    i, end, marker = find_slot(lines, a.slot)
    ps = [p for p in procedures([dec(l) for l in lines[i + 1:end]], i + 1)
          if p["name"].lower() == a.name.lower()]
    if not ps:
        raise ToolError(f"no procedure {a.name} in {marker}")
    p = ps[0]
    lo = p["start"]
    while lo - 1 > i and dec(lines[lo - 1]).strip() and COMMENT.match(dec(lines[lo - 1])):
        lo -= 1
    hi = p["end"] + 1
    if hi < end and not strip_eol(lines[hi]).strip():
        hi += 1
    new = lines[:lo] + lines[hi:]
    print(f"removed {p['kind']} {p['name']} with its header (lines {lo + 1}-{hi})")
    return finish(a, lines, new, {marker.strip()}, -nonascii_lines(lines[lo:hi]))


def cmd_check(a):
    lines = read_lines(a.file)
    rc = 0
    has_high, utf8_ok = encoding_report(lines)
    n = nonascii_lines(lines)
    crlf = sum(1 for l in lines if l.endswith(b"\r\n"))
    print(f"{a.file}: {len(lines)} lines, {len(slots(lines))} slots, "
          f"{n} non-ASCII lines, {crlf} CRLF / {len(lines) - crlf} LF")
    if has_high and utf8_ok:
        print("CORRUPTED? the file decodes as UTF-8; E3 exports are Windows-1252")
        rc = 1
    if a.expect_nonascii is not None and n != a.expect_nonascii:
        print(f"MISMATCH: expected {a.expect_nonascii} non-ASCII lines, found {n}")
        rc = 1
    problems = []
    for s in slots(lines):
        problems += audit_slot(lines, s)
    for p in problems:
        print("ERROR:", p)
    for w in lint(lines):
        print("warning:", w)
    if problems:
        rc = 1
    if rc == 0:
        print("OK")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list"); p.add_argument("file"); p.add_argument("filter", nargs="?")
    p.set_defaults(fn=cmd_list)
    p = sp.add_parser("procs"); p.add_argument("file"); p.add_argument("slot"); p.set_defaults(fn=cmd_procs)
    p = sp.add_parser("show"); p.add_argument("file"); p.add_argument("slot"); p.add_argument("--proc")
    p.set_defaults(fn=cmd_show)
    p = sp.add_parser("put"); p.add_argument("file"); p.add_argument("slot"); p.add_argument("block")
    g = p.add_mutually_exclusive_group(); g.add_argument("--before"); g.add_argument("--after")
    p.add_argument("--new-slot", action="store_true"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_put)
    p = sp.add_parser("remove"); p.add_argument("file"); p.add_argument("slot"); p.add_argument("name")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_remove)
    p = sp.add_parser("check"); p.add_argument("file"); p.add_argument("--expect-nonascii", type=int)
    p.set_defaults(fn=cmd_check)
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
