# Leader and follower did not line up

October 2026. Leader ids 1 to 6, follower ids 11 to 16.

## A joint assembled at the wrong angle

Comparing the two arms in the same pose, one pair was far off while the rest
tracked within normal play: follower id 14 against leader id 4.

The offset was large enough that no zero-point adjustment would account for it.
The output horn had been bolted on at a different rotation on the follower than
on the leader.

Fix: released torque, unbolted the joint, rotated it 180 degrees, bolted it
back. That left a residual offset of 92 counts, about 8 degrees.

## The residual 92 counts was left alone

The horn mounts at discrete positions, so landing exactly on zero was not
possible. Two options: leave the 92 counts, or write a `Homing_Offset` to cancel
it.

It was left uncorrected. Teleoperation absorbed it without visible trouble, and
50 episodes were recorded afterwards with no problem traceable to it. Writing a
`Homing_Offset` would have added a second value that could be wrong, in a frame
whose sign convention had not been verified on this hardware.

Recorded because the decision matters for reading the rest of this log: no
`Homing_Offset` was ever computed to cancel an offset here. The thresholds in
`decode.py` first came from this one comparison, as a judgement about wording
rather than a measurement.

Update for 0.1.1: later sessions showed that offsets of 40 to
105 counts teleoperate fine, so the normal band was raised from 50 to 150
counts. The residual 92 counts above now reads as normal, which matches what
was observed. `compare` also warns when a reading sits near 0 or 4095, after a
pair at 3947 and 7 tripped `Overload` while looking aligned.

## The follower gripper would not open all the way

Separate symptom, same session. The leader gripper opened fully, the follower
opened part way and stopped.

Two causes, both present:

1. The follower's `Max_Position_Limit` was below where the gripper physically
   opened to, so the motor stopped at the limit as instructed. Fixed by
   measuring and writing the range (see
   [travel-range-and-calibration.md](2026-10-travel-range-and-calibration.md)).

2. LeRobot's own cap. `gripper_open_pos` defaults to 60.0 and caps the goal sent
   to the follower. It applies separately to teleoperation and to recording, so
   passing it to one and not the other reproduces the symptom exactly. It had to
   go on both:

```
lerobot-teleoperate  ... --teleop.gripper_open_pos=95
lerobot-record       ... --teleop.gripper_open_pos=95
```

95 was what suited this arm after the range was corrected.

## Comparing positions at all

Both arms have to be held in the same pose before the offsets mean anything. A
leader at rest compared against a follower mid-motion produces offsets that are
pure noise, which wasted some time early on.

Positions were read by pinging each ID across every serial port rather than by
naming ports, because `/dev/ttyUSB0` and `/dev/ttyUSB1` swapped between the two
arms depending on plug order. This is why `compare` takes ID pairs and no port
argument.
