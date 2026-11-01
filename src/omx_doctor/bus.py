"""Everything that actually talks to a motor.

All hardware I/O is confined to this file. The rest of the package is
pure functions so it can be unit tested without a robot.

Important: RS-485 is half duplex and allows exactly one master. If
LeRobot is running, stop it before using this tool, or both sides will
see corrupted traffic.
"""

import glob
import time

from .decode import to_signed
from .registers import (
    DEFAULT_BAUDRATE,
    EEPROM_ADDRESSES,
    HARDWARE_ERROR,
    PROTOCOL_VERSION,
    SCAN_IDS,
    TORQUE_ENABLE,
)

try:
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler
except ImportError as exc:  # pragma: no cover - install hint
    raise SystemExit(
        "dynamixel-sdk is required. Run: pip install dynamixel-sdk"
    ) from exc

# A motor with a latched hardware error sets this bit in the error field of
# every status packet. It only says "check Hardware_Error_Status"; the data
# in the packet is still valid, so it must not be treated as a failure.
ERRBIT_ALERT = 0x80


class BusError(Exception):
    """A motor cannot be reached."""


class MotorNotFound(BusError):
    """No port answered for that motor ID."""


def list_ports():
    """Return the USB serial device candidates."""
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


class Bus:
    """Reads and writes the motors on one serial port."""

    def __init__(self, device, baudrate=DEFAULT_BAUDRATE):
        self.device = device
        self.baudrate = baudrate
        self._port = None
        self._ph = PacketHandler(PROTOCOL_VERSION)

    def open(self):
        port = PortHandler(self.device)
        if not port.openPort():
            raise BusError(
                "Cannot open %s. Another program may be holding it, or you "
                "may not have permission." % self.device
            )
        if not port.setBaudRate(self.baudrate):
            port.closePort()
            raise BusError("Cannot set the baud rate on %s." % self.device)
        self._port = port
        return self

    def close(self):
        if self._port is not None:
            self._port.closePort()
            self._port = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    # Reads and writes ------------------------------------------------

    def ping(self, motor_id):
        """Return the model number if the motor answers, else None."""
        model, result, _ = self._ph.ping(self._port, motor_id)
        return model if result == COMM_SUCCESS else None

    def scan(self, ids=SCAN_IDS):
        """Return {motor id: model number} for every motor that answers."""
        found = {}
        for motor_id in ids:
            model = self.ping(motor_id)
            if model is not None:
                found[motor_id] = model
        return found

    def read(self, motor_id, register):
        """Read one register. Returns None on failure."""
        addr, nbytes, signed = register
        reader = {
            1: self._ph.read1ByteTxRx,
            2: self._ph.read2ByteTxRx,
            4: self._ph.read4ByteTxRx,
        }[nbytes]
        value, result, error = reader(self._port, motor_id, addr)
        if result != COMM_SUCCESS or error & ~ERRBIT_ALERT:
            return None
        return to_signed(value, nbytes) if signed else value

    def write(self, motor_id, register, value):
        """Write one register, then read it back to confirm it took.

        A motor silently ignores an out-of-range value and keeps the old
        one, so reading back is the only way to know what happened.
        """
        addr, nbytes, signed = register
        writer = {
            1: self._ph.write1ByteTxRx,
            2: self._ph.write2ByteTxRx,
            4: self._ph.write4ByteTxRx,
        }[nbytes]
        raw = value & ((1 << (8 * nbytes)) - 1) if signed and value < 0 else value
        result, error = writer(self._port, motor_id, addr, raw)
        readback = self.read(motor_id, register)
        return WriteResult(
            addr=addr,
            value=value,
            readback=readback,
            ok=readback == value,
            comm=self._ph.getTxRxResult(result),
            error=self._ph.getRxPacketError(error) if error else "",
        )

    def reboot(self, motor_id, settle=1.5):
        """Reboot a motor to clear its latched error. This also resets RAM."""
        result, _ = self._ph.reboot(self._port, motor_id)
        if result != COMM_SUCCESS:
            raise BusError(
                "Cannot reboot id %d. Check the arm's power and the USB "
                "connection (on WSL2, run `usbipd attach` again)." % motor_id
            )
        time.sleep(settle)

    # Common combinations ---------------------------------------------

    def clear_error(self, motor_id):
        """Reboot only if an error is latched. Returns True if it rebooted."""
        status = self.read(motor_id, HARDWARE_ERROR)
        if status:
            self.reboot(motor_id)
            return True
        return False

    def torque_off(self, motor_id):
        return self.write(motor_id, TORQUE_ENABLE, 0)

    def prepare_eeprom(self, motor_id):
        """Put a motor into a state where EEPROM writes are accepted.

        An EEPROM write is refused while torque is on or an error is
        latched. Returns True if the motor had to be rebooted.
        """
        rebooted = self.clear_error(motor_id)
        self.torque_off(motor_id)
        return rebooted


class WriteResult:
    """The outcome of a single verified write."""

    def __init__(self, addr, value, readback, ok, comm, error):
        self.addr = addr
        self.value = value
        self.readback = readback
        self.ok = ok
        self.comm = comm
        self.error = error

    def line(self, name):
        if self.ok:
            outcome = "ok"
        else:
            outcome = "REFUSED, reads back %s" % self.readback
            if self.comm or self.error:
                outcome += "  %s %s" % (self.comm, self.error)
        return "  %-20s %5s  ->  %-8s %s" % (
            name,
            "(%d)" % self.addr,
            self.value,
            outcome,
        )

    def __bool__(self):
        return self.ok


def find_motor(motor_id, baudrate=DEFAULT_BAUDRATE):
    """Sweep every port for a motor ID and return its open bus.

    Device names shift with plug order, so motors are located by ID
    rather than asking you which port to use.
    """
    for device in list_ports():
        bus = Bus(device, baudrate)
        try:
            bus.open()
        except BusError:
            continue
        if bus.ping(motor_id) is not None:
            return bus
        bus.close()
    raise MotorNotFound(
        "Could not find id %d. Check that the arm is powered and plugged in, "
        "and that no other program (LeRobot, for example) is holding the "
        "port." % motor_id
    )


def open_all(baudrate=DEFAULT_BAUDRATE):
    """Open every port that can be opened and return the buses."""
    buses = []
    for device in list_ports():
        bus = Bus(device, baudrate)
        try:
            buses.append(bus.open())
        except BusError:
            continue
    return buses


def is_eeprom(register):
    return register[0] in EEPROM_ADDRESSES
