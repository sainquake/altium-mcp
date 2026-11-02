# Altium MCP Server

Control and query Altium Designer through an MCP client that supports local stdio servers.
This Model Context Protocol (MCP) server exposes tools for inspecting and editing PCB designs, schematics, and libraries through Python and Altium's scripting interface. It runs on Windows and is independent of the agent or model provider.

## Example commands
- Run all output jobs
- Create a symbol for the part in the attached datasheet and use the currently open symbol as a reference example.
- Create a schematic symbol from the attached MPM3650 switching regulator datasheet and make sure to strictly follow the symbol placement rules. (Note: Need to open a schematic library. Uses `server\symbol_placement_rules.txt` in the server's installation directory as pin placement rules. Please modify for your own preferences; an update can replace the file, so keep a copy.)
- Create an op-amp symbol with a triangle body like the other op-amps in my library (symbols support line/polygon/arc/ellipse/label body graphics, not just rectangles)
- Find me the LM358 symbol in my opamp library and open it
- Create a multi-part symbol for a quad op-amp from the attached LM324 datasheet (creates parts A, B, C, D with shared V+/V- power pins)
- Create a PCB footprint for the SMD part in the attached datasheet and add it to my open PcbLib
- Duplicate my selected layout. (Will prompt user to now select destination components. Supports Component, Track, Arc, Via, Polygon, & Region)
- Show all my inner layers. Show the top and bottom layer. Turn off solder paste.
- Get me all parts on my design made by Molex
- Give me the description and part number of U4
- Place the selected parts on my pcb with best practices for a switching regulator, then verify clearances and show me a screenshot of the result
- Give me a list of all IC designators in my design
- Get me all length matching rules
- Check my project is ready for fabrication: unsaved documents, ERC errors, and which layers my Gerber output job plots
- Draw a schematic of an LED with a current-limiting resistor on a new sheet, using symbols from my library
- Edit an existing schematic sheet: add, update or delete components, wires, labels and ports without saving it

## Installing the MCP Server

1. Install Python 3.10+ on Windows and make sure it is available to your MCP client.
2. Clone or download this repository to a local directory.
3. Configure your MCP client to launch `start_server.py` with Python using the stdio transport. Use an absolute path to the script. If Python is not on the client's PATH, use the full path to `python.exe` as the command.

For clients that use an `mcpServers` configuration, a typical entry looks like this. Other clients may use a different configuration format; the launch command and arguments are the same.

```json
{
  "mcpServers": {
    "altium-mcp": {
      "command": "python",
      "args": ["C:/path/to/altium-mcp/start_server.py"]
    }
  }
}
```

Replace the example path with your repository location, then enable or reload the server in your client. Call `get_server_status` to check that the server is connected and Altium was found.

The launcher creates a virtual environment and installs dependencies on first use, which requires network access. To prepare it before connecting the client, run this from the repository directory:

```powershell
python start_server.py --build
```

Use the same Python interpreter and `ALTIUM_MCP_HOME` setting as the client. If a first launch exceeds the client's startup timeout, the detached build continues in the background; reconnect after it finishes. Build progress is recorded in `%USERPROFILE%\.altium-mcp\build.log` (or the directory set by `ALTIUM_MCP_HOME`).

Clients that support `.dxt` desktop extensions can alternatively install `altium-mcp.dxt` from [releases](https://github.com/coffeenmusic/altium-mcp/releases) using their extension installer.

## Launcher and Dependency Environment

`start_server.py` creates a virtual environment and pip-installs dependencies on the user's machine at first launch. This avoids bundling pre-compiled packages in `server/lib/`, which can fail when the user's Python version differs from the version used to build the bundled `.pyd` files.

**How it works:**

1. `start_server.py` (at the repo root) looks for a ready virtual environment in `%USERPROFILE%\.altium-mcp\venvs\<key>`, where `<key>` is a hash of the pinned requirements and the Python version
2. If it isn't ready, it starts a **detached** builder process (`start_server.py --build`) that creates the venv and pip-installs the dependencies, then waits for it. It installs the hash-locked `requirements.txt` when present, and falls back to the short `REQUIREMENTS` list in `start_server.py` when the file is missing or the locked dependencies cannot be installed for the interpreter. Separating the build from the launcher lets it continue if a client stops or restarts the server during setup.
3. A lock file (holding the builder's PID) makes sure only one build runs at a time; other launchers wait for it. A lock whose owner has exited is taken over immediately.
4. It then launches `server/main.py` using the venv's Python
5. Subsequent launches reuse the environment while the requirements and Python version remain unchanged

The venv, `config.json` and `build.log` live in `%USERPROFILE%\.altium-mcp`, outside the installation directory, so dependency environments and a hand-picked Altium path survive updates. Keeping them outside AppData also avoids filesystem redirection by packaged Windows clients. Set the `ALTIUM_MCP_HOME` environment variable to use a different folder. A `config.json` left beside `server/main.py` by an older version is migrated automatically on first start.

## Optional DXT Packaging (For Developers)

The repository includes a `manifest.json` for clients that support `.dxt` desktop extensions. Packaging is optional; clients can launch the server directly as described above.

**Build steps:**

1. Make sure `start_server.py` exists at the repo root
2. Make sure `server/main.py` does NOT have the old `site.addsitedir` hack at the top
3. Keep `manifest.json` configured with `entry_point` set to `start_server.py`, no bundled-library `PYTHONPATH`, and `manifest_version: "0.3"`
4. Package the DXT by zipping the files and renaming the archive:
```powershell
Compress-Archive -Path manifest.json, start_server.py, pyproject.toml, requirements.txt, server -DestinationPath altium-mcp.zip
Rename-Item altium-mcp.zip altium-mcp.dxt
```

**Do NOT include `server/lib/` or `server/.venv/` in the .dxt.** The whole point is that these are created on the user's machine.

**`start_server.py`:** use the file at the repo root as is. It is no longer reproduced here, so the two cannot drift apart.

**`manifest.json` server section:**
```json
"server": {
    "type": "python",
    "entry_point": "start_server.py",
    "mcp_config": {
      "command": "python",
      "args": ["${__dirname}/start_server.py"]
    }
  }
```

### Pitfalls

These are hard-won lessons from debugging DXT builds. Violating any of these will produce errors that are difficult to diagnose.

1. **Do NOT use `os.execv()` in `start_server.py`.** Installation paths can contain spaces. On Windows, `os.execv` splits the path at the space and fails. Use `sys.exit(subprocess.call([...]))` instead.

2. **Pin `mcp` to `==1.5.0`.** Using `>=1.5.0` pulls in the latest version, which has breaking API changes (`FastMCP.__init__()` dropped the `description` kwarg). The server code was written against 1.5.0.

3. **Keep the manifest aligned with the Python launcher.** The included manifest uses `"type": "python"` with `manifest_version: "0.3"`. Check the target client's supported manifest format before changing these fields.

4. **After removing the `site.addsitedir` hack from `main.py`, fix the `pathlib.Path` reference.** The hack included `import pathlib` at the top of the file. The logging setup later uses `pathlib.Path(...)` which will throw `NameError` once that import is gone. Change it to `Path(...)` — the `from pathlib import Path` import already exists in the file, just make sure it comes before the logging setup.

5. **Do NOT bundle `server/lib/` in the DXT.** That was the old approach and defeats the purpose of the venv bootstrap.

## Configuration

On first startup, the server will automatically try to locate your Altium Designer installation. It will search for all directories that start with `C:\Program Files\Altium\AD*` and use the one with the largest revision number. If it cannot find any, you will be prompted to select the Altium executable (X2.EXE) manually when you first run the server. Altium's DelphiScript scripting is used to create an API between the MCP server and Altium.

## Available Tools

The server provides several tools to interact with Altium Designer:

### Output Jobs
- `get_output_job_containers`: Reads all available output containers from the `.OutJob` at `outjob_path` (a full path, optional) or, without one, from the first OutJob open in a project
- `run_output_jobs`: Pass a list of output job container names to run any number of them, from the `.OutJob` at `outjob_path` or the first open one. The OutJob's project must be open in Altium. PDF containers report `output_verified` once the PDF is written. If the PDF already exists and the container prompts before overwriting, Altium asks in a dialog and the run waits for the answer.
- `get_outjob_settings`: Read any `.OutJob` file from disk (no Altium needed, the OutJob does not have to be open) and return its containers (output paths, file name expression, add-to-project) and outputs (connected containers, variant, document) with decoded settings: Gerber units/format/origin and the plotted and "add to all plots" layers decoded from Altium layer IDs, NC Drill, IPC-D-356 test points, pick and place and print layers. Use it to audit fabrication settings before generating. Reads the saved file, so unsaved changes in Altium are not visible.

### Project & Validation
- `get_project_info`: Focused project's parameters, documents with their state (`closed` / `open` / `modified` = unsaved changes in memory), schematic sheet count and variants with their variations (e.g. Not Fitted parts). Read-only; use it to confirm nothing is unsaved before generating outputs.
- `get_project_components`: Every component of the compiled project with its schematic Comment, footprint, library reference and sheet (optionally all parameters). Use it for BOM work: the instance Comment is where generic passives keep their value, which PCB-side tools and ActiveBOM may not show.
- `get_erc_violations`: Compile the focused project in memory (nothing is saved) and list compiler/ERC violations with their level (fatal / error / warning). Violations are read from the project object - the per-document `DM_ViolationCount` does not exist in recent Altium versions.
- `get_board_summary`: Fabrication-oriented summary of the focused PCB in mm: board outline (bounding box, size, vertices) and origin, dimension objects, vias by hole size, components per side, primitive counts per layer (free vs. inside components, e.g. to see which mechanical layers hold the assembly outlines) and the free texts on both overlays.
- `get_component_primitives`: Every primitive of the given components with its layer (pads with size and solder/paste mask expansion, arcs, tracks, texts). Catches footprints that were flipped to the bottom side but kept part of their copper or mask opening on the top (e.g. fiducials).

### Component Information
- `get_all_designators`: Get a list of all component designators in the current board
- `get_all_component_property_names`: Get a list of all available component property names
- `get_component_property_values`: Get the values of a specific property for all components
- `get_component_data`: Get detailed data for specific components by designator
- `get_component_pins`: Get pin information for specified components

### Schematic/Symbol
- `get_schematic_data`: Get schematic data for specified components
- `create_schematic_symbol` ([YouTube](https://youtu.be/MMP7ZfmbCMI)): Passes pin list with pin type & coordinates to Altium script. Supports multi-part symbols (e.g. quad op-amps) via a `part_count` parameter and an `owner_part_id` field on each pin (use 0 for shared power/GND pins), active-low pin name overbars by placing a backslash after each overbarred character (e.g. `R\E\S\E\T\` renders as `RESET` with overbar), per-pin length and name/designator visibility, and an optional `graphics` list (lines, polylines, polygons, rectangles, arcs, ellipses, labels) for non-rectangular bodies like op-amp triangles and diode glyphs. When creating a symbol, the agent is instructed to first look up a similar symbol in an available library as a style reference (skipped gracefully if no library is available).
- `get_symbol_primitives`: Inventory a .SchLib (every symbol with per-type primitive counts) or dump one symbol's complete geometry (all graphics + pin details, in mils; `symbol_name="*"` dumps every symbol). Used to gap-analyze a library, to give the agent a reference example when drawing a new symbol, and to verify recreations. The symbol creator round-trips a complete production library set exactly - 514/514 symbols across IC, connector, misc, and passives libraries (dump -> recreate -> dump -> diff, zero differences). Footprint/model links (implementations) are metadata outside the graphics round-trip.
- `create_symbols_batch`: Create many symbols in one script run from a plain-text spec file (bulk imports/migrations) - far faster and more robust than one create call per symbol.
- `build_schematic`: Build a wired schematic on a new sheet from a circuit description: parts from a `.SchLib` (full path; `.IntLib` is not supported), wires, junctions, net labels, power ports and notes, in mils. Returns every placed pin's true connection point, so a second call can route wires from measured coordinates, and lists any part it could not place. The new sheet is kept out of your project.
- `edit_schematic(sheet_path, operations)`: Add, update and delete components, wires, net labels, ports, power ports, junctions and text on one exact existing `.SchDoc`. Never saves. Use `operations=[]` to read object UIDs and measured component pin connection points, then target edits by UID (or component designator). Components can be cloned from the sheet or placed from a `.SchLib`. Checks every target/source before applying the batch and reports partial API failures. See [operation schema, examples and verification](dev/EDIT_SCHEMATIC.md).
- `get_symbol_placement_rules`: Create symbol's helper tool that reads `server\symbol_placement_rules.txt` in the server's installation directory to get pin placement rules for symbol creation.
- `get_library_symbol_reference`: Create symbol's helper tool to use an open library symbol as an example to create the symbol
- `search_library_symbol`: Search for a symbol by name in a schematic library (.SchLib) and navigate to it. Supports partial name matching. Will open the library file in Altium if a path is provided, or show a file picker if not.

![Symbol Creator](assets/symbol_creator.gif)

### Layout Operations
- `get_all_nets`: Returns a list of unique nets from the pcb
- `create_net_class` ([YouTube](https://youtu.be/89booqRbnzQ)): Create a net class from a list of nets
- `get_pcb_layers`: Get detailed layer information including electrical, mechanical, layer pairs, etc.
- `get_pcb_layer_stackup`: Gets stackup info like dielectric, layer thickness, etc.
- `set_pcb_layer_visibility` ([YouTube](https://youtu.be/XaWs5A6-h30)): Turn on or off any group of layers. For example turn on inner layers. Turn off silk.
- `get_pcb_rules`: Gets the rule descriptions for all pcb rules in layout.
- `get_selected_components_coordinates`: Get position, rotation, layer, and footprint information for currently selected components
- `move_components`: Move specified components by X and Y offsets
- `set_component_position`: Set one component's absolute position and rotation
- `place_components`: Batch absolute placement - place any number of components (x, y, rotation, top/bottom layer) in a single transaction / one undo step. The workhorse for AI-driven placement.
- `check_placement`: Verify a placement - finds overlaps and clearance violations against every other component on the board using true primitive-to-primitive distances (designator text excluded). Run after placing; a screenshot is not verification.
- `check_orientation`: Advisory check for 2-pad passives whose rotation could be improved (e.g. a decoupling cap with its GND pad facing away from the IC). Geometry only - review suggestions with judgement; parts like pull-ups don't care.
- `get_net_connections`: For the nets touching a set of components, list every pad on each net board-wide with per-net airline (MST) lengths - the data behind connectivity-driven placement (shorten critical nets, see off-cluster loads and filter banks).
- `layout_duplicator` ([YouTube](https://youtu.be/HD-A_8iVV70)): Starts layout duplication assuming you have already selected the source components on the PCB.
- `layout_duplicator_apply`: Action #2 of `layout_duplicator`. Agent will use part info automatically to predict the match between source and destination components, then will send those matches to the place script.

The cool thing about layout duplication this way as opposed to with Altium's built in layout replication, is that the exact components don't have to match because the LLM can look through the descriptions and understand which components match and which don't have a match. That's something that can't really be hard coded.
![Placement Duplicator](assets/placement_duplicator.gif)

### PCB Footprint Library
- `create_pcb_footprint`: Create a new PCB footprint in the currently active .PcbLib document. Supports SMD pads (Rect, Round, Oval shapes) defined in mm relative to the component origin. Auto-generates a courtyard on Mech 15 and silkscreen with a pin 1 indicator (gap in the top-left corner), or accepts explicit courtyard dimensions. Contributed by [coffeedust](https://github.com/coffeedust) ([PR #7](https://github.com/coffeenmusic/altium-mcp/pull/7)).
- `get_footprint_primitives`: Inventory a .PcbLib (per-footprint primitive counts) or dump complete footprint geometry - pads with full stack/hole detail, tracks, arcs, fills, texts, regions - in mils. The reference source when recreating or verifying footprints. 3D bodies are excluded as models.
- `create_footprints_batch`: Create many footprints in one script run from a plain-text spec file: SMD + through-hole pads (holes, slots, plating, rotation, full pad stack), tracks, arcs, fills, texts, and regions on any layer. Round-trip verified against complete production SMD and through-hole libraries.

### Both
- `get_screenshot`: Take a screenshot of the Altium PCB window or Schematic Window that is the current view, returned as a proper image the agent can see. For PCB views, an optional `zoom_to` list of designators makes Altium zoom to those components before capture so they fill the frame. It should auto focus either document type if it is open but a different document type is focused.

### Scripting / Development
- `run_altium_script`: Run a DelphiScript snippet in an **isolated sandbox** and get back a step-by-step log, the script's result, and - when a script fails - Altium's own error message with the line in your script. Each run is written to a fresh copy of `SandboxScript/Sandbox.pas` with a unique file name and started with `ScriptingSystem:RunScriptFile`, so a script that failed earlier can never be re-run from Altium's script editor. Errors inside the script (undeclared identifiers, calls on nil, bad conversions) are caught and reported without blocking Altium; syntax errors are reported from Altium's error dialog, which the tool answers before stopping the debugger (`-REditScript:Stop`) and confirming with a probe run that the next script will work. The other MCP tools recover the same way when one of their own commands gets stuck. Only scripts the MCP started are ever stopped: a script you are running or debugging in Altium is left alone, and the tool says Altium is busy instead. Scripts may start with their own `var` block; assignments to undeclared names are refused before Altium is called. The template provides `MM()`, `OpenSchDoc()` and `SaveDoc()` helpers. While waiting it closes blocking Altium dialogs (only windows owned by `X2.EXE`) and returns their titles in `dismissed_dialog_titles` - close your own Altium dialogs before running scripts, since an open dialog of yours may be closed too.
- `ensure_altium_script_skill`: Check whether the [altium-script skill](https://github.com/coffeenmusic/altium-scripts-skill) (Altium DelphiScript API reference, examples, and conventions) is installed, and install it on request. Skills load at client startup, so a newly installed skill appears after a restart.

### Server Status
- `get_server_status`: Check the status of the MCP server, including paths to Altium and script files

## How It Works

The server communicates with Altium Designer using a scripting bridge:

1. It writes the command request to `C:\Users\Public\altium_mcp\request.json`, a folder both the server and Altium can reach
2. It launches Altium with instructions to run the `Altium_API.PrjScr` script
3. The script processes the request and writes the result to `C:\Users\Public\altium_mcp\response.json`
4. The server reads and returns the response

Files exchanged with the scripts are read and written the way Altium does: in the Windows ANSI code page, or as UTF-8 when the file starts with a byte-order mark.

## References
- Get scripts' project path from Jeff Collins and William Kitchen's stripped down version
- BlenderMCP: I got inspired by hearing about MCP being used in Blender and used it as a reference. https://github.com/ahujasid/blender-mcp
- Used CopyDesignatorsToMechLayerPair script by Petar Perisin and Randy Clemmons for reference on how to .Replicate objects (used in layout duplicator)
- Petar Perisin's Select Bad Connections Script: For understanding how to walk pcb primitives (track, arc, via, etc) connected to a pad
- Matija Markovic and Petar Perisin Distribute Script: For understanding how to properly let the GUI know when I've updated tracks' nets
- Petar Perisin's Room from Poly: Used as reference to detect poly to pad overlap since I couldn't get more tradition methods to work.
- Petar Perisin's Layer Panel Script: Used as reference for getting layers and changing layer visibility
- Jeff Collins has an XIA_Release_Manager.pas script that taught me the art of the Output Job. See his post on the Altium Forums: https://forum.live.altium.com/#/posts/189423

## Contributors
- [daescobarh](https://github.com/daescobarh) — project validation tools (`get_project_info`, `get_project_components`, `get_erc_violations`, `get_board_summary`, `get_component_primitives`, `get_outjob_settings`) and safer dialog dismissal ([PR #18](https://github.com/coffeenmusic/altium-mcp/pull/18))
- [coffeedust](https://github.com/coffeedust) — `create_pcb_footprint` tool for PcbLib automation ([PR #7](https://github.com/coffeenmusic/altium-mcp/pull/7))
- [fwolter](https://github.com/fwolter) — Fix JSON parsing error when the decimal separator is a comma ([PR #3](https://github.com/coffeenmusic/altium-mcp/pull/3))

## Disclaimer
This is a third-party integration and not made by Altium. Made by [coffeenmusic](https://x.com/coffeenmusic)

# TODO:
- Change selection filter:
  - `scripts-libraries\Scripts - PCB\FilterObjects\`
  - `scripts-libraries\Scripts - SCH\SelectionFilter\`
- Show/Hide Panels: `DXP/ReportPCBViews.pas`
- Create rules: `PCB/CreateRules.pas`
- Run DRC: IPCB_Board.RunBatchDesignRuleCheck( 
- Move cursor to position: IPCB_Board.XCursor, IPCB_Board.YCursor 
- Add get schematic & pcb library path for footprint. 
- log response time of each tool
- Add go to schematic sheet
- Go to sheet with component designator
- Board.ChooseLocation(x, y, 'Test');
- Zoom to selected objects:
- Change Schematic Selection Filter: SelectionFilter.pas
- How can I read through components from libraries in Components panel?

TODO Tests:
Need to add the following test units
- `get_pcb_layers` 
- `set_pcb_layer_visibility`
- `layout_duplicator`
- `get_screenshot`
