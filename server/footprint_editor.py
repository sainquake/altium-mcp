"""Validated footprint properties, pad flags/settings and graphic layer edits."""

import json
import math
from pathlib import Path, PureWindowsPath
import re
import uuid

from altium_files import read_altium_text, write_altium_text
from library_component_data import library_path, text
from schematic_document import disk_state


CONSTANT_NAMES = {
    "eRound", "eRectangular", "eOctagonal", "eRoundedRectangular",
    "eCacheManual",
    "eTopLayer", "eBottomLayer", "eTopOverlay", "eBottomOverlay",
    "eMechanical13", "eMechanical15", "eMultiLayer", "eNoLayer",
}
GEOMETRY = {
    "track": ("x1", "y1", "x2", "y2", "width"),
    "arc": ("cx", "cy", "radius", "start_angle", "end_angle", "width"),
    "fill": ("x1", "y1", "x2", "y2", "rotation"),
}


def number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e7:
        raise ValueError(f"{label} must be a finite number within +/-10000000")
    return format(value, ".15g")


def layer_name(value, allow_no_layer=False, legacy_only=True):
    text(value, "layer", True)
    if any(c in value for c in "|\r\n"):
        raise ValueError("layer contains a record delimiter")
    name = value.strip()
    mech = re.fullmatch(r"e?Mechanical\s*(?:Layer\s*)?(\d+)", name, re.I)
    if mech:
        index = int(mech[1])
        # These are the mechanical layers exposed by the legacy Layer property.
        if not 1 <= index <= 1024:
            raise ValueError("mechanical layer number must be within 1..1024")
        if legacy_only and index > 16:
            raise ValueError("mechanical layers above 16 require the V7 layer API")
        return f"Mechanical {index}"
    if name.casefold().replace(" ", "") in ("nolayer", "enolayer"):
        if not allow_no_layer:
            raise ValueError("No Layer is not a valid destination")
        return "No Layer"
    return name


def base(path, footprint_name):
    text(footprint_name, "footprint_name", True)
    return {"library_path": library_path(path, ".pcblib"), "footprint_name": footprint_name}


def pad_selection(path, footprint_name, pad_names):
    spec = base(path, footprint_name)
    if not isinstance(pad_names, list) or not 1 <= len(pad_names) <= 1000:
        raise ValueError("pad_names must contain 1 to 1000 distinct names")
    seen = set()
    for index, name in enumerate(pad_names):
        text(name, "pad name", True)
        if name.casefold() in seen:
            raise ValueError("pad_names must be distinct")
        seen.add(name.casefold())
        spec[f"pad.{index}"] = name
    spec["count"] = str(len(pad_names))
    return spec


def prepare_pads(path, footprint_name, pad_names, mask_expansion_mm=None,
                 paste_expansion_mm=None, mode="manual"):
    spec = pad_selection(path, footprint_name, pad_names)
    if mode not in ("manual", "rule"):
        raise ValueError("mode must be manual or rule")
    if mode == "manual" and mask_expansion_mm is None and paste_expansion_mm is None:
        raise ValueError("manual mode requires at least one expansion")
    if mode == "rule" and (mask_expansion_mm is not None or paste_expansion_mm is not None):
        raise ValueError("rule mode resets both overrides and takes no expansion values")
    for prefix, value in (("mask", mask_expansion_mm), ("paste", paste_expansion_mm)):
        if mode == "rule":
            spec[f"{prefix}_mode"] = "1"
        elif value is not None:
            numeric = number(value, f"{prefix}_expansion_mm")
            if abs(float(numeric)) > 10:
                raise ValueError("mask and paste expansions must be within +/-10 mm")
            spec[f"{prefix}_mode"] = "2"
            spec[f"{prefix}_expansion"] = number(float(numeric) / 0.0254, prefix)
    return spec


def prepare_pad_properties(path, footprint_name, pad_names, is_testpoint_top=None, is_testpoint_bottom=None):
    spec = pad_selection(path, footprint_name, pad_names)
    for key, value in (("is_testpoint_top", is_testpoint_top), ("is_testpoint_bottom", is_testpoint_bottom)):
        if value is not None:
            if type(value) is not bool:
                raise ValueError(f"{key} must be a boolean or omitted")
            spec[key] = "1" if value else "0"
    return spec


