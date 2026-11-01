"""Subcommand implementations.

Each function takes parsed arguments and returns an exit code: 0 when
nothing needs your attention, 1 when something does.
"""

import importlib.util
import pathlib
import sys
import time

from . import calib, patch, registers as reg
from .bus import BusError, find_motor, open_all
from .decode import (
    DIFF_SMALL,
    MIN_SPAN,
    boundary_verdict,
    diff_verdict,
    format_error,
    format_mode,
    pwm_verdict,
    range_usable,
    range_verdict,
    temperature_verdict,
    triage,
)

POLL_INTERVAL = 0.04  # 40 ms
RAM_NOTE = (
    "This is a RAM setting. It is lost on power cycle, and LeRobot "
    "overwrites it on the next connection. See `patch-lerobot` to keep it."
)


def _fail(message):
    print("error: %s" % message, file=sys.stderr)
    return 1


# 1. status ----------------------------------------------------------


def status(args):
    """Find every motor and print its state."""
    buses = open_all()
    if not buses:
        return _fail(
            "No serial port could be opened. Check that the USB cable is "
            "plugged in and that your user is in the dialout group."
        )

    total = 0
    problems = []
    try:
        for bus in buses:
            found = bus.scan(args.ids)
            if not found:
                continue
            print("%s" % bus.device)
            print(
                "  %-4s %-7s %-30s %9s %9s %7s %6s  %s"
                % (
                    "ID",
                    "MODEL",
                    "MODE",
                    "POSITION",
                    "CURRENT",
                    "PWM",
                    "TEMP",
                    "ERROR",
                )
            )
            for motor_id, model in sorted(found.items()):
                total += 1
                error = bus.read(motor_id, reg.HARDWARE_ERROR)
                print(
                    "  %-4d %-7s %-30s %9s %9s %7s %6s  %s"
                    % (
                        motor_id,
                        model,
                        format_mode(bus.read(motor_id, reg.OPERATING_MODE)),
                        bus.read(motor_id, reg.PRESENT_POSITION),
                        bus.read(motor_id, reg.PRESENT_CURRENT),
                        bus.read(motor_id, reg.PRESENT_PWM),
                        bus.read(motor_id, reg.PRESENT_TEMPERATURE),
                        format_error(error),
                    )
                )
                if error:
                    problems.append((motor_id, error))
            print()
    finally:
        for bus in buses:
            bus.close()

    if not total:
        return _fail(
            "No motor answered. Check that the arm is powered and that no "
            "other program is holding the port."
        )

    print("Found %d motor(s)." % total)
    if not problems:
        print("No errors.")
        return 0
    print()
    for motor_id, error in problems:
        print("id %d: %s" % (motor_id, triage(error)))
    return 1


# 2. reset -----------------------------------------------------------


def reset(args):
    """Reboot only the motors with a latched error, then disable all torque."""
    buses = open_all()
    if not buses:
        return _fail("No serial port could be opened.")

    cleared = 0
    total = 0
    try:
        for bus in buses:
            for motor_id in sorted(bus.scan(args.ids)):
                total += 1
                error = bus.read(motor_id, reg.HARDWARE_ERROR)
                if error:
                    print(
                        "id %d: error %s, rebooting." % (motor_id, format_error(error))
                    )
                    bus.reboot(motor_id)
                    cleared += 1
                if not bus.torque_off(motor_id):
                    print("id %d: could not disable torque." % motor_id)
    finally:
        for bus in buses:
            bus.close()

    if not total:
        return _fail("No motor answered.")
    print(
        "Handled %d motor(s), rebooted %d. Torque is off on all of them."
        % (total, cleared)
    )
    return 0


# 3. watch -----------------------------------------------------------


