"""Insert motor settings into LeRobot's follower configuration code.

LeRobot runs configure() every time it connects, so settings written from
a shell are undone on the next run. To make them stick they have to live
inside that code.

This module is pure text in, text out. Reading and writing the file is
commands.py's job. The insertion point is located by indentation
structure, not by matching line contents, so it survives upstream edits.
"""

MARKER = "# omx-doctor"


class PatchError(Exception):
    """The source cannot be edited."""


class AlreadyPatched(PatchError):
    """The patch is already applied."""


class AnchorNotFound(PatchError):
    """No insertion point was found."""


def find_anchor(lines):
    """Locate the torque_disabled() block.

    Returns (index of the with line, index one past the end of the block,
    indent width of the with line).
    """
    start = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("with ") and "torque_disabled()" in stripped:
            start = i
            break
    if start is None:
        raise AnchorNotFound(
            "No torque_disabled() block found. Your LeRobot version may "
            "structure this code differently."
        )

    with_indent = _indent_of(lines[start])

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip() and _indent_of(lines[j]) <= with_indent:
            end = j
            break
    if end == start + 1:
        raise AnchorNotFound("The torque_disabled() block is empty.")
    return start, end, with_indent


def _indent_of(line):
    return len(line) - len(line.lstrip())


def build_lines(with_indent, joint, settings):
    """Build the lines to insert.

    Returns the lines that go inside the block and the lines that go after
    it. EEPROM registers only accept writes while torque is off, so they
    go inside; Goal_Current is in RAM and goes after.
    """
    inside_indent = " " * (with_indent + 4)
    outside_indent = " " * with_indent

    inside = []
    for name in (
        "Operating_Mode",
        "Current_Limit",
        "Position_P_Gain",
        "Position_I_Gain",
        "Position_D_Gain",
    ):
        value = settings.get(name)
        if value is None:
            continue
        inside.append(
            '%sself.bus.write("%s", "%s", %d)  %s\n'
            % (inside_indent, name, joint, value, MARKER)
        )

    outside = []
    goal_current = settings.get("Goal_Current")
    if goal_current is not None:
        outside.append(
            '%sself.bus.write("Goal_Current", "%s", %d)  %s\n'
            % (outside_indent, joint, goal_current, MARKER)
        )

    if not inside and not outside:
        raise PatchError("No settings were given.")
    return inside, outside


def apply_patch(text, joint, settings):
    """Take the whole source as a string and return it with the settings in."""
    if MARKER in text:
        raise AlreadyPatched("The patch is already applied.")

    lines = text.splitlines(keepends=True)
    start, end, with_indent = find_anchor(lines)
    inside, outside = build_lines(with_indent, joint, settings)

    # Insert before any blank lines that trail the block, so the
    # indentation of what follows is untouched.
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1

    # If the preceding line has no newline (block at end of file), add one.
    if lines[insert_at - 1] and not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] += "\n"

    patched = lines[:insert_at] + inside + outside + lines[insert_at:]
    return "".join(patched)


def revert_patch(text):
    """Remove every line this module inserted."""
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if MARKER not in line]
    if len(kept) == len(lines):
        raise PatchError("Nothing to remove. The patch is not applied.")
    return "".join(kept), len(lines) - len(kept)
