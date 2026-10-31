# omx-doctor

A command-line tool for the problems that stop a ROBOTIS OpenManipulator-X from
working: a gripper that keeps latching `Overload`, a travel range that resets
itself, a follower arm that will not match the leader.

Install it, find your symptom in the table, follow that section from the top.
Sections 1 to 3 work on any Dynamixel Protocol 2.0 arm over USB; sections 4 and
5 assume [LeRobot](https://github.com/huggingface/lerobot).

**Every number here is a placeholder.** Ranges, gains and current limits are
properties of an individual arm. Measure yours.

## Install

```bash
git clone https://github.com/yanwoo8/omx-doctor.git
cd omx-doctor
pip install -e .
omx-doctor status
```

The only dependency is `dynamixel-sdk`. If `status` reports no serial port, add
yourself to the `dialout` group, then log out and back in:

```bash
sudo usermod -aG dialout "$USER"
```

## Before you start

**Stop LeRobot first.** RS-485 allows one master. Two programs on one port
corrupt traffic for both.

**Know which settings survive a power cycle.** Most confusing symptoms come from
this split.

| Area | Registers | Survives power cycle | Writable when |
| --- | --- | --- | --- |
| EEPROM | travel limits, current limit, operating mode, homing offset | yes | torque off, no error latched |
| RAM | goal current, position gains, goal position | no | any time |

A motor silently ignores an out-of-range value and keeps the old one, so every
write this tool makes is read back and reported as `ok` or `REFUSED`.

## Find your symptom

| Symptom | Go to |
| --- | --- |
| I do not know what is wrong yet | [1. Diagnose](#1-diagnose) |
| Red LED, or the motor refuses commands | [1.3 Clear errors and release torque](#13-clear-errors-and-release-torque) |
| `Overload` (error 32) every time the gripper grips | [2. Overload on a gripper](#2-overload-on-a-gripper) |
| The motor gets hot and stops holding | [2. Overload on a gripper](#2-overload-on-a-gripper) |
| The joint stops short of where it should reach | [3. Travel range](#3-travel-range) |
| Settings revert on the next run | [2.5 Settings do not survive](#25-settings-do-not-survive-lerobot) |
| LeRobot asks to recalibrate every time | [3.3 Write the calibration file too](#33-write-the-calibration-file-too-lerobot) |
| The follower sits at a different angle than the leader | [4. Leader and follower](#4-leader-and-follower) |
| The follower gripper will not open all the way | [4.4 The gripper will not open far enough](#44-the-gripper-will-not-open-far-enough) |
| Nothing above, and I want the command list | [Command reference](#command-reference) |

---

## 1. Diagnose

### 1.1 Read every motor

```bash
omx-doctor status
```

```
/dev/ttyUSB0
  ID   MODEL   MODE                           POSITION   CURRENT     PWM   TEMP  ERROR
  11   1060    current-based position control     2047         3       6     31  clear
  16   1200    current-based position control     2338      -162    -885     38  32 (Overload)

Found 2 motor(s).

id 16: Overload: go to section 2.
```

No motor answers at all: check power, then the USB cable, then whether another
program holds the port. Nothing below works until one answers.

### 1.2 Decide where to go

`ERROR` is a bit field, so one number can mean several things. `status` decodes
it and names the section.

| Error | What it means | Go to |
| --- | --- | --- |
| 32 `Overload` | Held full drive output without reaching the goal | [2](#2-overload-on-a-gripper) |
| 4 `Overheating` | Temperature limit reached. Cut power and cool it | [2](#2-overload-on-a-gripper) |
| 8 `EncoderError` | Position sensor not reading cleanly | [4.3](#43-reassemble-the-joint) |
| 1 `InputVoltage` | Supply voltage out of band | check the adapter and wiring |
| 16 `ElectricalShock` | Short or stalled winding. Cut power | check the wiring |
| 0 | No error, but the motion is wrong | [4](#4-leader-and-follower) |

`Overload` does not mean the current exceeded `Current_Limit`. It fires when the
motor spends too long at full drive output (PWM pinned against `PWM_Limit`)
without the position catching up, and the current at that moment is often well
under the limit. That is why section 2 looks at PWM, not current.

### 1.3 Clear errors and release torque

An error stays latched until reboot or power cycle, and while latched the motor
refuses EEPROM writes.

```bash
omx-doctor reset
```

Reboots only the motors with an error, then releases torque on all of them so
you can move the arm by hand. Reboot also resets RAM, so reapply anything from
section 2 afterwards.

If `reset` finds nothing to clear and the arm is still unresponsive, the problem
is power or wiring.

---

## 2. Overload on a gripper

Work through 2.1 to 2.3 in order, stop when 2.6 passes. The gripper is the usual
victim because it pushes against something solid, but this applies to any joint.

### 2.1 Check whether PWM is pinned

```bash
omx-doctor watch 16 --seconds 20
```

Reads only. Drive the arm the way you normally reproduce the problem.

```
  T(S)      GOAL  POSITION   CURRENT     PWM   TEMP
 12.19      2336      2340        -8      -6     31
 12.79      2295      2338      -105    -363     31
 13.36      1999      2338      -162    -885     32
 13.76      1999      2338      -162    -885     32

PWM saturated (peak 885, limit 885). Start at section 2.2.
Temperature held steady (31 C to 32 C, peak 32 C).
Error status: 32 (Overload)
```

`GOAL` moving away from a frozen `POSITION` means the motor is being told to go
somewhere it cannot reach. `PWM` at the limit for more than a second or two is
what trips `Overload`. To drive it from the tool instead, add `--goal 2400`.

- **PWM saturated** → continue to 2.2.
- **PWM not saturated** but the error returns → 2.4, something mechanical.

### 2.2 Adjust the position gains

`Position_P_Gain` sets how much drive output the motor produces per unit of
position error. Higher reaches full output sooner and trips faster; lower is
gentler but holds position more loosely. No value is copyable, so measure.

```bash
omx-doctor gains 16 --p 800
omx-doctor watch 16 --seconds 20
```

Change one value, re-run `watch`, compare. Keep what lowers peak PWM without
leaving the joint too slack to hold its load. `--i` and `--d` work the same way;
0 is a reasonable start for both.

Gains are RAM, so a reboot restores the defaults. Safe to experiment with, and
it will not persist (see 2.5).

### 2.3 Lower Goal_Current

This is what actually stops `Overload` on a gripper. `Goal_Current` caps how
hard the motor may push, so it gives up before PWM pins.

```bash
omx-doctor current 16 100
```

Pick the value from what the joint drew in 2.1: the current reading at the moment
PWM pinned is the ceiling it was trying to reach, and `Goal_Current` needs to sit
somewhat below that. Step down until it stops tripping, then check it still
grips. Too low and it will not hold the load.

Two constraints the command checks for you:

- `Goal_Current` only limits force in current-based position control
  (`Operating_Mode` 5). `status` shows the mode.
- A value above `Current_Limit` is silently ignored, so it is refused rather
  than left looking successful.

### 2.4 When it only stalls in one spot

Free through most of the travel, failing in one place, means something is
binding. No register fixes it.

```bash
omx-doctor reset
```

Move the joint by hand and feel for a stiffer region. Then enable it and watch
the current through that spot (2.1): a free joint draws a small current
throughout, a binding one jumps in the same place every pass.

Check in this order: screws tightened unevenly so the housing pinches at one end
of travel, a cable that pulls at full extension, debris in the gear train.
Re-tightening evenly is the cheapest fix and it moves the usable travel, so
re-measure the range afterwards (section 3).

### 2.5 Settings do not survive (LeRobot)

2.2 and 2.3 are RAM writes, and LeRobot overwrites them in its own configuration
step on every connection. Make them part of what it writes:

```bash
omx-doctor patch-lerobot gripper \
  --mode 5 --current-limit 600 \
  --p 800 --i 0 --d 0 \
  --goal-current 100
```

This edits the installed LeRobot source, inserting your writes into the routine
it already runs. The insertion point is found by indentation structure, not by
matching line text, so it is not tied to one upstream version. Pass `--file` if
it cannot find the source.

Every inserted line is tagged `# omx-doctor`:

```bash
python -c "import lerobot.robots.omx_follower.omx_follower"   # check it imports
omx-doctor patch-lerobot gripper --revert                     # undo
```

Pass only the settings you want. EEPROM registers go where torque is off and
`Goal_Current` after, because that is what each area requires.

### 2.6 Confirm it holds

```bash
omx-doctor watch 16 --seconds 60
```

Run the task that used to fail, for longer than it used to take to fail. Fixed
when all three hold:

- `PWM not saturated`
- `Temperature held steady`, not climbing. Still warming means still working too
  hard, even without a trip.
- `Error status: clear`

Still pinning → lower `Goal_Current` further. Trips nothing but will not hold
the load → raise it a little.

---

## 3. Travel range

Do this when a joint stops short of where it physically reaches, after
reassembling or re-tightening anything, or when LeRobot has overwritten the
range with the full 0 to 4095 sweep.

### 3.1 Measure by hand

```bash
omx-doctor measure 16 --seconds 30
```

Torque is released first. Move the joint slowly to each mechanical stop (not to
where it feels like enough) while it records. `Ctrl-C` finishes early.

```
id 16 on /dev/ttyUSB0. Torque is off.
  position   2873   min   2123   max   2873

Range 2123 to 2873 (span 750, about 66 degrees).

To write this range to the motor:
  omx-doctor set-range 16 2123 2873
```

### 3.2 Write it to the motor

**On LeRobot, skip to 3.3 instead.** This command writes only the motor, which
is the state that gets your measurement erased.

```bash
omx-doctor set-range 16 2123 2873
```

```
  Min_Position_Limit      (52)  ->  2123     ok
  Max_Position_Limit      (48)  ->  2873     ok
Stored in EEPROM. It survives a power cycle.
```

`REFUSED` means the motor kept its old value, usually an out-of-range number or
torque still on. Fix and run again.

`--homing-offset` is available here, but it shifts the frame the limits are
expressed in, which invalidates the range you just measured. Leave it alone
unless you know you need it.

### 3.3 Write the calibration file too (LeRobot)

LeRobot keeps its own copy of the range and compares it against the EEPROM on
every connection. A mismatch triggers recalibration, and that overwrites the
range with 0 to 4095. So writing only the EEPROM guarantees the erasure.

```bash
omx-doctor sync-calib 16 gripper 2123 2873
```

Arguments are the motor ID, the joint name as LeRobot calls it, then the range.
The file is located by matching both the joint name and the motor ID, so leader
and follower profiles that share joint names are not confused.

```
Calibration file: ~/.cache/huggingface/lerobot/calibration/robots/my_omx/my_omx_arm.json
  now:  id 16, homing_offset 0, range 0 to 4095

id 16 on /dev/ttyUSB0
  Min_Position_Limit      (52)  ->  2123     ok
  Max_Position_Limit      (48)  ->  2873     ok

Calibration file updated. The original is at ...json.bak
  now:  id 16, homing_offset 0, range 2123 to 2873

EEPROM and the file agree, so LeRobot will not ask to recalibrate.
```

EEPROM is written first on purpose: if a write is refused the file is left
untouched, because the two disagreeing is worse than neither changing. The
original is kept as `.bak`.

If several calibration files match, the command stops instead of guessing. Move
the profiles you are not using and run again.

### 3.4 Confirm

```bash
omx-doctor status
```

Then connect once with LeRobot. It should not offer to recalibrate. If it still
does, the two copies still disagree: re-run `sync-calib` and read the `ok` lines.

---

## 4. Leader and follower

The follower holds a visibly different pose than the leader, or one joint is
consistently off while the rest track.

### 4.1 Compare positions

Hold both arms in the same pose first. Offsets measured against a moving arm are
noise.

```bash
omx-doctor compare 1:11 2:12 3:13 4:14 5:15 6:16
```

Each argument is `LEADER:FOLLOWER`. Use your own IDs; `status` lists them.

```
  PAIR               LEADER  FOLLOWER    OFFSET
  1:11                 2047      2051         4
  6:16                 2048      2140        92

1:11  Offset 4. Within the normal range.
6:16  Offset 92. The zero point has drifted. Measure the range and zero again in section 3.
```

### 4.2 Read the offsets

| Offset | What it is | What to do |
| --- | --- | --- |
| up to about 50 | normal play and sensor noise | nothing |
| tens to a few hundred | the zero point has drifted | [3](#3-travel-range) |
| several hundred or more | joint assembled at a different angle | [4.3](#43-reassemble-the-joint) |

4096 counts is one revolution, so divide by about 11.4 for degrees. A small
offset is not worth chasing: teleoperation absorbs it.

### 4.3 Reassemble the joint

A large offset means the output horn was bolted on at a different rotation on
one arm. No register fixes this, because the motor's zero and the linkage's zero
really are in different places.

Release torque, unbolt, rotate the horn to match the other arm, bolt it back.
The horn mounts at discrete positions, so get within one step rather than
exactly on zero. Then re-measure the range (section 3), because the mechanical
stops moved.

### 4.4 The gripper will not open far enough

Two causes, in this order.

**The travel range.** If `Max_Position_Limit` is below where the gripper
physically opens to, the motor stops at the limit as instructed. Measure and
write it (section 3).

**LeRobot's own cap.** `gripper_open_pos` caps the goal sent to the follower, and
it applies separately to teleoperation and recording, so passing it to one and
not the other reproduces this exactly:

```bash
lerobot-teleoperate  ... --teleop.gripper_open_pos=95
lerobot-record       ... --teleop.gripper_open_pos=95
```

---

## 5. Other things that catch people

**Two programs on one port.** Any mix of LeRobot, this tool and a stray Python
shell corrupts traffic for all of them, and it looks like random communication
failures. Stop everything else first.

**Device names move.** `/dev/ttyUSB0` and `ttyUSB1` swap with plug order, so a
port written into a script eventually points at the wrong arm. Every command
here finds motors by ID across all ports instead.

**Rebooting resets RAM.** After `reset`, or anything else that reboots a motor,
reapply the gains and goal current from section 2.

**An out-of-range write looks like success.** Read back anything you write.

**Telemetry can cost more than inference.** If LeRobot's loop runs slow, suspect
the live visualization before the model: `--display_data=false`.

---

## Command reference

| Command | What it does | Section |
| --- | --- | --- |
| `status` | Find every motor, print position, current, PWM, temperature, errors | [1.1](#11-read-every-motor) |
| `reset` | Reboot motors with a latched error, release torque on all | [1.3](#13-clear-errors-and-release-torque) |
| `watch ID` | Log PWM and current, report whether PWM pinned | [2.1](#21-check-whether-pwm-is-pinned) |
| `gains ID --p --i --d` | Write the position gains, verified | [2.2](#22-adjust-the-position-gains) |
| `current ID VALUE` | Write `Goal_Current`, verified | [2.3](#23-lower-goal_current) |
| `patch-lerobot JOINT` | Make LeRobot reapply your settings on every connect | [2.5](#25-settings-do-not-survive-lerobot) |
| `measure ID` | Release torque and record the travel range | [3.1](#31-measure-by-hand) |
| `set-range ID MIN MAX` | Write the range to EEPROM, verified | [3.2](#32-write-it-to-the-motor) |
| `sync-calib ID JOINT MIN MAX` | Write the range to EEPROM and the calibration file | [3.3](#33-write-the-calibration-file-too-lerobot) |
| `compare L:F ...` | Compare leader and follower positions | [4.1](#41-compare-positions) |

Every command takes `--help`. `status` and `reset` take `--ids`; `watch` and
`measure` take `--seconds`. Exit status is 0 when nothing needs your attention
and 1 when something does, so these compose into scripts.

## Doing it without this tool

Three patterns cover every command here, worth knowing for when the tool is not
installed.

Find a motor by ID rather than by port name, because device names move:

```python
from dynamixel_sdk import PacketHandler, PortHandler, COMM_SUCCESS
import glob

ph = PacketHandler(2.0)
for device in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")):
    port = PortHandler(device)
    if port.openPort() and port.setBaudRate(1_000_000):
        if ph.ping(port, MOTOR_ID)[1] == COMM_SUCCESS:
            break
        port.closePort()
```

Read back every write, because an out-of-range value is ignored silently:

```python
ph.write2ByteTxRx(port, MOTOR_ID, address, value)
readback, _, _ = ph.read2ByteTxRx(port, MOTOR_ID, address)
assert readback == value
```

Clear the error and release torque before any EEPROM write, or it is refused:

```python
if ph.read1ByteTxRx(port, MOTOR_ID, 70)[0]:   # Hardware_Error_Status
    ph.reboot(port, MOTOR_ID)
    time.sleep(1.5)
ph.write1ByteTxRx(port, MOTOR_ID, 64, 0)      # Torque_Enable = 0
```

Addresses are in `src/omx_doctor/registers.py`; the control table is in the
[Dynamixel e-Manual](https://emanual.robotis.com/docs/en/dxl/x/xm430-w350/).

## Development

```bash
pip install -e ".[dev]"
pytest
```

```
src/omx_doctor/
  registers.py   control table addresses and error bits (data only)
  decode.py      bit decoding, sign conversion, verdicts (pure)
  patch.py       where to insert settings in LeRobot's source (pure)
  calib.py       finding and updating calibration files
  bus.py         port discovery, verified reads and writes (hardware I/O)
  commands.py    the subcommands
  cli.py         argument parsing
```

Hardware I/O is confined to `bus.py` and everything else is pure, so the test
suite covers it without a robot attached. That split is not a style choice: this
tool is published for arms we cannot test against, so the parts that can be
verified in isolation are kept verifiable.

Reports from other arms are welcome, especially where a verdict threshold in
`decode.py` reads your hardware wrong.

`trouble_shooting_log/` holds the session notes this came out of: what was
tried, what the measurements were, which attempts failed. It is a record of one
arm, not guidance, and nothing in it should be copied as a setting.

## Credits

The methods in this tool were worked out jointly on one OpenManipulator-X
during a Physical AI course.

- [Yanwoo Kim](https://github.com/yanwoo8)
- [Yumin Kim](https://github.com/Yu-billie)

## License

Apache-2.0. See [LICENSE](LICENSE).
