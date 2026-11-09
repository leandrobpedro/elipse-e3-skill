# E3 scripting — rules and idioms

How VBScript behaves inside Elipse E3 / Elipse Power, as learned on real projects.
Each rule says why it exists. **Confirmed** means it was seen to fail and the fix
was seen to work. **Inferred** means it fits what was observed but wasn't proven.

## Contents

1. The export format
2. Slot structure
3. Scopes and how to cross them
4. Shared procedure libraries
5. Passing values across `RunProcedure`
6. Names that collide with E3
7. Link expressions
8. Server, Viewer and timing
9. Creating, finding and deleting objects
10. Screens: opening, arguments, closing
11. XControls
12. Read-only Viewers, licences and versions
13. Logging and error handling

---

## 1. The export format

*Documentação de Scripts* writes one text file per project or library:

```
-----------------------
Documentação de Scripts
-----------------------
APPNAME (<path to>\app.prj)
<date>
-----------------------

<Folder.Object:Object_Event()>
Sub Object_Event()
    ...
End Sub

<Folder.Screen.Control:Control_Click()>
Sub Control_Click()
...
```

- A marker `<ObjectPath:Handler(args)>` starts a slot, which runs until the next
  marker. The slot is the unit the user pastes into Studio: the script editor of
  that object's event.
- Markers are sorted by object path. `vbs_tool.py put --new-slot` keeps that order.
- The file is Windows-1252 with CRLF. Comments in Portuguese often have accents.
  Write *new* comments accent-free so they survive any editor. UI strings
  (`MsgBox`, labels) keep their accents; the tool encodes them correctly.

## 2. Slot structure (confirmed)

Studio accepts a slot only if its **first line starts with `Sub`** and its **last
line is `End Sub`**.

```vbscript
Sub SignalPicker_OnShow()        ' first line: the handler itself
    ...
End Sub
'---'
Dim g_filterType                 ' module-level declarations go *after* the handler
Dim g_xmlDoc
'---'
Private Function ConfigColumns()
    ...
End Function
Sub Foo()                        ' padding: a slot can't end on End Function
End Sub
```

- Module-level `Dim`s in a slot are shared by every procedure in that slot (and in
  sibling slots of the same object, see §3). They keep their value for as long as
  the object stays loaded.
- A "procedure library" slot is just a handler that does nothing
  (`Sub Scripts_Functions()` / `End Sub`) followed by the real procedures.
- `vbs_tool.py check` audits every slot.

## 3. Scopes and how to cross them (confirmed)

**Every object has its own script scope.** A screen is one scope, and each control
on it is another. Each XControl instance, each data folder and each XObject has its
own as well. Slots on the **same** object share one scope: `MainScreen_OnPreShow`
can call a procedure defined in the `MainScreen_OnChangeLayer` slot. But
`cboFilter_Change` lives on the ComboBox and can't see either of them.

Reaching a screen procedure from a control:

```vbscript
' 1. RunProcedure: the target must NOT be Private. If it is, the call fails at
'    runtime and nothing is logged.
Screen.RunProcedure "UpdatePreview"
result = Screen.RunProcedure("BuildLabel", someString)

' 2. An internal tag on the screen as a trigger. Costs one object, but works
'    from anywhere, including inside XControls on that screen.
Screen.Item("UpdatePreview").WriteEx True
```

For option 2, the work happens in the internal tag's `OnValueChanged`. **Inside an
internal tag's events `Screen` is not defined**; the screen is `Parent`
(`Parent.Layer`, `Parent.Item("lvwRules")`). Graphic children and groups do see
`Screen`.

Inside an XControl, its own children are reached with `Item("child")`, and the
XControl itself by its class name (`MyCard.Source`) or `Me` depending on the slot.

## 4. Shared procedure libraries

Put project-wide helpers on one data object, e.g. `Data.Scripts`, in empty-handler
slots (`Scripts_Functions`, `Scripts_XmlHandler`, ...). All slots of that object
share one scope, so those procedures call each other directly. Everyone else goes
through the object:

