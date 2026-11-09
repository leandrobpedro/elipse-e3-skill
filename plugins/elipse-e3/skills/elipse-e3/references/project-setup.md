# Setting up an E3 / Elipse Power repository

How to put an E3 application under git so that Claude (and colleagues) can work
on it through text exports.

## Layout

```
<app>.prj            E3 project: screens, data folders, project scripts   (binary)
<app>.lib            E3 library: XControls / XObjects                      (binary)
<app>.dom            domain file                                           (binary)
docs/
  scripts/<app>.prj.vbs     Documentação de Scripts export of the project (CP1252)
  scripts/<app>.lib.vbs     same for each library
  screens/<Screen>.CSV      one export per screen / XControl you edit as text
  architecture.md           object model, layers, boot sequence (project-specific)
assets/icons/*.wmf          icons referenced by DrawPicture.Filename (relative paths)
CLAUDE.md
.gitattributes
.gitignore
```

Commit the binaries **and** their exports in the same commit, so the history
shows what each binary change did to the scripts and screens.

## .gitattributes

```gitattributes
*.prj  binary
*.lib  binary
*.dom  binary
*.mdb  binary
*.wmf  binary

# exports: keep bytes as E3 wrote them, but show readable diffs
*.vbs  -text diff=cp1252
*.CSV  -text diff=cp1252
*.csv  -text diff=cp1252
```

Then, once per clone:

```bash
git config diff.cp1252.textconv "iconv -f WINDOWS-1252 -t UTF-8"
```

`-text` stops git from rewriting line endings in these files. `textconv` only
changes how `git diff` and `git log -p` *display* them, so accents read correctly
and the stored bytes stay exactly as E3 wrote them. (A repo that already relies on
`core.autocrlf` works too; the important part is never letting a UTF-8 editor save
the exports.)

## .gitignore

```gitignore
# runtime data and logs
*.mdb
*.ldb
# Application.Trace output
<APP>.txt
# plus whatever backup / lock files your E3 version writes next to the project
```

## The CLAUDE.md template

Keep the project's own facts in `CLAUDE.md` and leave the E3 rules to this skill,
so they are maintained in one place. A starting point:

```markdown
# <App name>

<One paragraph: what the application supervises, for whom, over which protocol.>

Use the **elipse-e3** skill for anything touching E3: script exports, screen
CSVs, units, E3 scripting rules.

## Files
| Path | What it is |
|---|---|
| `<app>.prj` / `<app>.lib` | E3 binaries, edited only in Studio |
| `docs/scripts/*.vbs` | script exports (CP1252), edited with `vbs_tool.py` |
| `docs/screens/*.CSV` | screen exports, edited with `e3csv.py` |
| `<APP>.txt` | `Application.Trace` log |

## Project facts the code doesn't make obvious
- Shared procedures live in `<Data.Scripts>`; call them with
  `Application.GetObject("<Data.Scripts>").RunProcedure(...)`.
- Screen layers: <table of bits -> views>.
- <Configuration source of truth, e.g. "the XML in tag X wins over the file">.
- <Signal conventions, address formats, ids that are templates ...>

## Conventions
- Comments: <language>, accent-free. UI strings: <language>.
- Errors: `Application.Trace "[ProcedureName] message"`.
- Changelog: <where release notes live>.
```

## Onboarding an existing E3 project

1. Ask the user to export *Documentação de Scripts* for the project and each
   library, and the screens they want to work on as CSV.
2. Run `vbs_tool.py check` on each export to get a baseline: slot audit, number of
   non-ASCII lines, and lint. Record it in `CLAUDE.md` if the count is useful as a
   tripwire.
3. Map the object model (data folders, shared script objects, XControls, screens
   and their layers) into `docs/architecture.md` as you learn it.
