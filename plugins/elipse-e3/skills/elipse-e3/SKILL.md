---
name: elipse-e3
description: Field-tested rules and helper scripts for Elipse E3 and Elipse Power SCADA projects. Covers editing the "Documentação de Scripts" VBScript exports (.prj.vbs / .lib.vbs, Windows-1252) and screen / XControl CSV exports without corrupting them, E3 script-slot and scope rules (Sub/End Sub slots, RunProcedure, Item shadowing, Screen vs Parent), link expressions, Viewer/server timing, layers, himetric/pixel/point/colour conversion, and screen design that E3 draws well. Use it whenever the user works on an E3 or Elipse Power application — mentions E3, Elipse, E3 Studio, Viewer, a .prj / .lib / .dom file, an XControl, a script slot, an E3 screen or its CSV, himetric, or asks to write VBScript that runs inside E3 — even if they never name this skill.
---

# Elipse E3 / Elipse Power

E3 applications live in binary files (`.prj`, `.lib`, `.dom`) that only E3 Studio can
edit. You never touch those. You work on **text exports** the user makes from Studio,
and the user carries your changes back by hand. Most mistakes come from forgetting
one side of that round trip, or from rules the export doesn't show (a script can
look fine in the `.vbs` and still be rejected when pasted into Studio).

Elipse Power is built on the E3 platform: same Studio, object model and VBScript
engine. Everything here applies to it. Power's electrical-model objects aren't
covered yet. When you learn something about them, see "Growing this skill" below.

## The round trip

| Content | Export the user makes | What you edit | How it goes back |
|---|---|---|---|
| Scripts | Studio → *Documentação de Scripts* → `<name>.prj.vbs`, `<name>.lib.vbs` | procedures under a slot marker | user pastes **whole procedures** into that slot in Studio, then re-exports |
| Screens, XControls | Studio → export to CSV (one file per screen / XControl) | rows of the CSV | user imports the CSV in Studio, then re-exports |

Consequences:

- **Edits run ahead of the binary.** A change in an export is a draft until the user
  pastes or imports it. Never say it is live. End each change by saying exactly
  what to paste or import and where (slot marker, CSV file).
- **Deliver whole `Sub`/`Function` blocks**, never diffs. The user copies them into a
  script editor.
