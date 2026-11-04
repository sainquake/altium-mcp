# Upstream integration: v0.6.1

This integration combines upstream `53f756e` (v0.6.1) with fork `4a154e4`,
including the LCSC tools. The common ancestor is `9ad05d3` (v0.5.1).
Upstream contributes 119 commits; the fork contributes 11.

## Branches and commands

The original fork main is preserved by both `main` and the local backup branch
`codex/backup-before-upstream-2026-11-04`. Integration takes place on
`codex/sync-upstream-v0.6.1`.

```powershell
git fetch --all --prune
git branch codex/backup-before-upstream-2026-11-04 main
git switch -c codex/sync-upstream-v0.6.1
git merge --no-commit --no-ff upstream/main
```

After resolving conflicts and validating the result:

```powershell
git diff --check
git add -u
git add dev/UPSTREAM_SYNC.md server/tests/test_merge_compatibility.py
git commit -m "Merge upstream v0.6.1 and preserve fork tools"
git push -u origin codex/sync-upstream-v0.6.1
```

`fetch` updates remote history without changing the working branch. `switch -c`
creates a branch. `merge --no-commit` incorporates upstream while leaving time
to reconcile overlapping behavior. `add` marks the reviewed resolutions as
ready; `commit` records a merge with both histories as parents. `push` publishes
the integration branch to the fork. Main is not advanced by these commands.

## Compatibility decisions

- Preserve upstream's MCP 1.30 registration, read-only annotations, startup
  discovery, rotating logs, request isolation, exchange locks and script bundles.
- Preserve the fork's setup, runtime identity, exact document/project tools,
  compiler-backed connectivity, library metadata/model tools and LCSC workflow.
- Keep one public `edit_schematic` accepting both operation formats. UID
  add/update/delete operations remain in mils and never save. Upstream action
  operations retain mil/mm coordinates and optional saving. Mixed batches fail
  before dispatch. Distinct bridge commands and unique input files isolate the
  implementations. See [editor formats](EDIT_SCHEMATIC.md).
- Keep creation metadata validation while accepting upstream library edit
  records. Existing-symbol edits need no creation schema. Creation readback
  reflects property edits, and failures preserve upstream's diagnostic lists.
  See [symbol creation](SYMBOL_CREATION.md).
- Renumber script-project document sections and eliminate conflicting routine
  names so every unit participates in the production bundle exactly once.
- Extend GitHub Actions to run both branches' offline tests and integration
  regressions from the repository root. Live Altium tests remain excluded.

## Validation

Validation uses Python 3.13 on Windows and the exact `requirements.txt`,
including MCP 1.30.0. The CI command in
[tests.yml](../.github/workflows/tests.yml) ran 315 offline tests successfully
(314 passed, one skipped). The remaining
code-page-dependent test skips unless the system ANSI code page is 1252.

Additional checks cover Python 3.10-compatible syntax, production bundling of
all 11 Pascal units, unique tool names, both schematic operation formats,
batch metadata/readback and the actual server's stdio initialization. The
merged server exposes 70 tools and returns its runtime identity without
duplicating string responses as structured content.

Live Altium editing and saving have not been exercised for this merge. Offline
tests and bundling do not establish DelphiScript compilation or document-edit
behavior in a running Altium instance. Use disposable design/library copies
for the existing `dev/test_*_live.py` harnesses before relying on the merged
version for production work.