def watch(args):
    """Log PWM and current to see whether PWM pins against its limit.

    Read only by default. Pass --goal to drive the motor yourself.
    """
    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        pwm_limit = bus.read(args.id, reg.PWM_LIMIT)
        print("id %d on %s, PWM_Limit %s" % (args.id, bus.device, pwm_limit))

        if args.goal is not None:
            bus.write(args.id, reg.TORQUE_ENABLE, 1)
            result = bus.write(args.id, reg.GOAL_POSITION, args.goal)
            print(result.line("Goal_Position"))
            if not result:
                return _fail("The goal position was refused.")
        else:
            print("Reading only. Drive the arm as you normally would.")
        print()
        print(
            "  %7s %9s %9s %9s %7s %6s"
            % ("T(S)", "GOAL", "POSITION", "CURRENT", "PWM", "TEMP")
        )

        peak_pwm = 0
        temperatures = []
        start = time.perf_counter()
        while True:
            now = time.perf_counter() - start
            if now > args.seconds:
                break
            goal = bus.read(args.id, reg.GOAL_POSITION)
            position = bus.read(args.id, reg.PRESENT_POSITION)
            current = bus.read(args.id, reg.PRESENT_CURRENT)
            pwm = bus.read(args.id, reg.PRESENT_PWM)
            temperature = bus.read(args.id, reg.PRESENT_TEMPERATURE)
            if pwm is not None and abs(pwm) > abs(peak_pwm):
                peak_pwm = pwm
            if temperature is not None:
                temperatures.append(temperature)
            print(
                "  %7.2f %9s %9s %9s %7s %6s"
                % (now, goal, position, current, pwm, temperature)
            )
            time.sleep(POLL_INTERVAL)

        error = bus.read(args.id, reg.HARDWARE_ERROR)
        print()
        print(pwm_verdict(peak_pwm, pwm_limit))
        print(temperature_verdict(temperatures))
        print("Error status: %s" % format_error(error))
        return 1 if error else 0
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        bus.close()


# 4. gains -----------------------------------------------------------


def gains(args):
    """Write the Position P/I/D gains."""
    wanted = [
        ("Position_P_Gain", reg.POSITION_P_GAIN, args.p),
        ("Position_I_Gain", reg.POSITION_I_GAIN, args.i),
        ("Position_D_Gain", reg.POSITION_D_GAIN, args.d),
    ]
    wanted = [item for item in wanted if item[2] is not None]
    if not wanted:
        return _fail("Give at least one of --p, --i, --d.")

    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        print("id %d on %s" % (args.id, bus.device))
        refused = 0
        for name, register, value in wanted:
            result = bus.write(args.id, register, value)
            print(result.line(name))
            if not result:
                refused += 1
        if refused:
            return _fail(
                "%d write(s) were refused. The values may be out of range."
                % refused
            )
        print(RAM_NOTE)
        return 0
    finally:
        bus.close()


# 5. current ---------------------------------------------------------


def current(args):
    """Write Goal_Current, the ceiling on how hard the motor may push."""
    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        mode = bus.read(args.id, reg.OPERATING_MODE)
        limit = bus.read(args.id, reg.CURRENT_LIMIT)
        print("id %d on %s" % (args.id, bus.device))
        print("  mode %s, Current_Limit %s" % (format_mode(mode), limit))
        if mode != reg.MODE_CURRENT_BASED_POSITION:
            print(
                "  Goal_Current only caps force in current-based position "
                "control (mode 5). In this mode it may do nothing."
            )
        if limit is not None and abs(args.value) > limit:
            return _fail(
                "Goal_Current %d is outside -%d to %d (Current_Limit), so the "
                "motor will refuse it." % (args.value, limit, limit)
            )
        result = bus.write(args.id, reg.GOAL_CURRENT, args.value)
        print(result.line("Goal_Current"))
        if not result:
            return _fail("The write was refused.")
        print(RAM_NOTE)
        return 0
    finally:
        bus.close()


# 6. patch-lerobot ---------------------------------------------------

SOURCE_CANDIDATES = (
    "lerobot.robots.omx_follower.omx_follower",
    "lerobot.robots.omx.omx_follower",
)


def _find_source(explicit=None):
    if explicit:
        path = pathlib.Path(explicit).expanduser()
        if not path.is_file():
            raise patch.PatchError("%s does not exist." % path)
        return path
    for name in SOURCE_CANDIDATES:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        if spec and spec.origin:
            return pathlib.Path(spec.origin)
    raise patch.PatchError(
        "Could not find LeRobot's follower source. Tried: %s\n"
        "Pass the path with --file." % ", ".join(SOURCE_CANDIDATES)
    )


