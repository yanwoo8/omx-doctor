# Travel range kept getting erased

October 2026. Follower gripper id 16 and leader gripper id 6.

## Symptom

The gripper travel range was measured by hand and written to the motor's
EEPROM. It verified on read-back. On the next LeRobot connection the range was
back to 0 to 4095 and the gripper was driving past its mechanical stops again.

## Cause

LeRobot keeps its own copy of the calibration in a JSON file:

```
~/.cache/huggingface/lerobot/calibration/{robots,teleoperators}/<id>/<id>_arm.json
```

Each joint entry holds `id`, `drive_mode`, `homing_offset`, `range_min` and
`range_max`.

On connection, `is_calibrated` compares that file against the motor's EEPROM.
When they disagree it triggers `calibrate()`, and `calibrate()` writes
`range_min = 0` and `range_max = 4095` to both the motor and the file.

So writing the EEPROM alone did not just fail to persist. It guaranteed a
mismatch, which guaranteed the recalibration that erased it.

## Fix

Write both, with the same values, EEPROM first. If any EEPROM write is refused,
leave the file alone, because the two disagreeing is the state that causes the
erasure.

Measured and applied:

| Joint | Motor id | `Min_Position_Limit` (52) | `Max_Position_Limit` (48) | `Homing_Offset` (20) |
| --- | --- | --- | --- | --- |
| Follower gripper | 16 | 2123 | 2873 | 0 |
| Leader gripper | 6 | 917 | 2577 | 100 |

The leader's `Homing_Offset` of 100 was already there and was written back
unchanged as part of the set. It was not calculated, and nothing was ever
corrected by changing it.

The JSON was copied to `.bak` before each edit. After this, LeRobot connected
without offering to recalibrate and the range held across power cycles.

This is what `sync-calib` does, including locating the file by matching both the
joint name and the motor ID, which is what keeps the leader and follower
profiles apart when they use the same joint names.

## Things learned about EEPROM writes

- A write is refused unless `Torque_Enable` (64) is 0 **and**
  `Hardware_Error_Status` (70) is 0. A latched error from an earlier problem is
  enough to make every subsequent write silently fail.
- An out-of-range value is not an error. The motor ignores it and keeps the old
  value, and the write call returns success. Reading back is the only way to
  know what happened. Every write in this tool reads back for that reason.
- `reboot()` clears the latched error and also resets RAM, so gains and goal
  current have to be reapplied afterwards.
- The range had to be re-measured after the gripper screws were re-tightened
  (see [gripper-overload.md](2026-10-gripper-overload.md)), because that moved
  the mechanical stops by 330 counts.

## Not confirmed

The coordinate relationship between `Homing_Offset` and the position limits was
never tested on hardware: whether a non-zero offset shifts the frame the limits
are expressed in, and in which direction. Since the offset was only ever written
as part of a full set, this never had to be resolved. Treat any claim about it
as unverified.
