# elipse-e3-skill

A Claude Code skill for **Elipse E3** and **Elipse Power** projects. It holds the
rules that were learned the hard way on real applications. E3 binaries can't be
edited as text, so Claude works on the *Documentação de Scripts* exports and the
screen CSV exports. The skill teaches Claude how to change those files without
corrupting them, how E3 scripts must be structured, how scopes and link expressions
behave, and how to design screens that E3 draws well.

The repository is a Claude Code **plugin marketplace** with one plugin,
`elipse-e3`, that contains one skill, also named `elipse-e3`.

## What's inside

```
.claude-plugin/marketplace.json        marketplace manifest
plugins/elipse-e3/
  .claude-plugin/plugin.json           plugin manifest (version lives here)
  skills/elipse-e3/
    SKILL.md                           core rules; loaded when the skill triggers
    references/
      scripting.md                     slots, scopes, RunProcedure, links, timing, XControls
      screens-csv.md                   CSV format, import behaviour, editing recipes, UI patterns
      ui-design.md                     units, fonts, fixed layouts, layers
      project-setup.md                 repo layout, .gitattributes, CLAUDE.md template
    scripts/
      vbs_tool.py                      list/show/put/remove/check procedures in .vbs exports (CP1252-safe)
      e3csv.py                         info/show/set/clone/delete/check screen CSV exports
      e3units.py                       px / himetric / pt / colour / layer / label-width conversions
```

The scripts need only Python 3 (standard library), and work on Windows with Git
Bash or PowerShell.

## Install (colleagues)

In Claude Code:

```
/plugin marketplace add <git URL of this repo>
/plugin install elipse-e3@elipse-e3-skill
```

Or from a terminal: `claude plugin marketplace add <url>` and then
`claude plugin install elipse-e3@elipse-e3-skill`.

Get updates with `claude plugin marketplace update elipse-e3-skill` followed by
`claude plugin update elipse-e3@elipse-e3-skill`.

The skill triggers by itself whenever a conversation is about E3 or Elipse Power.
You can also ask for it by name ("use the elipse-e3 skill").

## Develop

Load your working copy directly, without installing:

```
claude --plugin-dir <path-to-your-clone>/plugins/elipse-e3
```

Before sharing a change:

1. `claude plugin validate .` (marketplace) and `claude plugin validate plugins/elipse-e3`.
2. Raise `version` in `plugins/elipse-e3/.claude-plugin/plugin.json` **and** in
   `.claude-plugin/marketplace.json`. Installed copies update only when the version
   changes.
3. Add a line to `CHANGELOG.md`, commit and push.

## Contributing a lesson

When a project teaches you something new about E3:

- Put it in the reference file where it belongs. Only put it in `SKILL.md` if it
  is a rule people break all the time.
- Say why it matters, and mark it **confirmed** (seen to fail and seen fixed) or
  **inferred**.
- Keep project-specific facts (tag names, XML schemas, devices) in that project's
  `CLAUDE.md`, not here.
- If a step keeps being done by hand, make it a script in `scripts/`.

Test cases can be added later under `plugins/elipse-e3/skills/elipse-e3/evals/`;
`claude plugin eval` runs them.