def verify_pad_properties(result, spec):
    errors = []
    before, after = result.get("before"), result.get("after")
    count = int(spec["count"])
    if not isinstance(before, list) or not isinstance(after, list) or len(before) != count or len(after) != count:
        return ["pad property snapshot count mismatch"]
    requested = {spec[f"pad.{i}"].casefold() for i in range(count)}
    for rows in (before, after):
        if any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in rows):
            return ["invalid pad property snapshot"]
        if {row["name"].casefold() for row in rows} != requested:
            return ["pad identity readback mismatch"]
    before = {row["name"].casefold(): row for row in before}
    edited = {key for key in ("is_testpoint_top", "is_testpoint_bottom") if key in spec}
    changed = 0
    for row in after:
        previous = before[row["name"].casefold()]
        for key in ("is_testpoint_top", "is_testpoint_bottom"):
            if type(row.get(key)) is not bool or type(previous.get(key)) is not bool:
                errors.append("missing native testpoint flag: " + key)
            elif key in edited and row[key] is not (spec[key] == "1"):
                errors.append("testpoint flag readback mismatch: " + key)
        if {k:v for k,v in row.items() if k not in edited} != {k:v for k,v in previous.items() if k not in edited}:
            errors.append("unrequested pad properties changed: " + row["name"])
        changed += any(row.get(key) != previous.get(key) for key in edited)
    if type(result.get("changed")) is not bool or result["changed"] != bool(changed) or result.get("updated_count") != changed:
        errors.append("changed pad count mismatch")
    if any(type(result.get(key)) is not bool for key in ("was_modified", "is_modified")):
        errors.append("missing Modified state flags")
    elif (changed and result["is_modified"] is not True) or (not changed and result["was_modified"] != result["is_modified"]):
        errors.append("pad edit/no-op Modified mismatch")
    return errors


def prepare_layers(path, footprint_name, operations):
    spec = base(path, footprint_name)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 1000:
        raise ValueError("operations must contain 1 to 1000 layer updates")
    selectors = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or set(operation) != {"target", "layer"}:
            raise ValueError("each operation must have target and layer")
        target = operation["target"]
        if not isinstance(target, dict) or target.get("type") not in GEOMETRY:
            raise ValueError("target.type must be track, arc or fill")
        kind = target["type"]
        if set(target) != {"type", "layer", *GEOMETRY[kind]}:
            raise ValueError(f"{kind} target requires layer and {', '.join(GEOMETRY[kind])}")
        prefix = f"op.{index}."
        spec[prefix + "type"] = kind
        spec[prefix + "from_layer"] = layer_name(target["layer"], True)
        spec[prefix + "to_layer"] = layer_name(operation["layer"])
        for field in GEOMETRY[kind]:
            spec[prefix + field] = number(target[field], field)
        identity = tuple((key[len(prefix):], value) for key, value in spec.items()
                         if key.startswith(prefix) and key != prefix + "to_layer")
        if identity in selectors:
            raise ValueError("duplicate primitive selector")
        selectors.add(identity)
    spec["count"] = str(len(operations))
    return spec


def prepare_constants(names):
    if not isinstance(names, list) or not names or len(names) > len(CONSTANT_NAMES):
        raise ValueError("names must be a nonempty list of supported enum names")
    if any(not isinstance(name, str) or name not in CONSTANT_NAMES for name in names):
        raise ValueError("unsupported constant; supported: " + ", ".join(sorted(CONSTANT_NAMES)))
    if len(set(names)) != len(names):
        raise ValueError("constant names must be distinct")
    return {"count": str(len(names)), **{f"name.{i}": name for i, name in enumerate(names)}}


def prepare_properties(path, footprint_name, height_mm=None):
    spec = {**base(path, footprint_name), "count": "1"}
    if height_mm is not None:
        if type(height_mm) not in (int, float) or abs(height_mm) > 1000 or not math.isfinite(height_mm) or height_mm < 0:
            raise ValueError("height_mm must be a finite number from 0 to 1000 mm")
        spec["height_mm"] = format(height_mm, ".15g")
    return spec


def verify_properties(result, spec):
    errors = []
    if any(type(result.get(key)) is not bool for key in ("changed", "was_modified", "is_modified")):
        errors.append("missing property state flags")
    before, after = result.get("before"), result.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ["missing property snapshots"]
    actual = after.get("height_mm")
    expected = float(spec["height_mm"]) if "height_mm" in spec else before.get("height_mm")
    if type(actual) not in (int, float) or type(expected) not in (int, float) or not math.isfinite(actual) or abs(actual - expected) > .000003:
        errors.append("height_mm readback mismatch")
    if {k:v for k,v in before.items() if k != "height_mm"} != {k:v for k,v in after.items() if k != "height_mm"}:
        errors.append("unrequested footprint properties changed")
    if result.get("changed"):
        if "height_mm" not in spec:
            errors.append("read-only request changed the footprint")
        if result.get("is_modified") is not True or result.get("updated_count") != 1:
            errors.append("changed library is not marked Modified or update count is invalid")
    elif result.get("was_modified") != result.get("is_modified") or result.get("updated_count") != 0:
        errors.append("no-op changed Modified state or update count")
    return errors


