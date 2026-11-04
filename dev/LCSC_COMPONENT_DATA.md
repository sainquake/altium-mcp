# Minimal LCSC component data

The MCP exposes two focused operations:

```python
get_lcsc_component_info(query="LMR16030SDDAR", qty=100)
get_lcsc_component_info(query="C136648", qty=100)

# After creating the symbol with create_schematic_symbol or create_symbols_batch:
set_library_component_lcsc_data(
    library_path="C:/Design/Parts.SchLib",
    symbol_name="LMR16030SDDAR",
    lcsc_id="C136648",
    qty=100,
)
```

The lookup does not access Altium. The second operation updates only one exact
existing SchLib symbol in memory through `set_library_component_data`; it never
saves the library or updates placed schematic components.

## Extraction scope

`server/lcsc_catalog.py` adapts `LcscClient` and `component_from_payload` from
the user's `C:/workspace_altium/altium-delphiscript-toolkit/lcsc_tool.py`.
The source file was read without edits. Its SHA-256 at extraction was
`f1d71d0baef139f0c0cbc2ef32435af0e0e10636355d9c1a4dcfce7984cabb70`.

Only search/detail HTTP access, response parsing and quantity-price calculation
were extracted. There is no runtime dependency on that repository, no third-party
Python dependency, CLI, SQLite cache, job system, analog search, ranking, project
batch workflow or copied DelphiScript application layer. The existing native
SchLib metadata writer handles validation, parameter creation and readback.

Requests use the source client's public-web endpoints under
`https://wmsc.lcsc.com/ftps/wm`: `POST /product/query/list` and
`GET /product/detail?productCode=C...`, with a USD currency cookie. They are not
a documented authenticated LCSC API. Timeout is 15 seconds per attempt, with one
retry for transient transport/server errors and a 20 MiB response limit. Rate
limits, HTTP errors and changed JSON schemas return explicit failures.

## Lookup response

`query` accepts an exact C-number, MPN or search text. `limit` is 1..10 (default
5) and `qty` is a positive integer (maximum 1,000,000,000). C-numbers go directly
to the detail endpoint. Text/MPN lookup requests one bounded search page; exact
MPN matches in that page are preferred, otherwise the returned candidates remain
explicit. Multiple exact matches are not silently ranked or selected.

Every candidate is hydrated from its detail card, rather than returning the
lighter search summary. The response includes:

- C-number, MPN, manufacturer, category/path, description and package.
- `parameters`: all available catalog technical names and values with original
  units. No SI inference, electrical compatibility checks or PDF parsing occur.
- Datasheet and canonical LCSC product URLs.
- Stock, MOQ, requested/order quantities, all USD price breaks and the applicable
  unit price/batch cost.
- UTC `fetched_at`, plus `lcsc_parameters`, a string dictionary ready for the
  symbol's creation parameter dictionary.

Missing stock/MOQ/prices stay `null`, not invented zeroes. `order_qty` is at least
the reported MOQ when known; price is selected only when a returned tier applies.
No quote is invented below the lowest returned tier or when MOQ is unknown.
Catalog quantities/prices are snapshots and the order calculation does not model
checkout fees, shipping, taxes or packaging multiples.

A completed search with no candidates returns `success=true`, `result_count=0`
and an empty `components` list. A missing exact code or network/schema failure
returns `success=false`. No Altium changes happen during lookup.

## Applying supplier fields

`set_library_component_lcsc_data` accepts an exact C-number, not an implicit
result index. It fetches a fresh detail card, reads the exact symbol and requires
one nonempty MP matching the card's MPN case-insensitively. A missing/ambiguous MP,
mismatch or failed lookup returns without writing fields.

The library path follows `set_library_component_data`: an absolute path to an
existing SchLib. A newly created symbol may still be unsaved in that library.

The operation upserts only these 15 string fields:

| Identity and documentation | Procurement snapshot |
| --- | --- |
| `JLCPCB Part#` | `LCSC Stock` |
| `LCSC URL` | `LCSC MOQ` |
| `LCSC MPN` | `LCSC Requested Qty` |
| `LCSC Manufacturer` | `LCSC Order Qty` |
| `LCSC Category` | `LCSC Unit Price` |
| `LCSC Description` | `LCSC Batch Cost` |
| `LCSC Package` | `LCSC Currency` |
| `LCSC Datasheet URL` | |

`JLCPCB Part#` follows the existing project's convention of storing the LCSC
C-number; this does not check JLCPCB assembly inventory or Basic/Extended class.
Unknown values become empty strings, clearing stale supplier data instead of
retaining an old price or stock value. No retrieval timestamp is written as a
parameter, so equivalent repeated data can return `changed=false`.

Core fields (`Value`, `MF`, `MP`, `HelpURL`, `Package`, `Type`, `Instructions`,
`System`), Comment, native Description, unrelated parameters, models and geometry
are left alone. `Pacage` is never created. Source-tool workflow fields such as
score, search mode and applied-result index are deliberately not transferred.

The result retains the native writer's before/after snapshots, `changed`,
`saved=false`, Modified state and readback verification, plus `lcsc_id`,
`lcsc_fetched_at` and `lcsc_parameter_names`. Changed metadata must leave the
library marked Modified. A native/API failure can leave partial in-memory edits;
inspect `may_have_partial_changes` before retrying. Do not edit the same symbol
concurrently between its read and write.

For writing at creation time, use the chosen card's dictionary:

```python
parameters = {**core_parameters, **chosen_component["lcsc_parameters"]}
```

The normal creation schema remains unchanged. Choose the matching card explicitly;
the generic creation tool does not independently resolve a C-number. `Value`,
assembly instructions and functional block still need component/project context.

## Verification and loading

```powershell
python -m unittest server.tests.test_lcsc_catalog server.tests.test_library_component_data -v
python dev/test_lcsc_catalog_live.py --schlib 'C:\Project\Symbols.SchLib' --lcsc-id C136648
```

The live harness fetches a real part, creates symbols only in an unsaved library
copy under the toolkit's ignored `.altium-mcp` directory, applies supplier fields,
tests repeat/mismatched-MPN behavior and compares core fields, geometry, source
disk hashes and modification timestamps. It leaves scratch symbols available for
inspection and restores the original project/editor. Do not run other Altium
calls concurrently with the harness.

See [live results](LCSC_COMPONENT_DATA_LIVE_TEST.md). Reconnect/restart the MCP
server to expose the two new tools; load updated production scripts when Altium
holds stale buffers. No user configuration or dependency installation is needed.
