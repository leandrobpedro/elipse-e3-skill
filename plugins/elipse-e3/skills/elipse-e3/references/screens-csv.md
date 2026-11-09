# Screen and XControl CSV exports

Studio exports a screen or an XControl to CSV and imports it back. That is the
only way to add or restyle graphic objects without drawing them in Studio. Use
`scripts/e3csv.py` for every read and write: it keeps the format byte-exact, and
it refuses to write a file that fails its checks.

## Contents

1. Format
2. Rows: objects, children, links, sub-rows
3. How the import behaves
4. Editing recipes
5. Patterns that work well

---

## 1. Format (confirmed)

- `;` separator, **decimal comma** (`1693,333333`), **CRLF**, **Windows-1252**.
- Strings are in double quotes, with `""` for a quote and **backslashes doubled**
  (`"assets\\icons\\lock.wmf"`). Inside strings `\r\n` is written as the two
  escape sequences, as in multi-line SQL. Numbers, booleans (`True`/`False`) and
  enums are unquoted. An empty field means "not applicable to this class".
- Header: `ObjectType;Name;` then **every property of every class present in the
  file**, in case-insensitive alphabetical order (`Effect3D_X` before
  `Effect3DColorBase`). Screen and XControl exports therefore have different column
  sets, and two screens rarely match. **Map by column name, never by position.**
- Geometry (`X`, `Y`, `Width`, `Height`) is in himetric. Children of a group have
  **absolute** coordinates, not coordinates relative to the group.
- `Layer` is a signed decimal `Long` mask: `-1` is all layers, `&h80000000` is
  `-2147483648`. The screen's own row holds its current layer.
- Colours are decimal BGR `Long`s; negative values are system colours.
- `PathName` is the full path (`Screens.Main.grpX.lbl` on a screen, `Card.grpX.lbl`
  in an XControl). `PathContainer` and `PathVolume` are the same on every row of a
  file. Rows cloned from another file must be rebased on the destination's
  values (`clone --from` does this).

Shell tools on Windows (Git Bash `sed -i`, `grep`) drop or mangle the CRs. If you
must look with them, compare through `tr -d '\r'` on both sides. Never write with
them.

## 2. Rows

- The first data row is the screen or XControl itself (`Screen` / `XControl`, empty
  `Name`).
- Every graphic object has a row whose `Name` is its path inside the
  screen: `grpChip`, `grpChip.lblName`.
- **A parent row comes before its children, and a subtree is contiguous.**
  Rows run front to back.
- Links are rows named `<object>.Links.<Property>`:
  - `AgSimple` is a simple link: `Property`, `Source` (the expression),
    `BiDirectional`, `Reverse`.
  - `AnimationBind` is a digital link: `Source`, `OffValue`, `OnValue`, and
    `BlinkOn/Off` with their values.
  - `TableBind` / `MultiSourceBind` and their row objects follow the same
    naming.
  - A link on the screen itself is named `Links.<Property>`.
- Some sub-objects have **no name**, and their rows belong to the named row above:
  `IDrawLinePoint` under `line.Points`, `IField` under `browser.Fields`.
- XControl instances placed on a screen appear with their class as `ObjectType`
  and their public properties as columns.
- Internal tags on a screen are rows too (`InternalTag`, with `Value`,
  `Retentive`).
- The screen's **layer definitions** (the *Edição de Camadas* table) are **not** in
  the CSV. A new layer must be created in Studio.

## 3. How the import behaves

Confirmed:

- Objects are **matched by name and updated in place**.
- The import **never changes an object's class**. A row that reuses a name with a
  different `ObjectType` (`DrawPicture` → `DrawGroup`) only updates the old
  object's properties, and every child row then fails with "não pode ter um
  objeto-filho". **To change a class, the user deletes the object in Studio first.**
  Its scripts are deleted with it; paste them back from the `.vbs`.
- Objects **missing from the CSV are not deleted**. Removing rows deletes nothing,
  so tell the user what to delete in Studio.
- Keep the names that script slots use (`btnSave` → `btnSave_Click`), so the
  handlers stay attached.

Not yet confirmed:

- Adding columns for a class the file didn't contain yet (e.g. `RoundAspectX/Y`
  when the first `DrawTank` arrives) was done in alphabetical position. Whether the
  import accepts every such column hasn't been verified. When it matters, ask the
  user to drop one object of that class in Studio and re-export, which brings the
  real columns.

## 4. Editing recipes

```bash
python e3csv.py info  Main.CSV --no-links              # what's there, in px
python e3csv.py show  Main.CSV 'btnSave*'               # all props of a subtree
python e3csv.py clone Main.CSV btnSave btnOpen --dx 120 \
       --set lblButton:Value=Abrir --set icon:Filename='assets\icons\folder-open.wmf'
python e3csv.py set   Main.CSV 'grpBand*' 'Layer=&h80000000' Visible=True
python e3csv.py clone Card.CSV grpBadge grpBadge --from Main.CSV   # screen -> XControl
python e3csv.py delete Main.CSV grpOld                  # then delete it in Studio too
python e3csv.py check Main.CSV
```

- **Build new objects by cloning the user's own rows.** A cloned row carries every
  default Studio wrote (shadow, 3D, fill settings), which a row written from scratch
  would lack.
- Values: `24px` → himetric, `#RRGGBB` → colour `Long`, `&h...` → signed layer.
  Quoting follows the column. `raw:` writes a token exactly as given.
- When restyling an XControl, keep its internal offset. Its objects may not start
  at (0, 0); one row sat at (8, 24) px inside its control.
- After editing, tell the user:
  1. which CSV to import,
  2. what to delete in Studio first (class changes, removed objects),
  3. which layers to create,
  4. which script slots to paste for new objects.

## 5. Patterns that work well

Chosen by a user after reviewing alternatives. Prefer them.

- **Hover on a filled shape:** an `AnimationBind` on `ForegroundColor` with source
  `Parent.MouseOverChild` and Off/On colours, plus an `AgSimple` on `BorderColor`
  with source `"ForegroundColor"` (the border follows the fill). This beats two
  stacked shapes.
- **Rounded corners:** use a `DrawTank`. `RoundAspectX = radius / width`,
  `RoundAspectY = radius / height` (6 px radius on 40 px height → 0.15).
- **Icons:** WMF files in `DrawPicture`. Recolour with
  `EnableOverrideLineColor = True` + `OverrideLineColor`, and bind that colour for
  hover. `Angle` does **not** rotate a WMF (confirmed), so ship a separately drawn
  file per direction. Lucide icons converted to WMF work well; name them
  `<lucide-name>.wmf`.
- **Tabs:** each tab is a group whose `DocString` holds its layer bit (`&h4`). One
  click handler reads it and changes the layer. The selection bar's `Visible` links
  to `Screen.Layer And CLng(Parent.DocString)`.
- **Toggle / selected state:** keep `"1"`/`"0"` in a group's `DocString` and drive
  colours from `Parent.DocString = "1"`, combined with hover:
  `Parent.MouseOverChild Or Parent.DocString = "1"`.
- **Empty state:** a group on its own layer (e.g. `&h80000000`, the top bit, clear of
  the view bits) that holds only static objects.
