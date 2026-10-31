"""Locate and update LeRobot calibration files.

On every connection LeRobot compares this file against the motor's
EEPROM. If they disagree it asks to recalibrate, and that process
overwrites the travel range with 0 to 4095. So the EEPROM and this file
have to be written together, with the same values.

The calculation that changes the file is a pure function; finding and
writing the file comes after it.
"""

import copy
import json
import pathlib

CALIBRATION_ROOT = ".cache/huggingface/lerobot/calibration"


class CalibrationError(Exception):
    """The calibration file cannot be used."""


# Pure functions -----------------------------------------------------


def update_joint(data, joint, range_min=None, range_max=None, homing_offset=None):
    """Return a copy with the joint's entry changed. The input is untouched."""
    if joint not in data:
        raise CalibrationError(
            "No entry named '%s'. Entries present: %s"
            % (joint, ", ".join(sorted(data)))
        )
    updated = copy.deepcopy(data)
    entry = updated[joint]
    if range_min is not None:
        entry["range_min"] = int(range_min)
    if range_max is not None:
        entry["range_max"] = int(range_max)
    if homing_offset is not None:
        entry["homing_offset"] = int(homing_offset)
    return updated


def describe_joint(data, joint):
    """Render a joint's entry as one line."""
    entry = data.get(joint)
    if entry is None:
        return "no entry named '%s'" % joint
    return "id %s, homing_offset %s, range %s to %s" % (
        entry.get("id"),
        entry.get("homing_offset"),
        entry.get("range_min"),
        entry.get("range_max"),
    )


def joints_of(data):
    """Return {joint name: motor id} for the entries in a file."""
    found = {}
    if not isinstance(data, dict):
        return found
    for name, entry in data.items():
        if isinstance(entry, dict) and "id" in entry:
            found[name] = entry["id"]
    return found


# File handling ------------------------------------------------------


def calibration_root(home=None):
    base = pathlib.Path(home) if home else pathlib.Path.home()
    return base / CALIBRATION_ROOT


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CalibrationError("Cannot read %s: %s" % (path, exc)) from exc


def find_files(joint, motor_id, root=None):
    """Find calibration files where both the joint name and motor ID match."""
    root = pathlib.Path(root) if root else calibration_root()
    if not root.exists():
        return []
    hits = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        entry = data.get(joint)
        if isinstance(entry, dict) and entry.get("id") == motor_id:
            hits.append(path)
    return hits


def find_file(joint, motor_id, root=None):
    """Return the file only when exactly one matches.

    With several matches there is no way to tell which one is in use, so
    this stops instead of guessing.
    """
    hits = find_files(joint, motor_id, root)
    if not hits:
        raise CalibrationError(
            "No calibration file contains '%s' with id %d. Connect once with "
            "LeRobot so that a calibration file exists." % (joint, motor_id)
        )
    if len(hits) > 1:
        listing = "\n".join("  %s" % p for p in hits)
        raise CalibrationError(
            "%d calibration files match, so there is no way to tell which one "
            "to edit. Delete or move the ones you do not use and run again.\n%s"
            % (len(hits), listing)
        )
    return hits[0]


def save_with_backup(path, data):
    """Keep the original as .bak and write the new contents."""
    path = pathlib.Path(path)
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        backup.write_text(path.read_text())
    path.write_text(json.dumps(data, indent=4) + "\n")
    return backup
