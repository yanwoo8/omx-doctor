"""Unit tests for calib.py.

These cover the calculation that edits a calibration file and the rule
for locating one. LeRobot does not need to be installed.
"""

import json

import pytest

from omx_doctor import calib

SAMPLE = {
    "shoulder_pan": {
        "id": 11,
        "drive_mode": 0,
        "homing_offset": 0,
        "range_min": 0,
        "range_max": 4095,
    },
    "gripper": {
        "id": 16,
        "drive_mode": 0,
        "homing_offset": 0,
        "range_min": 0,
        "range_max": 4095,
    },
}


class TestUpdateJoint:
    def test_changes_the_range(self):
        result = calib.update_joint(SAMPLE, "gripper", range_min=2123, range_max=2873)
        assert result["gripper"]["range_min"] == 2123
        assert result["gripper"]["range_max"] == 2873

    def test_does_not_mutate_the_input(self):
        calib.update_joint(SAMPLE, "gripper", range_min=2123, range_max=2873)
        assert SAMPLE["gripper"]["range_min"] == 0

    def test_other_joints_are_untouched(self):
        result = calib.update_joint(SAMPLE, "gripper", range_min=2123)
        assert result["shoulder_pan"] == SAMPLE["shoulder_pan"]

    def test_fields_not_given_are_kept(self):
        result = calib.update_joint(SAMPLE, "gripper", range_min=2123)
        assert result["gripper"]["range_max"] == 4095
        assert result["gripper"]["homing_offset"] == 0

    def test_can_change_the_zero_point(self):
        result = calib.update_joint(SAMPLE, "gripper", homing_offset=100)
        assert result["gripper"]["homing_offset"] == 100

    def test_id_and_drive_mode_survive(self):
        result = calib.update_joint(SAMPLE, "gripper", range_min=2123)
        assert result["gripper"]["id"] == 16
        assert result["gripper"]["drive_mode"] == 0

    def test_unknown_joint_raises_and_lists_what_exists(self):
        with pytest.raises(calib.CalibrationError) as exc:
            calib.update_joint(SAMPLE, "elbow", range_min=0)
        assert "gripper" in str(exc.value)


class TestJointsOf:
    def test_extracts_joints_and_ids(self):
        assert calib.joints_of(SAMPLE) == {"shoulder_pan": 11, "gripper": 16}

    def test_entries_without_an_id_are_skipped(self):
        assert calib.joints_of({"note": {"text": "x"}}) == {}

    def test_non_mapping_returns_empty(self):
        assert calib.joints_of([1, 2]) == {}


class TestDescribeJoint:
    def test_holds_the_key_values(self):
        text = calib.describe_joint(SAMPLE, "gripper")
        assert "16" in text
        assert "4095" in text

    def test_unknown_joint(self):
        assert "no entry" in calib.describe_joint(SAMPLE, "elbow")


def write_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


class TestFindFile:
    def test_matches_on_joint_name_and_id(self, tmp_path):
        target = write_file(tmp_path / "robots/omx/omx_arm.json", SAMPLE)
        assert calib.find_file("gripper", 16, root=tmp_path) == target

    def test_wrong_id_does_not_match(self, tmp_path):
        write_file(tmp_path / "robots/omx/omx_arm.json", SAMPLE)
        with pytest.raises(calib.CalibrationError):
            calib.find_file("gripper", 6, root=tmp_path)

    def test_wrong_joint_name_does_not_match(self, tmp_path):
        write_file(tmp_path / "robots/omx/omx_arm.json", SAMPLE)
        with pytest.raises(calib.CalibrationError):
            calib.find_file("elbow", 16, root=tmp_path)

    def test_several_matches_stop_instead_of_guessing(self, tmp_path):
        write_file(tmp_path / "robots/a/a_arm.json", SAMPLE)
        write_file(tmp_path / "robots/b/b_arm.json", SAMPLE)
        with pytest.raises(calib.CalibrationError) as exc:
            calib.find_file("gripper", 16, root=tmp_path)
        assert "2 calibration files" in str(exc.value)

    def test_leader_and_follower_are_told_apart_by_id(self, tmp_path):
        leader = dict(SAMPLE)
        leader["gripper"] = dict(SAMPLE["gripper"], id=6)
        write_file(tmp_path / "teleoperators/omx/omx_arm.json", leader)
        follower = write_file(tmp_path / "robots/omx/omx_arm.json", SAMPLE)
        assert calib.find_file("gripper", 16, root=tmp_path) == follower

    def test_broken_json_is_skipped(self, tmp_path):
        (tmp_path / "robots").mkdir(parents=True)
        (tmp_path / "robots/broken.json").write_text("{not json")
        target = write_file(tmp_path / "robots/omx/omx_arm.json", SAMPLE)
        assert calib.find_file("gripper", 16, root=tmp_path) == target

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(calib.CalibrationError):
            calib.find_file("gripper", 16, root=tmp_path / "nowhere")


class TestSaveWithBackup:
    def test_keeps_the_original(self, tmp_path):
        path = write_file(tmp_path / "omx_arm.json", SAMPLE)
        updated = calib.update_joint(SAMPLE, "gripper", range_min=2123)
        backup = calib.save_with_backup(path, updated)
        assert json.loads(backup.read_text()) == SAMPLE
        assert json.loads(path.read_text())["gripper"]["range_min"] == 2123

    def test_a_second_save_does_not_clobber_the_first_backup(self, tmp_path):
        path = write_file(tmp_path / "omx_arm.json", SAMPLE)
        first = calib.update_joint(SAMPLE, "gripper", range_min=2123)
        backup = calib.save_with_backup(path, first)
        second = calib.update_joint(first, "gripper", range_min=2200)
        calib.save_with_backup(path, second)
        assert json.loads(backup.read_text())["gripper"]["range_min"] == 0

    def test_result_reads_back(self, tmp_path):
        path = write_file(tmp_path / "omx_arm.json", SAMPLE)
        updated = calib.update_joint(SAMPLE, "gripper", range_max=2873)
        calib.save_with_backup(path, updated)
        assert calib.load(path) == updated


class TestLoad:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(calib.CalibrationError):
            calib.load(tmp_path / "nope.json")

    def test_broken_file_raises(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        with pytest.raises(calib.CalibrationError):
            calib.load(path)