def patch_lerobot(args):
    """Edit LeRobot's source so it reapplies your settings on every connect."""
    settings = {
        "Operating_Mode": args.mode,
        "Current_Limit": args.current_limit,
        "Position_P_Gain": args.p,
        "Position_I_Gain": args.i,
        "Position_D_Gain": args.d,
        "Goal_Current": args.goal_current,
    }
    settings = {k: v for k, v in settings.items() if v is not None}
    if not settings and not args.revert:
        return _fail(
            "No settings were given. Pass some of --mode, --current-limit, "
            "--p, --i, --d, --goal-current."
        )

    try:
        source = _find_source(args.file)
        text = source.read_text()

        if args.revert:
            new_text, removed = patch.revert_patch(text)
            source.write_text(new_text)
            print("Removed %d line(s) from %s." % (removed, source))
            return 0

        source.write_text(patch.apply_patch(text, args.joint, settings))
    except patch.AlreadyPatched as exc:
        return _fail("%s Pass --revert to remove it." % exc)
    except patch.PatchError as exc:
        return _fail(exc)
    except OSError as exc:
        return _fail("Cannot write the source: %s" % exc)

    print("Patched %s" % source)
    for name, value in settings.items():
        print("  %-20s %s" % (name, value))
    print()
    if not args.file:
        print('Check it imports:  python -c "import %s"' % SOURCE_CANDIDATES[0])
    print(
        "Undo:  omx-doctor patch-lerobot %s%s --revert"
        % (args.joint, " --file %s" % args.file if args.file else "")
    )
    return 0


# 7. measure ---------------------------------------------------------


def measure(args):
    """Disable torque and record the travel range while you move the joint."""
    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        bus.prepare_eeprom(args.id)
        print("id %d on %s. Torque is off." % (args.id, bus.device))
        print(
            "For the next %d seconds, move the joint slowly to each end until "
            "it stops. Ctrl-C finishes early." % args.seconds
        )
        print()

        low = high = None
        start = time.perf_counter()
        try:
            while time.perf_counter() - start < args.seconds:
                position = bus.read(args.id, reg.PRESENT_POSITION)
                if position is not None:
                    low = position if low is None else min(low, position)
                    high = position if high is None else max(high, position)
                    print(
                        "\r  position %6s   min %6s   max %6s" % (position, low, high),
                        end="",
                        flush=True,
                    )
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            pass
        print()
        print()
        print(range_verdict(low, high))
        if not range_usable(low, high):
            return 1
        print()
        print("To write this range to the motor:")
        print("  omx-doctor set-range %d %d %d" % (args.id, low, high))
        print("On LeRobot, write the calibration file at the same time:")
        print("  omx-doctor sync-calib %d <joint> %d %d" % (args.id, low, high))
        return 0
    finally:
        bus.close()


# 8. set-range -------------------------------------------------------


def _range_problem(low, high):
    """Return why a range given on the command line cannot be written, or None."""
    if low >= high:
        return "The minimum must be below the maximum."
    if high - low < MIN_SPAN:
        return (
            "The range is only %d counts wide, which would lock the joint in "
            "place. Measure it again with `measure`." % (high - low)
        )
    return None


def _write_range(bus, motor_id, low, high, homing_offset):
    """Write the range and zero to EEPROM, printing each result."""
    writes = [
        ("Min_Position_Limit", reg.MIN_POSITION_LIMIT, low),
        ("Max_Position_Limit", reg.MAX_POSITION_LIMIT, high),
    ]
    if homing_offset is not None:
        writes.append(("Homing_Offset", reg.HOMING_OFFSET, homing_offset))

    results = []
    for name, register, value in writes:
        result = bus.write(motor_id, register, value)
        print(result.line(name))
        results.append(result)
    return results


def set_range(args):
    """Write a travel range to the motor's EEPROM."""
    problem = _range_problem(args.min, args.max)
    if problem:
        return _fail(problem)

    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        print("id %d on %s" % (args.id, bus.device))
        if bus.prepare_eeprom(args.id):
            print("  An error was latched, so the motor was rebooted. RAM is reset.")
        results = _write_range(bus, args.id, args.min, args.max, args.homing_offset)
        if not all(results):
            return _fail(
                "Some values were refused. A motor silently ignores an "
                "out-of-range value. Check them and run again."
            )
        print("Stored in EEPROM. It survives a power cycle.")
        print()
        print(
            "On LeRobot the calibration file has to hold the same values. "
            "Use sync-calib instead of this command."
        )
        return 0
    finally:
        bus.close()


