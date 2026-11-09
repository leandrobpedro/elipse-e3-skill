# Designing screens E3 draws well

E3 is a SCADA runtime, not a browser. Designs that assume reflow, web fonts or
cheap resizing look fine in a mock-up and then fight the runtime. This page
covers what translates.

## Units

| Quantity | E3 unit | Conversion | Tool |
|---|---|---|---|
| Position, size | himetric (hm, 1/100 mm) | `hm = px × 2540 / 96`; 1 px ≈ 26.458 hm; 24 px = 635 hm | `e3units.py 24px` |
| Font size | point | `pt = px × 0.75`; 11 px = 8.25 pt | `e3units.py 11px` |
| Colour | BGR `Long` | `R + G×256 + B×65536`; `#1142FF` → 16728593 | `e3units.py "#1142FF"` |
| Layer | 32-bit mask | CSV stores it signed: `&h80000000` → -2147483648 | `e3units.py layer 32` |
| Round corner | ratio | `RoundAspectX = r / width`, `RoundAspectY = r / height` | — |

A few script functions take pixels instead of himetric. Check the help for the
call you use. When you spec a screen, list `x · y · w · h` in **px and hm** so
the user can type either into Studio.

## Fonts

Use only fonts that ship with Windows 10/11, because the target machines (often
plant PCs) have nothing else installed:

- **Verdana**: the default, readable at small sizes, a good brand fallback.
- **Segoe UI** and **Tahoma**: alternatives.
- Not brand web fonts (Montserrat, Urbanist, Inter ...). They aren't on the target
  machines and E3 doesn't embed them.

E3 renders Verdana about **15 % wider** than its font metrics say, and a
`DrawString` adds about **5 px** of left inset. Labels sized to the metrics were
clipped ("Ordenar por" at 76 px, "Sem qualidade" at 88 px). Allow about 20 px of
slack, or run `e3units.py label "text" --size 8.25 [--bold]`. E3 can't draw
letter-spacing, text shadows or other CSS-style effects.

## Layout and performance

- **Fixed sizes.** Resizing objects at runtime is expensive, and growing a card
  pushes nothing else out of the way. Cards and controls keep fixed dimensions.
  States change colour, text and visibility. To show a different shape, swap two
  overlapping objects rather than resizing one.
- **Fixed pools over dynamic creation.** For lists, place N instances of an
  XControl in Studio (`Item0`…`Item9`), fill and hide them from script, and page
  through the data. `AddObject` per row is slower and leaves cleanup work.
- **Native ListView for long tables.** It scrolls by itself, so the row count isn't
  limited by the screen height. Use report view (`View = 3`), `FullRowSelect`, and
  `MultiSelect` when the actions apply to several rows.
- **Grids.** Start at an invisible anchor object, advance by the control's own
  `Width`/`Height`, and wrap at `Screen.Width`.
- **Read live values once.** For a view that compares many tags, read them into a
  dictionary when the view is entered (and on an explicit refresh), rather than
  linking hundreds of objects.

## Layers as view state

`Screen.Layer` is a 32-bit mask and an object shows when its own `Layer` mask
intersects it. A clean scheme:

- `&h1`: chrome (header, tabs), always on.
- One bit per view (`&h2`, `&h4`, `&h8` ...). A view is `&h1 + bit`.
- The top bit `&h80000000` for an empty or blocked state, clear of the view bits as
  they grow.
- One `OnChangeLayer` handler dispatches on the layer and builds what the view
  needs. Force a rebuild with the round trip `Layer = &h1 : Layer = prev`.
- Layers are *defined* in Studio (*Edição de Camadas*). A new bit needs a new layer
  there before objects on it show correctly.

## Visual details that work

- Hover, rounded corners, recoloured icons, tabs and toggles: see the patterns in
  [screens-csv.md](screens-csv.md#5-patterns-that-work-well).
- Status dots and LEDs: a small `DrawTank` or `DrawCircle` whose
  `ForegroundColor` links to a state expression: green for on, white for off, grey
  for "no reading". Hide it when the row has no signal.
- Tool tips: the `Tip` property on groups and objects. Use it to explain disabled
  or read-only states.
- Give read-only and empty states their own visible band or chip, so a Viewer
  without write access doesn't look broken.
