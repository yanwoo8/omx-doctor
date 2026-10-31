"""Unit tests for patch.py.

These check that the insertion point is found by indentation rather than
by matching line contents, and that the result is valid Python. LeRobot
does not need to be installed.
"""

import textwrap

import pytest

from omx_doctor import patch

# A stand-in for LeRobot's configure(). The line contents are
# deliberately not the ones upstream uses.
SOURCE = textwrap.dedent(
    """\
    class OMXFollower(Robot):
        name = "omx_follower"

        def configure(self) -> None:
            with self.bus.torque_disabled():
                self.bus.configure_motors()
                for motor in self.bus.motors:
                    self.bus.write("Operating_Mode", motor, 3)
                    self.bus.write("P_Coefficient", motor, 16)

        def setup_motors(self) -> None:
            for motor in reversed(self.bus.motors):
                self.bus.setup_motor(motor)
    """
)

SETTINGS = {
    "Operating_Mode": 5,
    "Current_Limit": 600,
    "Position_P_Gain": 800,
    "Position_I_Gain": 0,
    "Position_D_Gain": 0,
    "Goal_Current": 100,
}


def compiles(text):
    compile(text, "<patched>", "exec")
    return True


class TestFindAnchor:
    def test_finds_the_with_line(self):
        lines = SOURCE.splitlines(keepends=True)
        start, _, indent = patch.find_anchor(lines)
        assert "torque_disabled()" in lines[start]
        assert indent == 8

    def test_block_ends_at_the_next_def(self):
        lines = SOURCE.splitlines(keepends=True)
        _, end, _ = patch.find_anchor(lines)
        assert lines[end].lstrip().startswith("def setup_motors")

    def test_missing_with_line_raises(self):
        with pytest.raises(patch.AnchorNotFound):
            patch.find_anchor(["def configure(self):\n", "    pass\n"])

    def test_other_indent_widths_work(self):
        lines = [
            "def configure(self):\n",
            "  with self.bus.torque_disabled():\n",
            "    self.bus.configure_motors()\n",
        ]
        start, end, indent = patch.find_anchor(lines)
        assert (start, end, indent) == (1, 3, 2)


class TestBuildLines:
    def test_eeprom_inside_goal_current_outside(self):
        inside, outside = patch.build_lines(8, "gripper", SETTINGS)
        assert all(line.startswith(" " * 12) for line in inside)
        assert len(outside) == 1
        assert outside[0].startswith(" " * 8)
        assert "Goal_Current" in outside[0]

    def test_every_line_carries_the_marker(self):
        inside, outside = patch.build_lines(8, "gripper", SETTINGS)
        assert all(patch.MARKER in line for line in inside + outside)

    def test_the_joint_name_is_used(self):
        inside, _ = patch.build_lines(8, "wrist_roll", SETTINGS)
        assert all('"wrist_roll"' in line for line in inside)

    def test_settings_not_given_are_skipped(self):
        inside, outside = patch.build_lines(8, "gripper", {"Current_Limit": 600})
        assert len(inside) == 1
        assert "Current_Limit" in inside[0]
        assert outside == []

    def test_zero_is_written(self):
        inside, _ = patch.build_lines(8, "gripper", {"Position_I_Gain": 0})
        assert "Position_I_Gain" in inside[0]
        assert ", 0)" in inside[0]

    def test_no_settings_raises(self):
        with pytest.raises(patch.PatchError):
            patch.build_lines(8, "gripper", {})


class TestApplyPatch:
    def test_result_is_valid_python(self):
        assert compiles(patch.apply_patch(SOURCE, "gripper", SETTINGS))

    def test_every_setting_is_present(self):
        result = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        for name in SETTINGS:
            assert name in result

    def test_nothing_is_deleted(self):
        result = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        for line in SOURCE.splitlines():
            assert line in result

    def test_indentation_inside_and_outside_the_block(self):
        result = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        for line in result.splitlines():
            if patch.MARKER not in line:
                continue
            indent = len(line) - len(line.lstrip())
            assert indent == (8 if "Goal_Current" in line else 12)

    def test_inserted_before_the_trailing_blank_line(self):
        lines = patch.apply_patch(SOURCE, "gripper", SETTINGS).splitlines()
        last = max(i for i, line in enumerate(lines) if patch.MARKER in line)
        assert lines[last + 1].strip() == ""

    def test_applying_twice_raises(self):
        once = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        with pytest.raises(patch.AlreadyPatched):
            patch.apply_patch(once, "gripper", SETTINGS)

    def test_missing_with_line_raises(self):
        with pytest.raises(patch.AnchorNotFound):
            patch.apply_patch("x = 1\n", "gripper", SETTINGS)

    def test_block_at_end_of_file(self):
        source = "def configure(self):\n    with self.bus.torque_disabled():\n        pass"
        assert compiles(patch.apply_patch(source, "gripper", SETTINGS))


class TestRevertPatch:
    def test_revert_restores_the_original(self):
        once = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        reverted, removed = patch.revert_patch(once)
        assert reverted == SOURCE
        assert removed == 6

    def test_unpatched_source_raises(self):
        with pytest.raises(patch.PatchError):
            patch.revert_patch(SOURCE)

    def test_can_reapply_after_revert(self):
        once = patch.apply_patch(SOURCE, "gripper", SETTINGS)
        reverted, _ = patch.revert_patch(once)
        assert compiles(patch.apply_patch(reverted, "gripper", SETTINGS))