- **The export is a snapshot.** If it looks out of date (the user mentions a change
  that isn't there), ask for a fresh export before editing.

## Tools — use these instead of Write/Edit

The exports are **Windows-1252** and the CSVs are CRLF. Write and Edit save UTF-8,
which silently mangles every accented line in Portuguese files. The Read tool shows
those lines as mojibake: that's only how it displays them, the file isn't damaged.
So read and change exports through the bundled scripts (Python 3, standard
library only, any OS). They live in `scripts/` under this skill's base directory,
which is shown when the skill loads. The working directory is the user's project,
so call them by full path. In the examples, `<skill>` stands for that base
directory and file names are placeholders for the user's own exports.

```bash
# scripts (.vbs exports)
python <skill>/scripts/vbs_tool.py list  app.prj.vbs [filter]          # slots + line numbers
python <skill>/scripts/vbs_tool.py procs app.prj.vbs Scripts_Functions # procedures in a slot
python <skill>/scripts/vbs_tool.py show  app.prj.vbs MainScreen_OnPreShow --proc RefreshList
python <skill>/scripts/vbs_tool.py put   app.prj.vbs Scripts_Functions block.vbs [--before Foo] [--dry-run]
python <skill>/scripts/vbs_tool.py put   app.prj.vbs "<Screens.Main.btnX:btnX_Click()>" block.vbs --new-slot
python <skill>/scripts/vbs_tool.py check app.prj.vbs [--expect-nonascii N]

# screens (.CSV exports)
python <skill>/scripts/e3csv.py info  MainScreen.CSV --no-links        # objects, layers, geometry in px
python <skill>/scripts/e3csv.py show  MainScreen.CSV btnSave 'btnSave.*'
python <skill>/scripts/e3csv.py set   MainScreen.CSV btnSave.lbl Value="Salvar" Width=90px TextColor=#1142FF
python <skill>/scripts/e3csv.py clone MainScreen.CSV btnSave btnOpen --dx 120 --set lbl:Value=Abrir
python <skill>/scripts/e3csv.py clone Card.CSV grpBadge grpBadge --from MainScreen.CSV
python <skill>/scripts/e3csv.py check MainScreen.CSV

# units
python <skill>/scripts/e3units.py 24px | 635hm | 9pt | "#1142FF" | color 16728593
python <skill>/scripts/e3units.py layer "&h80000000"       # CSV Layer value and bit list
python <skill>/scripts/e3units.py label "Ordenar por" --size 8.25   # safe DrawString width
```

Each script prints its full usage with `--help`.

`put` takes a **UTF-8** block file. Write it with Write in a scratch or temp
directory (not in the user's project), accents included. It replaces procedures with the same name, adds new ones, refuses
characters that don't exist in Windows-1252, checks the slot rules, and leaves every
other byte untouched. Run `check` before you hand a file back. It reports the slot
audit, the encoding, and two lint warnings that otherwise fail silently at runtime:
a local named `item`, and `RunProcedure` aimed at a `Private` procedure.

## Script rules the export doesn't show

Details, with examples, are in [references/scripting.md](references/scripting.md).
Read it before writing more than a few lines of E3 VBScript.

1. **A slot must start with `Sub` and end with `End Sub`.** Module-level `Dim`s go
   *after* the first `End Sub`. If the last procedure is a `Function`, add an empty
   padding `Sub Foo()` / `End Sub` at the end. Studio rejects the paste otherwise.
2. **Every object is its own scope.** A screen, each control on it, each XControl,
   and each data object have separate scopes. Slots on the *same* object share one.
   From a child control, reach a screen procedure with `Screen.RunProcedure "Name"`,
   and that procedure must not be `Private`. Inside an internal tag's events
   `Screen` is undefined; use `Parent`.
3. **A shared library is an object whose slots hold procedures.** Other objects call
   it with `Application.GetObject("Data.Scripts").RunProcedure("Name", args)`.
   Pass **strings** across that boundary, not DOM nodes or objects the caller
   created.
4. **Never name a local `item`.** On screens and XControls `Item(...)` is the
   child-object accessor, and a local named `item` hides it.
5. **Link expressions evaluate every operand of `Or` and `And`.** If a tag may have
   no value (driver deactivated, no licence), reading `.Value` breaks the whole
   link. Guard it with a nested `IIf`, because only the branch taken is evaluated.
6. **A server event can still be running after the Viewer handler returns.**
   Writing a server tag from a click handler fires its server event *later*. Don't
   redraw in the same handler. Redraw from an internal tag linked to the
   `.Timestamp` of the last tag the server writes.
7. **Don't delete objects while iterating their parent.** It skips the next object.
   Collect the names first, then delete.
8. **Log with `Application.Trace "[ProcName] message"`.** A failed `RunProcedure`
   writes nothing anywhere, so trace around calls that cross objects.

## Screens

Format and import behaviour are in [references/screens-csv.md](references/screens-csv.md).
Units, fonts, layout and runtime patterns are in [references/ui-design.md](references/ui-design.md).
The essentials:

- **Units.** Geometry is in **himetric**: `hm = px × 2540 / 96` (24 px = 635 hm).
  Fonts are in points (`pt = px × 0.75`). Colours are a BGR `Long`
  (`R + G·256 + B·65536`). A `Layer` is a 32-bit mask, stored in the CSV as a signed
  decimal (`&h80000000` → `-2147483648`, all layers → `-1`). Give every size you
  spec in px **and** hm.
- **Import matches objects by name.** It updates them in place, never changes an
  object's class, and never deletes an object that is missing from the CSV. To
  change a class or remove an object, the user deletes it in Studio first (its
  scripts go with it, so they get pasted back from the `.vbs`).
- **Map rows by column name, not position.** Screens and XControls have different
  column sets. The header lists every property in case-insensitive alphabetical
  order. `e3csv.py clone --from` handles all of this.
- **Design for fixed sizes.** Resizing objects at runtime is expensive in E3, so
  states change colour, text and visibility only. Use fixed pools of instances
  (paged) rather than `AddObject` per row, and native ListViews for long lists.
- **Fonts.** Use only fonts that ship with Windows: Verdana (default), Segoe UI,
  Tahoma. Leave about 20 px of slack on label widths, because E3 draws text wider
  than the font metrics say (`e3units.py label`).

## Starting or onboarding an E3 repo

[references/project-setup.md](references/project-setup.md) has the repository
layout, `.gitattributes`, readable diffs for Windows-1252 files, and a `CLAUDE.md`
template that keeps project facts in the project and leaves the E3 rules to this
skill. Use it when the user starts a new E3/Power project or asks how to put one
under version control.

## Growing this skill

This skill lives in a git repo (`elipse-e3-skill`) shared with colleagues. When a
session uncovers E3 behaviour that isn't written here, offer to add it at the end
of the task: a bug that turned out to be an E3 quirk, an import that misbehaved, a
property that does nothing. Say whether it is **confirmed** or **inferred**, as the
references do, and keep project-specific facts out.
