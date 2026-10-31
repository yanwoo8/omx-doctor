# Overload on the follower gripper

October 2026. Follower gripper, id 16, model 1200, `Operating_Mode` 5.

## Symptom

During teleoperated pick-and-place recording, the follower gripper latched
`Hardware_Error_Status` 32 (`Overload`) every time it closed on the object.
Once latched, the motor stopped responding until it was rebooted, which ended
the episode.

## First hypothesis, wrong

The assumption was that the current had exceeded `Current_Limit` (38), which was
600. It had not. At the moment the error fired the current reading was 162,
roughly a quarter of the limit.

What the 40 ms log showed:

```
t=12.19  goal 2336  pos 2340  cur   -8   pwm    -6     normal
t=12.79  goal 2295  pos 2338  cur -105   pwm  -363     contact with the object
t=13.36  goal 1999  pos 2338  cur -162   pwm  -885     PWM pinned at the limit
         ... pwm -885, cur -162, pos 2338 all frozen for about 2.5 s ...
t=15.82                                  err 32
```

`PWM_Limit` (36) was 885, so `pwm -885` is full drive output. Position stopped
changing while the goal kept moving away from it, and the error arrived about
2.5 seconds later.

Conclusion: on this motor `Overload` is triggered by sustained saturation of the
drive output, not by current crossing `Current_Limit`. The current never got
near the limit because the gripper was pressed against a solid object and the
winding could not draw more at that rotor position. Measured current ceiling in
that state was about 160 regardless of what the limits were set to.

This is why `watch` reports a PWM verdict rather than a current one.

## Attempts that did not work

| Attempt | Result |
| --- | --- |
| `Goal_Current` 300 | Stalled around position 2100, current stayed at or below 161, still tripped |
| `Goal_Current` 500 | Same as 300. Raising the ceiling changed nothing because the motor was not reaching it |
| `Position_P_Gain` 1500 | Worse. Reached full output sooner and tripped faster |
| Raising `Current_Limit` | No effect, consistent with the diagnosis above |

The pattern: anything that raised the ceiling was irrelevant, because the
problem was the motor refusing to give up, not the ceiling being too low.

## What worked

Lowering `Goal_Current` (102) until the motor stopped pushing before PWM pinned.

Defaults before any change were `Position_P_Gain` 250, `Position_I_Gain` 0,
`Position_D_Gain` 600.

Final values on id 16:

| Register | Address | Value | Area |
| --- | --- | --- | --- |
| `Operating_Mode` | 11 | 5 | EEPROM |
| `Current_Limit` | 38 | 600 | EEPROM |
| `Goal_Current` | 102 | 100 | RAM |
| `Position_P_Gain` | 84 | 800 | RAM |
| `Position_I_Gain` | 82 | 0 | RAM |
| `Position_D_Gain` | 80 | 0 | RAM |

After the change, with the gripper closed on the same object:

```
t=43.99  goal 2333  pos 2300  cur  101   pwm  285
```

72 seconds with no error, temperature 29 C to 32 C. Peak PWM 285 against a limit
of 885, so roughly a third of full output where it had previously been pinned at
all of it. The gripper still held the object.

`Goal_Current` 100 against a measured ceiling of about 160 is roughly 60 percent
of what the motor could reach in that state. That is one data point on one
joint, not a ratio worth generalizing.

## The mechanical part

Before settling on the current limit, one spot in the travel was found to be
binding. Released torque and moved the gripper by hand: most of the travel was
free, one region was noticeably stiffer.

Current readings confirmed it. Free travel drew 3 to 18 mA. Passing through the
stiff region drew over 150 mA in the same place on every pass.

The cause was uneven screw tension in the gripper housing. Loosening and
re-tightening evenly widened the open end of the travel from 2573 to 2902, a
gain of 330 counts, and removed the stiff region. The travel range had to be
re-measured afterwards.

No register would have fixed this, and with it in place no current setting would
have been a fair test.

## Why the settings kept reverting

`Goal_Current` and the position gains live in RAM. LeRobot runs its own
configuration routine on every connection and overwrites them, so the gripper
behaved for one session and reverted on the next. Rebooting a motor to clear an
error has the same effect.

The fix was to insert the writes into LeRobot's follower configuration routine:
`Operating_Mode` and `Current_Limit` inside the `with self.bus.torque_disabled():`
block, since EEPROM writes are refused while torque is on, and `Goal_Current`
after the block.

Edits were made with `sed` against the installed source and verified with
`python -c "import lerobot.robots.omx_follower.omx_follower"`. No backup file was
taken; `git diff` and `git checkout` in the LeRobot checkout served as the undo.
This is what `patch-lerobot` automates, except that it locates the insertion
point by indentation structure instead of by matching line text.

## A boost policy that was tried and not adopted

One further idea was tested: hold `Goal_Current` low while stationary and raise
it briefly while the gripper is moving, so it has force to travel with but not
enough to push against a stall.

Implemented as a hook called with each goal position, with `GC_HOLD` 100,
`GC_BOOST` 200, a 2.0 count deadband, a 1.0 count progress threshold and a 1.0 s
timeout. It read `Present_Position`, compared it to the goal, raised the current
when a new direction of travel started, and dropped it back when either the
goal was reached or no progress was made within the timeout.

Validated over 102 seconds with no error. It was not adopted, because
`Goal_Current` 100 alone already solved the problem and this added state to a
hot loop for no measured benefit. Recorded here because it worked, not because
it is recommended.

## Open questions

- Whether `Overload` on this motor is triggered by a fixed saturation duration
  or by an accumulated load integral. Only the roughly 2.5 s figure was
  observed, in one condition, once.
- Why peak current plateaued near 160 in the stalled state. Most likely the
  rotor position, but this was not investigated.
