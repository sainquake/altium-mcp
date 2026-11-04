# Symbol creation metadata

`create_schematic_symbol` and `create_symbols_batch` require populated metadata
before creating anything in Altium. Existing project symbols and libraries are
not migrated. `set_library_component_data` remains a general metadata editor;
it does not require the creation schema for existing symbols.

## Required fields

| Parameter | Content |
|---|---|
| `Value` | Nominal value or a useful functional value for non-passives |
| `MF` | Actual manufacturer |
| `MP` | Manufacturer part number |
| `HelpURL` | Absolute HTTP(S) documentation URL |
| `Package` | Package/case designation, such as 0603 or LQFP-100 |
| `Type` | Component or mounting type, such as SMD |
| `Instructions` | Assembly instruction, such as Fit or DNP |
| `System` | Functional block, such as Power or MCU |

All eight fields must contain nonempty string values. Empty strings and common
placeholders (`None`, `N/A`, `TBD`, `*`, etc.) are rejected. Missing information
must be obtained from the user or an authoritative component source; the server
does not invent values. Names match case-insensitively and use the spelling above
when stored. Additional string parameters are allowed, up to 500 total.
JLCPCB/LCSC fields are optional. Duplicate names are rejected.

Use [`get_lcsc_component_info`](LCSC_COMPONENT_DATA.md) to obtain catalog data.
After creation, `set_library_component_lcsc_data(library_path, symbol_name,
lcsc_id, qty=1)` fills only supplier fields after checking the symbol's MP.
Alternatively, merge the chosen card's `lcsc_parameters` into the creation
parameter dictionary; the existing required core fields still apply.

`Pacage` and `Pacage Metric` are rejected; use `Package`. Built-in `Comment`,
`Designator` and `Description` cannot be supplied as custom parameters. Comment
is set to MP and hidden; Value is visible below the symbol, while other custom
parameters are hidden and shared across symbol parts. No document is saved.

## Searchable Description

The separate `description` argument populates Altium's native component
Description (`ComponentDescription`), which is used in library searches.
Include the category/function, important electrical ratings and package, using
verified datasheet information. For example:

```text
Resistor, 10k, 1%, 100mW, 0603 SMD
```

The server rejects blank descriptions, common placeholders, a symbol name or
MPN alone, and descriptions with fewer than three whitespace-separated words.
This is a basic quality gate, not datasheet verification: the caller still must
provide accurate specifications. Description is transported separately from
pin records, preserving Unicode, punctuation, quotes and line breaks.

## Single symbol

`parameters` is now a required argument, before optional `part_count` and
`graphics`. Existing callers must supply it. The desired SchLib must be focused.

```python
create_schematic_symbol(
    symbol_name="R-10K",
    description="Resistor, 10k, 1%, 100mW, 0603 SMD",
    pins=[
        "1|A|eElectricPassive|eRotate0|0|0",
        "2|B|eElectricPassive|eRotate180|600|0",
    ],
    parameters={
        "Value": "10k", "MF": "Example", "MP": "R-10K",
        "HelpURL": "https://example.com/datasheet.pdf",
        "Package": "0603", "Type": "SMD",
        "Instructions": "Fit", "System": "Power",
    },
)
```

The example data is illustrative. Replace it with actual component data.

## Batch creation

Add a complete set of `PARAM|name|value` records for **each** symbol:

```text
LIBRARY|C:\Libraries\Parts.SchLib
SYMBOL|R-10K|Resistor, 10k, 1%, 100mW, 0603 SMD|1
PARAM|Value|10k
PARAM|MF|Example
PARAM|MP|R-10K
PARAM|HelpURL|https://example.com/datasheet.pdf
PARAM|Package|0603
PARAM|Type|SMD
PARAM|Instructions|Fit
PARAM|System|Power
PIN|1|A|eElectricPassive|eRotate0|0|0
PIN|2|B|eElectricPassive|eRotate180|600|0
```

All blocks are validated before opening a library or creating the first symbol.
Unknown records, duplicate symbol names and incomplete later blocks reject the
whole request. `LIBRARY` is optional and may appear only before the first symbol;
its path must be absolute and identify an existing SchLib. Records are single
lines; a batch Description cannot contain `|`. Parameter values retain everything
after the second `|`, including additional pipes, commas, quotes and equals signs.
The tool sends a unique BOM-marked UTF-8 copy, leaving the input file unchanged.

## Readback, failures and loading the update

Creation returns actual `metadata`, `verification`, and `saved=false`. Readback
compares all requested parameters, native Description and Comment. Batch output
also contains a per-symbol `components` list. A mismatch makes `success=false`.
API failures or timeouts can leave partial in-memory changes; inspect the result
before retrying. No atomic rollback is promised. Uncertain bridge failures retain
the input file under the shared exchange directory for diagnosis.

Restart/reconnect the MCP server to load the new required argument and validator.
If Altium retains old script buffers, reopen `Altium_API.PrjScr` without saving
stale buffers over the updated source. Python and DelphiScript must be updated
together; the old direct bridge request without `metadata_file` is unsupported.

```powershell
python -m unittest server.tests.test_symbol_metadata -v
python dev/test_symbol_creation_live.py --schlib 'C:\Project\Symbols.SchLib'
```

The live runner creates test symbols only in an unsaved scratch copy under the
toolkit's `.altium-mcp` directory and verifies source metadata and disk hashes.