async def execute(bridge, exchange_dir, command, prepare, *args, **kwargs):
    mutating = command != "get_pcb_api_constants"
    properties = command in {"set_footprint_properties", "set_footprint_pad_properties"}
    try:
        spec = prepare(*args, **kwargs)
        if properties:
            mutating = any(key in spec for key in ("height_mm", "is_testpoint_top", "is_testpoint_bottom"))
            before_disk = disk_state(spec["library_path"])
    except (ValueError, TypeError, OSError) as exc:
        return json.dumps({"success": False, "error": str(exc), "saved": False,
                           "may_have_partial_changes": False})
    spec_path = exchange_dir / f"{command}_{uuid.uuid4().hex}.txt"
    write_altium_text(spec_path, "\n".join(f"{key}={json.dumps(value, ensure_ascii=False)[1:-1]}"
                                         for key, value in spec.items()) + "\n")
    completed = False
    try:
        try:
            response = await bridge.execute_command(command, {"spec_file": str(spec_path)})
        except Exception as exc:
            response = {"error": str(exc)}
        if response.get("command_started") is False:
            completed = True
            return json.dumps({"success": False, "error": response.get("error", "command was not started"),
                               "command_started": False, "saved": False, "may_have_partial_changes": False})
        result = response.get("result", {})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        completed = isinstance(result, dict) and type(result.get("success")) is bool
        if not completed:
            return json.dumps({"success": False, "error": response.get("error", "invalid bridge result"),
                               "outcome_unknown": True, "saved": False,
                               "may_have_partial_changes": mutating, "spec_file": str(spec_path)})
        errors = []
        if result.get("success"):
            if command != "get_pcb_api_constants":
                actual_path = result.get("library_path")
                if not isinstance(actual_path, str) or PureWindowsPath(actual_path) != PureWindowsPath(spec["library_path"]):
                    errors.append("library identity mismatch")
                if str(result.get("footprint_name", "")).casefold() != spec["footprint_name"].casefold():
                    errors.append("footprint identity mismatch")
                if type(result.get("verified_count")) is not int or result["verified_count"] != int(spec["count"]):
                    errors.append("edit readback was not confirmed")
                if properties:
                    verify = verify_pad_properties if command == "set_footprint_pad_properties" else verify_properties
                    errors.extend(verify(result, spec))
            else:
                values = result.get("constants")
                expected = {spec[f"name.{i}"] for i in range(int(spec["count"]))}
                if not isinstance(values, dict) or set(values) != expected or any(type(v) is not int for v in values.values()):
                    errors.append("constant readback mismatch")
            if result.get("saved") is not False:
                errors.append("edit readback was not confirmed")
        if properties:
            try:
                if disk_state(spec["library_path"]) != before_disk:
                    errors.append("library file changed unexpectedly")
            except OSError as exc:
                errors.append("cannot verify library file: " + str(exc))
        if result.get("success") or errors:
            result["verification"] = {"passed": not errors, "errors": errors}
        if errors:
            result.update(success=False, error="footprint API readback failed", may_have_partial_changes=mutating)
        return json.dumps(result, indent=2, ensure_ascii=False)
    finally:
        if completed:
            spec_path.unlink(missing_ok=True)


def prepare_batch_file(spec_file, exchange_dir):
    """Normalize mechanical aliases in a private copy, preserving the caller's file."""
    source = Path(spec_file)
    if not source.is_file():
        raise ValueError("spec_file must be an existing file")
    lines = read_altium_text(source).splitlines()
    fields_by_kind = {"PAD": (5,), "TRACK": (6,), "ARC": (7,), "FILL": (6,),
                      "TEXT": (6,), "REGION": (1,), "MODEL3D": (2,), "VIA": (5, 6)}
    for index, line in enumerate(lines):
        fields = line.split("|")
        kind = fields[0].strip().upper()
        if kind == "FPLIB" and len(fields) > 1:
            fields[1] = library_path(fields[1].strip(), ".pcblib")
        for position in fields_by_kind.get(kind, ()):
            if position >= len(fields):
                raise ValueError(f"line {index + 1}: missing layer")
            fields[position] = layer_name(fields[position], legacy_only=False)
        lines[index] = "|".join(fields)
    destination = exchange_dir / f"footprint_batch_{uuid.uuid4().hex}.txt"
    write_altium_text(destination, "\n".join(lines) + "\n")
    return destination
