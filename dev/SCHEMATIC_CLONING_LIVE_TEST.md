# Cross-sheet cloning live verification

Tested on 2026-11-05 in Altium Designer Enterprise 24.4.1 with the open
`C:/workspace_altium/SALT-FMUV6X-JETSON/SALT-FMUV6X-JETSON.PrjPcb`.

## Confirmed checks

| Check | Result |
| --- | --- |
| Two instances copied between scratch copies of Display.SchDoc | Passed; two new component roots and fresh owned-object UIDs. |
| Unsaved comment/parameter overrides containing Unicode and delimiters | Preserved exactly. |
| Rotation/mirror, parameter display, pins, primitive counts and model links | Preservation readback passed. |
| Source snapshot and Modified flag | Unchanged by successful clone calls. |
| Existing target objects and prior unsaved edits | Preserved. |
| A valid selector followed by a missing designator | Rejected with zero copies; target snapshot unchanged. |
| Repeat into occupied target designators | Rejected with zero copies; target snapshot unchanged. |
| New named unsaved destination | Two copies placed; no SchDoc written. |
| Actual unsaved Supply.SchDoc used as read-only source | One instance copied; original snapshot and Modified flag preserved. |
| Same-sheet alias and missing closed target | Rejected. |

The initial project already had Modified `Supply.SchDoc` and
`Power-Sequencer-Draft.SchDoc`. Originals were never clone targets. No save or
compile command was issued. All source/target fixture edits were in memory.

## Pending multipart verification

The `M1` test on SoM.SchDoc selected placed parts 1, 3, 4, 6 and 7. The native log
recorded registration of all five copies into a unique unsaved scratch target,
then the bridge timed out before a complete response. Altium remained busy.
The mutation was not retried, and Altium was not terminated because it holds
unsaved user data. Final source/target readback and scratch cleanup are pending.

An unnecessary whole-response `DocumentJSON` pass was removed: the common
`JSONEscapeString` already escapes Unicode per value, and rebuilding a large
string character by character can be quadratic. Progress heartbeats and stage
logs were added. This correction passed offline tests; its multipart performance
must still be verified live after the running old invocation completes.

Evidence and exact recovery state are stored centrally in
`.altium-mcp/schematic_cloning_20261105_220451/`, including per-call responses,
`recovery_state.json`, original project/sheet snapshots and the retained spec
path. The incomplete run must not be reported as a fully passing live test.

Before retrying: wait for a responsive executor, inspect any late response and
the exact scratch destination, verify source state, then close only the recorded
scratch buffers without saving. Do not repeat an unknown-outcome clone blindly.

## Reproduce

```powershell
python dev/test_schematic_cloning_live.py --project "C:/Design/Controller/Controller.PrjPcb" --multipart-sheet "C:/Design/Controller/SoM.SchDoc" --multipart-designator M1 --exercise
```

The harness copies saved sources into a unique toolkit `.altium-mcp` directory,
creates unsaved destinations, records disk baselines and compares original
document states. After an unknown executor outcome it records the incomplete run
and skips further Altium calls. Without `--exercise`, no Altium action is taken.

Offline regression: 66 tests passed for cloning, script bundling, schematic
editing, metadata, opening/closing and bridge compatibility.

## Custom scripts

Read-only API probes inspected multipart root UIDs and owned parameter/model UID
trees because existing tools could not clone from an explicit different source
sheet. The probes succeeded and informed
`clone_schematic_components(source_sheet, target_sheet, designators)`.
Implementation tests called the new Python wrapper and existing dedicated tools;
the large multipart invocation has the pending outcome described above.
