"""Required metadata and preflight for single and batch symbol creation."""

import json
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

from altium_files import read_altium_text


REQUIRED_PARAMETERS = ("Value", "MF", "MP", "HelpURL", "Package", "Type", "Instructions", "System")
CANONICAL_NAMES = {name.casefold(): name for name in REQUIRED_PARAMETERS}
PLACEHOLDERS = {"", "none", "null", "n/a", "na", "unknown", "tbd", "todo", "?", "-", "*", "value",
                "new component", "component", "description"}


def text(value, label, nonempty=False):
    if not isinstance(value, str) or "\x00" in value or (nonempty and not value.strip()):
        raise ValueError(f"{label} must be a {'nonempty ' if nonempty else ''}string without NUL")


def validate(symbol_name, description, parameters):
    """Return canonical parameter names; never invent missing component data."""
    text(symbol_name, "symbol_name", True)
    text(description, "description", True)
    if not isinstance(parameters, dict) or len(parameters) > 500:
        raise ValueError("parameters must be an object of at most 500 string values")
    normalized = {}
    seen = set()
    for name, value in parameters.items():
        text(name, "parameter name", True)
        text(value, f"parameter {name}")
        folded = name.casefold()
        if name != name.strip() or any(c in name for c in "=|\r\n"):
            raise ValueError("parameter names cannot have surrounding whitespace or =, |, CR, LF")
        if folded in seen:
            raise ValueError(f"duplicate parameter name: {name}")
        if folded in {"comment", "designator", "description"}:
            raise ValueError(f"{name} is a built-in field, not a custom creation parameter")
        if folded in {"pacage", "pacage metric"}:
            raise ValueError(f"{name} is obsolete; use Package")
        seen.add(folded)
        normalized[CANONICAL_NAMES.get(folded, name)] = value
    missing = [name for name in REQUIRED_PARAMETERS if name not in normalized]
    if missing:
        raise ValueError("missing required parameters: " + ", ".join(missing))
    for name in REQUIRED_PARAMETERS:
        if normalized[name].strip().casefold() in PLACEHOLDERS:
            raise ValueError(f"{name} must contain an actual value, not an empty string or placeholder")
    url = urlsplit(normalized["HelpURL"])
    if url.scheme.lower() not in {"http", "https"} or not url.netloc or any(c.isspace() for c in normalized["HelpURL"]):
        raise ValueError("HelpURL must be an absolute HTTP(S) documentation URL")
    if (description.strip().casefold() in PLACEHOLDERS
            or description.strip().casefold() in {symbol_name.strip().casefold(), normalized["MP"].strip().casefold()}
            or len(description.split()) < 3):
        raise ValueError("description must describe the component category, function/specifications and package "
                         "in at least three words; a placeholder or part number alone is insufficient")
    return normalized


def prepare(symbol_name, description, pins, parameters, part_count=1, graphics=None):
    parameters = validate(symbol_name, description, parameters)
    if type(part_count) is not int or not 1 <= part_count <= 1000:
        raise ValueError("part_count must be an integer from 1 to 1000")
    for name, entries in (("pins", pins), ("graphics", graphics if graphics is not None else [])):
        if not isinstance(entries, list):
            raise ValueError(f"{name} must be a list of strings")
        for entry in entries:
            text(entry, name + " entry", True)
            if entry.startswith("Description="):
                raise ValueError("pass the description in its separate argument")
    fields = {"description": description, "parameter_count": len(parameters)}
    for index, (name, value) in enumerate(parameters.items()):
        fields[f"p{index}.name"] = name
        fields[f"p{index}.value"] = value
    spec = "\n".join(f"{key}={json.dumps(str(value), ensure_ascii=False)[1:-1]}" for key, value in fields.items()) + "\n"
    return spec, parameters


def prepare_batch(spec_file):
    """Validate every block before Altium opens a library or creates a symbol."""
    text(spec_file, "spec_file", True)
    lines = read_altium_text(spec_file).splitlines()
    current = None
    symbols = []
    names = set()
    library_seen = False
    prepared_lines = []

    def finish():
        if current is None:
            return
        _, parameters = prepare(current["symbol_name"], current["description"], current["pins"],
                                current["parameters"], current["part_count"], current["graphics"])
        current["parameters"] = parameters
        symbols.append(current)

    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        kind, _, rest = line.partition("|")
        kind = kind.strip().upper()
        prepared_lines.append(kind + "|" + rest)
        try:
            if kind == "LIBRARY":
                if library_seen or current is not None:
                    raise ValueError("LIBRARY may appear only once before the first SYMBOL")
                path = rest.strip()
                if not PureWindowsPath(path).is_absolute() or Path(path).suffix.lower() != ".schlib" or not Path(path).is_file():
                    raise ValueError("LIBRARY must be an absolute path to an existing .SchLib")
                library_seen = True
            elif kind == "SYMBOL":
                finish()
                fields = rest.split("|")
                if len(fields) not in (2, 3):
                    raise ValueError("expected SYMBOL|name|description[|part_count]; description cannot contain |")
                name, description = fields[:2]
                name = name.strip()
                if name.casefold() in names:
                    raise ValueError(f"duplicate symbol name: {name}")
                names.add(name.casefold())
                current = {"symbol_name": name, "description": description,
                           "part_count": int(fields[2]) if len(fields) == 3 and fields[2].strip() else 1,
                           "parameters": {}, "pins": [], "graphics": []}
            elif current is None:
                raise ValueError("expected SYMBOL before component records")
            elif kind == "PARAM":
                name, separator, value = rest.partition("|")
                if not separator:
                    raise ValueError("expected PARAM|name|value")
                if any(name.casefold() == existing.casefold() for existing in current["parameters"]):
                    raise ValueError(f"duplicate parameter name: {name}")
                current["parameters"][name] = value
            elif kind in {"PIN", "GRAPHIC"}:
                current["pins" if kind == "PIN" else "graphics"].append(rest)
            else:
                raise ValueError(f"unknown record: {kind}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    finish()
    if not symbols:
        raise ValueError("batch must contain at least one SYMBOL")
    return "\n".join(prepared_lines) + "\n", symbols


def verify(result, description, parameters):
    """Compare Altium readback to the request, including the native Description."""
    metadata = result.get("metadata", {})
    actual = {name.casefold(): value for name, value in metadata.get("parameters", {}).items()}
    errors = [f"parameter mismatch: {name}" for name, value in parameters.items() if actual.get(name.casefold()) != value]
    if metadata.get("description") != description:
        errors.append("native Description mismatch")
    if metadata.get("comment") != parameters["MP"]:
        errors.append("Comment mismatch")
    result["verification"] = {"passed": not errors, "errors": errors}
    if errors:
        result.update(success=False, error="created symbol metadata readback mismatch", may_have_partial_changes=True)
    return result
