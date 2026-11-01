"""Run each subcommand against the simulated bus in conftest.py.

These cover the paths that need a motor: finding it, reading its state,
and writing to it. No robot or serial port is needed.
"""

import json

from conftest import FakeMotor
from omx_doctor import calib, cli
from omx_doctor import registers as reg

OVERLOAD = 1 << 5


def healthy_follower(arm, device="/dev/ttyUSB0"):
    return arm.add(device, *(FakeMotor(i) for i in range(11, 17)))


class TestStatus:
    def test_healthy_arm(self, arm, capsys):
        healthy_follower(arm)
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "Found 6 motor(s)." in out
        assert "No errors." in out

    def test_reports_a_latched_overload(self, arm, capsys):
        # The session on 2026-10-27: the follower gripper read
        # Hardware_Error_Status 32, and every packet carried the Alert bit.
        healthy_follower(arm)
        arm.motor(16).set(reg.HARDWARE_ERROR, OVERLOAD)
        assert cli.main(["status"]) == 1
        out = capsys.readouterr().out
        assert "id 16: Overload" in out
        assert "No errors." not in out

    def test_other_motors_still_read_while_one_has_an_error(self, arm, capsys):
        healthy_follower(arm)
        arm.motor(16).set(reg.HARDWARE_ERROR, OVERLOAD)
        cli.main(["status"])
        out = capsys.readouterr().out
        gripper_row = next(line for line in out.splitlines() if line.strip().startswith("16 "))
        assert "read failed" not in gripper_row

    def test_signed_values_are_shown_signed(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, present_current=-120, present_pwm=-300))
        cli.main(["status"])
        out = capsys.readouterr().out
        assert "-120" in out
        assert "-300" in out

    def test_no_port(self, arm, capsys):
        assert cli.main(["status"]) == 1
        assert "No serial port" in capsys.readouterr().err

    def test_port_but_no_motor(self, arm, capsys):
        arm.add("/dev/ttyUSB0")
        assert cli.main(["status"]) == 1
        assert "No motor answered" in capsys.readouterr().err


class TestReset:
    def test_reboots_only_the_motor_with_an_error(self, arm):
        healthy_follower(arm)
        arm.motor(16).set(reg.HARDWARE_ERROR, OVERLOAD)
        assert cli.main(["reset"]) == 0
        assert arm.motor(16).reboots == 1
        assert arm.motor(11).reboots == 0
        assert arm.motor(16).get(reg.HARDWARE_ERROR) == 0

    def test_disables_torque(self, arm):
        arm.add("/dev/ttyUSB0", FakeMotor(11, torque_enable=1))
        assert cli.main(["reset"]) == 0
        assert arm.motor(11).get(reg.TORQUE_ENABLE) == 0

    def test_a_failed_reboot_is_reported_not_raised(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, hardware_error=OVERLOAD))
        arm.motor(16).reboot_fails = True
        assert cli.main(["reset"]) == 1


class TestGains:
    def test_writes_and_confirms(self, arm, capsys):
        healthy_follower(arm)
        assert cli.main(["gains", "16", "--p", "640", "--d", "3600"]) == 0
        assert arm.motor(16).get(reg.POSITION_P_GAIN) == 640
        assert arm.motor(16).get(reg.POSITION_D_GAIN) == 3600

    def test_out_of_range_is_reported(self, arm, capsys):
        healthy_follower(arm)
        assert cli.main(["gains", "16", "--p", "20000"]) == 1
        assert "REFUSED" in capsys.readouterr().out
        assert arm.motor(16).get(reg.POSITION_P_GAIN) == 800

    def test_works_while_an_error_is_latched(self, arm):
        healthy_follower(arm)
        arm.motor(16).set(reg.HARDWARE_ERROR, OVERLOAD)
        assert cli.main(["gains", "16", "--p", "640"]) == 0

    def test_missing_motor(self, arm, capsys):
        healthy_follower(arm)
        assert cli.main(["gains", "99", "--p", "640"]) == 1
        assert "Could not find id 99" in capsys.readouterr().err


