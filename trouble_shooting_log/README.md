# Troubleshooting log

Session notes from the run this tool came out of: one OpenManipulator-X driven
by LeRobot during a Physical AI course, used for teleoperated pick-and-place
recording.

These are records, not guidance. They say what was observed on one particular
arm, which attempts failed, and what the final values were. The arm has since
been returned, so nothing here can be re-measured or corrected.

**Do not copy any number here into your robot.** Travel ranges, gains and
current limits are properties of an individual arm. The [README](../README.md)
is the part meant to be followed.

## Files

| File | Covers |
| --- | --- |
| [gripper-overload.md](2026-10-gripper-overload.md) | `Overload` on the follower gripper: what actually triggers it, four attempts that failed, the one that worked |
| [travel-range-and-calibration.md](2026-10-travel-range-and-calibration.md) | Why writing the EEPROM alone got erased, and the order that fixed it |
| [leader-follower-mismatch.md](2026-10-leader-follower-mismatch.md) | A joint assembled at the wrong angle, and an offset deliberately left uncorrected |
| [recording-loop-performance.md](2026-10-recording-loop-performance.md) | Where the recording loop time went, and the camera settings that worked |

## The arm

| | IDs | Models |
| --- | --- | --- |
| Leader | 1 to 6 | 1200 (ids 1 to 5), 1190 (id 6) |
| Follower | 11 to 16 | 1060 (ids 11 to 13), 1200 (ids 14 to 16) |

Protocol 2.0 at 1 Mbps. Follower gripper (id 16) in `Operating_Mode` 5,
current-based position control. Host was a GPU-less VM for recording.

## What is not written down

Three things were considered and not done, so there is no record of them either
way. They are listed here so the gaps are visible rather than implied:

- `Homing_Offset` was never computed to cancel a leader/follower offset. It was
  only written as part of a calibration set.
- The sign convention of `Homing_Offset` relative to the position limits was
  never confirmed on hardware.
- Success rates for the trained policies were never measured under a fixed
  protocol, so the rollout impressions recorded elsewhere are not comparable
  numbers.