```vbscript
Dim scripts
Set scripts = Application.GetObject("Data.Scripts")
Set xmlDoc = scripts.RunProcedure("GetXmlDoc")
scripts.RunProcedure "CommitXml", xmlDoc.xml
```

- `RunProcedure` exists from **E3 5.6** onward. An older server can't run any of
  this, so check the version first if the app may meet one (see §12).
- Server-side procedures run on the server. `MsgBox` there doesn't appear in the
  Viewer. Put dialogs in screen procedures.
- A user event on the library object (linked to a tag) is a good "on change" hook,
  e.g. reload configuration when a path tag changes.

## 5. Passing values across `RunProcedure` (confirmed)

Pass **strings and numbers**, not objects you created on the calling side.

```vbscript
' fails at the RunProcedure line: groupNode belongs to a DOM this screen created
expression = scripts.RunProcedure("BuildExpression", groupNode)

' works: the callee re-parses the string
expression = scripts.RunProcedure("BuildExpressionFromXml", groupNode.xml)
```

A node of a document that the *callee's* scope created does travel back and forth.
To be safe, serialise anyway. For E3 objects, prefer letting the callee do its own
`Application.GetObject(path)` and pass the path.

## 6. Names that collide with E3 (confirmed)

- **`item`**: on screens and XControls, `Item("name")` is the child accessor. A
  local `Dim item` hides it, and `Item("lvwRules")` silently becomes an index
  into your variable. Use `itm`.
- Avoid other names of members that the hosting object already has (`Name`,
  `Value`, `Parent`, `Layer`, `Visible` ...) as locals for the same reason.

## 7. Link expressions (confirmed)

Links (*AgSimple*, *AnimationBind* ...) hold expressions that E3 evaluates on its
own, outside VBScript.

- **`Or` / `And` evaluate both sides.** If one operand reads `.Value` of a tag
  that has no value, the *whole* link breaks. That happens with a driver that is
  deactivated (for instance with no licence only one driver runs) or a tag never
  read. Writing `tag.Quality < 192 Or tag.Value = 0` does not protect it.
- **`IIf` evaluates only the branch it takes.** Nest it to guard `.Value`:

  ```
  ' 0 = online, 1 = communication failure, 2 = driver offline
  ' WorkOnline = the driver's online tag; SomeTag = any tag it reads
  IIf(WorkOnline.Quality < 192, 2,
      IIf(WorkOnline.Value <> 1, 2,
          IIf(SomeTag.Quality < 192, 1, 0)))
  ```
- A link can combine screen state, e.g. selection of a tab whose layer bit sits in
  its group's `DocString`: `Screen.Layer And CLng(Parent.DocString)`.
- Create or remove links from script with
  `obj.Links.CreateLink "Property", "expression", 0` and
  `obj.Links.RemoveLink "Property"`.
- Hover: `Parent.MouseOverChild` (true while the mouse is over any child of the
  group) as the source of an *AnimationBind* with OffValue/OnValue.

## 8. Server, Viewer and timing (confirmed)

Viewer scripts (screens, controls) and server scripts (data objects, XObjects,
their events) run in different processes.

- Writing a server tag from a click handler fires the server-side event **after
  the handler has returned**. If the handler then redraws the screen, it races the
  server: in one application, cards were rebuilt while the server was still deleting the
  old objects behind them.
- The pattern that works: the server writes one "done" tag as its **last** step. The
  screen has an internal tag linked to that tag's `.Timestamp`, and redraws in its
  `OnValueChanged`.
- A tag linked to an expression (`Dirty = Content <> SavedContent`) needs no script
  to stay correct. Prefer links to scripts that "remember to set" a flag.

## 9. Creating, finding and deleting objects

```vbscript
' find-or-create
On Error Resume Next
Set o = parentObj.GetChildObject(name)
On Error Goto 0
If Not IsObject(o) Then Set o = parentObj.AddObject(className, True, name)

' delete: collect first, then delete (confirmed: deleting inside For Each
' skips the next element, which left a stale object running)
Dim names(), n : n = -1
For Each obj In parentObj
    If TypeName(obj) = "MyClass" Then n = n + 1 : ReDim Preserve names(n) : names(n) = obj.Name
Next
For i = 0 To n : parentObj.DeleteObject names(i) : Next
```