class TestCurrent:
    def test_writes_in_mode_5(self, arm):
        arm.add("/dev/ttyUSB0", FakeMotor(16, operating_mode=5, current_limit=600))
        assert cli.main(["current", "16", "300"]) == 0
        assert arm.motor(16).get(reg.GOAL_CURRENT) == 300

    def test_above_the_limit_is_rejected_before_writing(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, operating_mode=5, current_limit=600))
        assert cli.main(["current", "16", "700"]) == 1
        assert "outside -600 to 600" in capsys.readouterr().err

    def test_below_minus_the_limit_is_rejected_before_writing(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, operating_mode=5, current_limit=600))
        assert cli.main(["current", "16", "-700"]) == 1
        assert "Current_Limit" in capsys.readouterr().err


class TestSetRange:
    def test_writes_eeprom_with_torque_on(self, arm):
        arm.add("/dev/ttyUSB0", FakeMotor(16, torque_enable=1))
        assert cli.main(["set-range", "16", "2123", "2873"]) == 0
        assert arm.motor(16).get(reg.MIN_POSITION_LIMIT) == 2123
        assert arm.motor(16).get(reg.MAX_POSITION_LIMIT) == 2873
        assert arm.motor(16).get(reg.TORQUE_ENABLE) == 0

    def test_negative_homing_offset(self, arm):
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        assert cli.main(["set-range", "16", "100", "3000", "--homing-offset", "-512"]) == 0
        assert arm.motor(16).get(reg.HOMING_OFFSET) == -512

    def test_reboots_first_when_an_error_is_latched(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, hardware_error=OVERLOAD))
        assert cli.main(["set-range", "16", "2123", "2873"]) == 0
        assert arm.motor(16).reboots == 1
        assert "rebooted" in capsys.readouterr().out

    def test_a_failed_reboot_is_reported_not_raised(self, arm):
        arm.add("/dev/ttyUSB0", FakeMotor(16, hardware_error=OVERLOAD))
        arm.motor(16).reboot_fails = True
        assert cli.main(["set-range", "16", "2123", "2873"]) == 1

    def test_min_above_max(self, arm, capsys):
        assert cli.main(["set-range", "16", "3000", "1000"]) == 1

    def test_a_range_that_would_lock_the_joint_is_refused(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        assert cli.main(["set-range", "16", "2047", "2049"]) == 1
        assert "lock the joint" in capsys.readouterr().err
        assert arm.motor(16).get(reg.MIN_POSITION_LIMIT) == 0


class TestSyncCalib:
    def write_calibration(self, tmp_path, monkeypatch, motor_id=16):
        root = tmp_path / "calibration"
        path = root / "robots" / "omx_follower" / "follower.json"
        path.parent.mkdir(parents=True)
        data = {
            "gripper": {
                "id": motor_id,
                "drive_mode": 0,
                "homing_offset": 0,
                "range_min": 0,
                "range_max": 4095,
            }
        }
        path.write_text(json.dumps(data))
        monkeypatch.setattr(calib, "calibration_root", lambda home=None: root)
        return path

    def test_writes_both(self, arm, tmp_path, monkeypatch):
        path = self.write_calibration(tmp_path, monkeypatch)
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        assert cli.main(["sync-calib", "16", "gripper", "2123", "2873"]) == 0
        assert arm.motor(16).get(reg.MIN_POSITION_LIMIT) == 2123
        saved = json.loads(path.read_text())["gripper"]
        assert (saved["range_min"], saved["range_max"]) == (2123, 2873)

    def test_file_untouched_when_eeprom_refuses(self, arm, tmp_path, monkeypatch):
        path = self.write_calibration(tmp_path, monkeypatch)
        before = path.read_text()
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        assert cli.main(["sync-calib", "16", "gripper", "2123", "5000"]) == 1
        assert path.read_text() == before

    def test_file_untouched_when_the_motor_is_missing(self, arm, tmp_path, monkeypatch):
        path = self.write_calibration(tmp_path, monkeypatch)
        before = path.read_text()
        arm.add("/dev/ttyUSB0")
        assert cli.main(["sync-calib", "16", "gripper", "2123", "2873"]) == 1
        assert path.read_text() == before


class TestCompare:
    def test_pairs_across_two_ports(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(6, present_position=2000))
        arm.add("/dev/ttyUSB1", FakeMotor(16, present_position=2030))
        assert cli.main(["compare", "6:16"]) == 0
        assert "30" in capsys.readouterr().out

    def test_large_offset(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(6, present_position=1000))
        arm.add("/dev/ttyUSB1", FakeMotor(16, present_position=2030))
        assert cli.main(["compare", "6:16"]) == 1

    def test_missing_id(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(6))
        assert cli.main(["compare", "6:16"]) == 1
        assert "id 16 not found" in capsys.readouterr().out

    def test_bad_pair(self, arm, capsys):
        assert cli.main(["compare", "6-16"]) == 1

    def leader_and_follower(self, arm, leader, follower):
        arm.add("/dev/ttyACM0", *(FakeMotor(i, present_position=p) for i, p in leader.items()))
        arm.add("/dev/ttyACM1", *(FakeMotor(i, present_position=p) for i, p in follower.items()))

    def test_the_arm_that_teleoperated_is_normal(self, arm, capsys):
        # Readings from 2026-10-26 right before teleoperation first worked.
        self.leader_and_follower(
            arm,
            {1: 2039, 2: 649, 3: 2178, 4: 1030, 5: 2024},
            {11: 1999, 12: 748, 13: 2122, 14: 1035, 15: 1957},
        )
        assert cli.main(["compare", "1:11", "2:12", "3:13", "4:14", "5:15"]) == 0
        out = capsys.readouterr().out
        assert "drifted" not in out
        assert "boundary" not in out

    def test_a_misassembled_elbow(self, arm, capsys):
        self.leader_and_follower(arm, {3: 2171}, {13: 2636})
        assert cli.main(["compare", "3:13"]) == 1
        assert "assembled" in capsys.readouterr().out

    def test_a_wrist_on_the_encoder_boundary(self, arm, capsys):
        # Leader 3947 and follower 7: the pair that lit the follower red.
        self.leader_and_follower(arm, {4: 3947}, {14: 7})
        assert cli.main(["compare", "4:14"]) == 1
        assert "boundary" in capsys.readouterr().out


class TestWatch:
    def test_read_only_logging(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, present_pwm=-880))
        assert cli.main(["watch", "16", "--seconds", "0.05"]) == 0
        out = capsys.readouterr().out
        assert "PWM saturated" in out
        assert arm.motor(16).get(reg.TORQUE_ENABLE) == 0

    def test_goal_enables_torque_and_moves(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        assert cli.main(["watch", "16", "--goal", "2500", "--seconds", "0.05"]) == 0
        assert arm.motor(16).get(reg.GOAL_POSITION) == 2500

    def test_reports_a_latched_error(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, hardware_error=OVERLOAD))
        assert cli.main(["watch", "16", "--seconds", "0.05"]) == 1
        assert "Overload" in capsys.readouterr().out


