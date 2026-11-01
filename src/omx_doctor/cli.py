"""omx-doctor entry point."""

import argparse
import sys

from . import __version__

EPILOG = """\
The subcommands follow the order of the README. If you do not know where
to start, run `omx-doctor status`.

Warning: stop LeRobot before using this tool. RS-485 allows one master,
so two programs on one port corrupt traffic for both.
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="omx-doctor",
        description="Diagnose and configure the Dynamixel motors in a "
        "ROBOTIS OpenManipulator-X.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version="omx-doctor %s" % __version__
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")

    def add(name, help_text):
        return sub.add_parser(name, help=help_text, description=help_text)

    def add_ids(p):
        p.add_argument(
            "--ids",
            nargs="+",
            type=int,
            metavar="ID",
            help="motor IDs to sweep (default: 1 through 30)",
        )

    # 1
    p = add("status", "Find every motor and print position, current, temperature and errors.")
    add_ids(p)

    # 2
    p = add("reset", "Reboot only the motors with a latched error, then disable all torque.")
    add_ids(p)

    # 3
    p = add("watch", "Log PWM and current to see whether PWM pins against its limit.")
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("--goal", type=int, help="drive to this position (default: read only)")
    p.add_argument("--seconds", type=float, default=20.0, help="how long to log (default: 20)")

    # 4
    p = add("gains", "Write the Position P/I/D gains.")
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("--p", type=int, help="Position_P_Gain")
    p.add_argument("--i", type=int, help="Position_I_Gain")
    p.add_argument("--d", type=int, help="Position_D_Gain")

    # 5
    p = add("current", "Write Goal_Current, the ceiling on how hard the motor may push.")
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("value", type=int, help="Goal_Current value")

    # 6
    p = add(
        "patch-lerobot",
        "Edit LeRobot's source so it reapplies your settings on every connect.",
    )
    p.add_argument("joint", help="joint name as LeRobot calls it, for example gripper")
    p.add_argument("--mode", type=int, help="Operating_Mode")
    p.add_argument("--current-limit", type=int, help="Current_Limit")
    p.add_argument("--p", type=int, help="Position_P_Gain")
    p.add_argument("--i", type=int, help="Position_I_Gain")
    p.add_argument("--d", type=int, help="Position_D_Gain")
    p.add_argument("--goal-current", type=int, help="Goal_Current")
    p.add_argument("--file", help="path to the source, if it cannot be found")
    p.add_argument("--revert", action="store_true", help="remove every line this added")

    # 7
    p = add("measure", "Disable torque and record the travel range while you move the joint.")
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("--seconds", type=float, default=30.0, help="how long to record (default: 30)")

    # 8
    p = add("set-range", "Write a travel range to the motor's EEPROM.")
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("min", type=int, help="Min_Position_Limit")
    p.add_argument("max", type=int, help="Max_Position_Limit")
    p.add_argument("--homing-offset", type=int, help="Homing_Offset")

    # 9
    p = add(
        "sync-calib",
        "Write the same range to EEPROM and to the LeRobot calibration file.",
    )
    p.add_argument("id", type=int, help="motor ID")
    p.add_argument("joint", help="joint name as LeRobot calls it, for example gripper")
    p.add_argument("min", type=int, help="range minimum")
    p.add_argument("max", type=int, help="range maximum")
    p.add_argument("--homing-offset", type=int, help="Homing_Offset")

    # 10
    p = add("compare", "Compare leader and follower positions.")
    p.add_argument(
        "pairs",
        nargs="+",
        metavar="LEADER:FOLLOWER",
        help="pairs to compare, for example 1:11 2:12 6:16",
    )

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    # Hardware modules are imported here so that --help works without
    # dynamixel-sdk installed.
    from . import commands
    from .bus import BusError
    from .registers import SCAN_IDS

    if hasattr(args, "ids") and args.ids is None:
        args.ids = list(SCAN_IDS)

    handlers = {
        "status": commands.status,
        "reset": commands.reset,
        "watch": commands.watch,
        "gains": commands.gains,
        "current": commands.current,
        "patch-lerobot": commands.patch_lerobot,
        "measure": commands.measure,
        "set-range": commands.set_range,
        "sync-calib": commands.sync_calib,
        "compare": commands.compare,
    }
    try:
        return handlers[args.command](args)
    except BusError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