# 9. sync-calib ------------------------------------------------------


def sync_calib(args):
    """Write the same range to EEPROM and to the LeRobot calibration file.

    EEPROM goes first, and the file is left alone if any write is
    refused, because the worst outcome is the two disagreeing.
    """
    problem = _range_problem(args.min, args.max)
    if problem:
        return _fail(problem)

    try:
        path = calib.find_file(args.joint, args.id)
        data = calib.load(path)
    except calib.CalibrationError as exc:
        return _fail(exc)

    print("Calibration file: %s" % path)
    print("  now:  %s" % calib.describe_joint(data, args.joint))

    try:
        bus = find_motor(args.id)
    except BusError as exc:
        return _fail(exc)

    try:
        print()
        print("id %d on %s" % (args.id, bus.device))
        if bus.prepare_eeprom(args.id):
            print("  An error was latched, so the motor was rebooted. RAM is reset.")
        results = _write_range(bus, args.id, args.min, args.max, args.homing_offset)
        if not all(results):
            return _fail(
                "The EEPROM write was refused, so the calibration file was "
                "left untouched. Check the values and run again."
            )
    finally:
        bus.close()

    try:
        updated = calib.update_joint(
            data,
            args.joint,
            range_min=args.min,
            range_max=args.max,
            homing_offset=args.homing_offset,
        )
        backup = calib.save_with_backup(path, updated)
    except (calib.CalibrationError, OSError) as exc:
        return _fail(
            "EEPROM was written but the calibration file was not, so the two "
            "now disagree: %s" % exc
        )

    print()
    print("Calibration file updated. The original is at %s" % backup)
    print("  now:  %s" % calib.describe_joint(updated, args.joint))
    print()
    print("EEPROM and the file agree, so LeRobot will not ask to recalibrate.")
    return 0


# 10. compare --------------------------------------------------------


def _parse_pair(text):
    if ":" not in text:
        raise ValueError("Use LEADER:FOLLOWER, for example 6:16")
    left, right = text.split(":", 1)
    return int(left), int(right)


def compare(args):
    """Compare leader and follower positions."""
    try:
        pairs = [_parse_pair(text) for text in args.pairs]
    except ValueError as exc:
        return _fail(exc)

    buses = open_all()
    if not buses:
        return _fail("No serial port could be opened.")

    location = {}
    try:
        for bus in buses:
            for motor_id in bus.scan(reg.SCAN_IDS):
                location.setdefault(motor_id, bus)

        print("  %-16s %9s %9s %9s" % ("PAIR", "LEADER", "FOLLOWER", "OFFSET"))
        problems = 0
        verdicts = []
        for leader_id, follower_id in pairs:
            label = "%d:%d" % (leader_id, follower_id)
            leader_bus = location.get(leader_id)
            follower_bus = location.get(follower_id)
            if leader_bus is None or follower_bus is None:
                missing = [
                    str(i)
                    for i, b in ((leader_id, leader_bus), (follower_id, follower_bus))
                    if b is None
                ]
                print("  %-16s  id %s not found." % (label, ", ".join(missing)))
                problems += 1
                continue
            leader = leader_bus.read(leader_id, reg.PRESENT_POSITION)
            follower = follower_bus.read(follower_id, reg.PRESENT_POSITION)
            offset = None if leader is None or follower is None else follower - leader
            print("  %-16s %9s %9s %9s" % (label, leader, follower, offset))
            verdicts.append((label, diff_verdict(offset)))
            boundary = boundary_verdict(leader, follower)
            if boundary:
                verdicts.append((label, boundary))
            if offset is None or abs(offset) > DIFF_SMALL or boundary:
                problems += 1
    finally:
        for bus in buses:
            bus.close()

    print()
    for label, verdict in verdicts:
        print("%s  %s" % (label, verdict))
    print()
    print(
        "Hold both arms in the same pose before comparing. If the poses "
        "differ, the offsets mean nothing."
    )
    return 1 if problems else 0
