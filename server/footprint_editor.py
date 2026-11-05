"""Validated edits of existing library pads and graphic primitive layers."""

import json
import math
from pathlib import Path, PureWindowsPath
import re
import uuid

from altium_files import read_altium_text, write_altium_text
from library_component_data import library_path, text


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


def prepare_pads(path, footprint_name, pad_names, mask_expansion_mm=None,
                 paste_expansion_mm=None, mode="manual"):
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


async def execute(bridge, exchange_dir, command, prepare, *args, **kwargs):
    mutating = command != "get_pcb_api_constants"
    try:
        spec = prepare(*args, **kwargs)
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
        if result.get("success"):
            errors = []
            if mutating:
                actual_path = result.get("library_path")
                if not isinstance(actual_path, str) or PureWindowsPath(actual_path) != PureWindowsPath(spec["library_path"]):
                    errors.append("library identity mismatch")
                if str(result.get("footprint_name", "")).casefold() != spec["footprint_name"].casefold():
                    errors.append("footprint identity mismatch")
                if type(result.get("verified_count")) is not int or result["verified_count"] != int(spec["count"]):
                    errors.append("edit readback was not confirmed")
            else:
                values = result.get("constants")
                expected = {spec[f"name.{i}"] for i in range(int(spec["count"]))}
                if not isinstance(values, dict) or set(values) != expected or any(type(v) is not int for v in values.values()):
                    errors.append("constant readback mismatch")
            if result.get("saved") is not False:
                errors.append("edit readback was not confirmed")
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