class TestMeasure:
    def test_disables_torque_and_reports(self, arm, capsys):
        arm.add("/dev/ttyUSB0", FakeMotor(16, torque_enable=1))
        cli.main(["measure", "16", "--seconds", "0.05"])
        assert arm.motor(16).get(reg.TORQUE_ENABLE) == 0

    def measure(self, arm, positions):
        arm.add("/dev/ttyUSB0", FakeMotor(16))
        arm.motor(16).positions = list(positions)
        return cli.main(["measure", "16", "--seconds", "0.05"])

    def test_a_joint_that_never_moved_is_not_offered_to_set_range(self, arm, capsys):
        assert self.measure(arm, [2048]) == 1
        out = capsys.readouterr().out
        assert "did not move" in out
        assert "minimum is above the maximum" not in out
        assert "set-range" not in out

    def test_sensor_noise_is_not_offered_to_set_range(self, arm, capsys):
        assert self.measure(arm, [2048, 2049, 2047, 2048]) == 1
        out = capsys.readouterr().out
        assert "all the way" in out
        assert "set-range" not in out

    def test_a_range_across_the_boundary_points_to_reassembly(self, arm, capsys):
        assert self.measure(arm, [4045, 4090, -6, -51]) == 1
        out = capsys.readouterr().out
        assert "4.3" in out
        assert "set-range" not in out

    def test_a_good_range_is_offered_to_set_range(self, arm, capsys):
        assert self.measure(arm, [2123, 2500, 2873]) == 0
        assert "set-range 16 2123 2873" in capsys.readouterr().out