- Mark objects created at runtime (e.g. `DocString = "Dynamic"`) so the next
  rebuild can find and delete exactly those.
- A layout anchor object (an invisible rectangle where a grid starts) must be set
  invisible at runtime, or it shows in the Viewer.
- *Inferred:* `Screen.AddObject` seems to put each new object **behind** the ones
  already there. Create overlay texts before the shape they sit on.
- Dynamic assignment to a property whose name is in a string:
  `Execute "obj." & propName & " = value"`.
- `TypeName(obj)` returns the XControl/XObject class name. Use it to tell your
  classes apart.

## 10. Screens: opening, arguments, closing

```vbscript
' modal dialog with an argument; returns what the dialog passes to Close
answer = Application.DoModal("Screens.Picker", , , , , , Array(id, filterType), flags)
If answer <> vbOK Then Exit Sub

' inside the dialog
Sub Picker_OnPreShow(Arg)               ' Arg is the DoModal/OpenScreen argument
    If IsObject(Arg) Then Set Item("Arg").Value = Arg Else Item("Arg").Value = Arg
End Sub                                 ' keep it in an internal tag for later handlers
...
Screen.Close(vbOK)                      ' or vbCancel

' frames
Set frame = Application.GetFrame("")          ' the main frame
Set frame = Application.GetFrame(name, True)  ' create a named frame (one window per name)
```

- Window flags are a bitmask, documented in the E3 help. `256` made a window
  *always on top*. Users found that annoying for normal windows, so leave it off
  unless it is a true modal.
- A modal can't return objects reliably. Have it write a string (a path, an id) to
  a known tag and read that after `DoModal` returns.
- `Layer` is a bitmask of the 32 layers. Force a rebuild without changing view with
  a round trip: `prev = Screen.Layer : Screen.Layer = &h1 : Screen.Layer = prev`.
- `Application.ShowFilePicker(isOpen, path, ext, flags, filter)` returns True when
  the user confirmed, with the path in the second argument.

## 11. XControls

- **Pick property types that hold their default.** A `Byte` property can't hold
  `-1`, so an "unset" id of -1 failed until the type became Integer (confirmed).
- **What was drawn in Studio is what shows when the script fails.** If the
  constructor dies (missing source object, bad path), the control keeps its design
  state. Draw that state as neutral or "not found", never as "Online" or "OK", and
  have the constructor set an explicit error text when its source is missing.
- XControl handlers are named `<Class>_Constructor`, `<Class>_On<Prop>Changed`,
  and so on. Their scope is the XControl. Project procedures go through
  `Application.GetObject(...).RunProcedure`.
- ActiveX controls (MSCOMCTL TreeView, ListView ...) must be **registered on every
  machine** (`regsvr32`, elevated). Otherwise the screens that use them fail.

## 12. Read-only Viewers, licences and versions

- `Application.IsReadOnly` is True for a Viewer Only licence or a user without
  write permission. Guard every handler that writes: `If Application.IsReadOnly
  Then Exit Sub`, and hide or disable write actions.
- Elipse documents that a read-only Viewer can't call methods of server objects,
  which would include `RunProcedure` (*not yet verified*). If you rely on it, probe
  once and trace the outcome.
- To gate on the server's version, have a server script store
  `ProductVersionMajor.Minor.Build` in a tag at startup. Reading a tag works in any
  Viewer mode.
- Without a licence (demo), only one driver runs, so expect deactivated drivers in
  link expressions (see §7).

## 13. Logging and error handling

- `Application.Trace "[ProcedureName] message"` writes to the application's trace
  file (typically `<APP>.txt` next to the project). Keep the bracketed
  procedure name so the log can be searched.
- `On Error Resume Next` hides everything. Scope it to the one call that may fail,
  check `Err.Number`, trace `Err.Description`, then `On Error Goto 0`.
- Script-generated messages (`MsgBox`, traces) can be English or the UI language.
  Follow the project's convention and be consistent.
