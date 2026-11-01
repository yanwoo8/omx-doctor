"""A simulated Dynamixel bus, so commands can run without a robot.

FakePortHandler and FakePacketHandler stand in for the dynamixel_sdk
classes that bus.py uses. Each simulated motor keeps a control table and
follows the rules from the Protocol 2.0 e-Manual that this tool depends on:

- While Hardware_Error_Status is non-zero, every status packet carries the
  Alert bit (0x80) in its error field. The data in the packet is still valid.
- An EEPROM write is refused while torque is on (Access Error, 0x07).
- An out-of-range value is refused and the old value is kept (Data Range
  Error, 0x04).
- Torque cannot be enabled while an error is latched.
- A reboot clears the error and resets RAM to its defaults.
"""

import pytest

from omx_doctor import bus as bus_module
from omx_doctor import registers as reg

COMM_SUCCESS = 0
COMM_TX_FAIL = -1001
COMM_RX_TIMEOUT = -3001

ERRBIT_ALERT = 0x80
ERR_DATA_RANGE = 0x04
ERR_ACCESS = 0x07

XM430_W350 = 1020

EEPROM_DEFAULTS = {
    reg.MODEL_NUMBER: XM430_W350,
    reg.OPERATING_MODE: reg.MODE_POSITION,
    reg.HOMING_OFFSET: 0,
    reg.TEMPERATURE_LIMIT: 80,
    reg.PWM_LIMIT: 885,
    reg.CURRENT_LIMIT: 1193,
    reg.MAX_POSITION_LIMIT: 4095,
    reg.MIN_POSITION_LIMIT: 0,
}

RAM_DEFAULTS = {
    reg.TORQUE_ENABLE: 0,
    reg.HARDWARE_ERROR: 0,
    reg.POSITION_D_GAIN: 0,
    reg.POSITION_I_GAIN: 0,
    reg.POSITION_P_GAIN: 800,
    reg.GOAL_CURRENT: 1193,
    reg.GOAL_POSITION: 2048,
    reg.PRESENT_PWM: 0,
    reg.PRESENT_CURRENT: 0,
    reg.PRESENT_POSITION: 2048,
    reg.PRESENT_TEMPERATURE: 30,
}


def _to_raw(value, nbytes):
    return value & ((1 << (8 * nbytes)) - 1)


class FakeMotor:
    def __init__(self, motor_id, **values):
        """values: register name in lower case, e.g. hardware_error=32."""
        self.id = motor_id
        self.table = {}
        self.reboots = 0
        self.reboot_fails = False
        # Present_Position readings to return in order, as if the joint were
        # moved by hand. The last one repeats once the list runs out.
        self.positions = []
        for register, value in list(EEPROM_DEFAULTS.items()) + list(RAM_DEFAULTS.items()):
            self.set(register, value)
        for name, value in values.items():
            self.set(getattr(reg, name.upper()), value)

    def set(self, register, value):
        addr, nbytes, _ = register
        self.table[addr] = _to_raw(value, nbytes)

    def get(self, register):
        addr, nbytes, signed = register
        raw = self.table[addr]
        return bus_module.to_signed(raw, nbytes) if signed else raw

    def read(self, addr):
        if addr == reg.PRESENT_POSITION[0] and self.positions:
            position = self.positions.pop(0) if len(self.positions) > 1 else self.positions[0]
            self.set(reg.PRESENT_POSITION, position)
        return self.table[addr]

    @property
    def alert(self):
        return ERRBIT_ALERT if self.get(reg.HARDWARE_ERROR) else 0

    def _in_range(self, register, value):
        if register in (reg.POSITION_P_GAIN, reg.POSITION_I_GAIN, reg.POSITION_D_GAIN):
            return 0 <= value <= 16383
        if register == reg.GOAL_CURRENT:
            limit = self.get(reg.CURRENT_LIMIT)
            return -limit <= value <= limit
        if register == reg.GOAL_POSITION:
            return self.get(reg.MIN_POSITION_LIMIT) <= value <= self.get(reg.MAX_POSITION_LIMIT)
        if register == reg.TORQUE_ENABLE:
            return value in (0, 1)
        if register in (reg.MIN_POSITION_LIMIT, reg.MAX_POSITION_LIMIT):
            return 0 <= value <= 4095
        return True

    def write(self, addr, raw):
        register = next(r for r in reg.BY_NAME.values() if r[0] == addr)
        value = bus_module.to_signed(raw, register[1]) if register[2] else raw
        if addr in reg.EEPROM_ADDRESSES and self.get(reg.TORQUE_ENABLE):
            return ERR_ACCESS | self.alert
        if register == reg.TORQUE_ENABLE and value == 1 and self.alert:
            return ERR_ACCESS | self.alert
        if not self._in_range(register, value):
            return ERR_DATA_RANGE | self.alert
        self.table[addr] = raw
        return self.alert

    def reboot(self):
        self.reboots += 1
        for register, value in RAM_DEFAULTS.items():
            if register != reg.PRESENT_POSITION:
                self.set(register, value)


class FakeArm:
    """Motors attached to simulated ports: {device: {id: FakeMotor}}."""

    def __init__(self):
        self.ports = {}

    def add(self, device, *motors):
        self.ports.setdefault(device, {})
        for motor in motors:
            self.ports[device][motor.id] = motor
        return self

    def motor(self, motor_id):
        for motors in self.ports.values():
            if motor_id in motors:
                return motors[motor_id]
        raise KeyError(motor_id)


class FakePortHandler:
    arm = None

    def __init__(self, device):
        self.device = device

    def openPort(self):
        return self.device in self.arm.ports

    def setBaudRate(self, baudrate):
        return True

    def closePort(self):
        pass


class FakePacketHandler:
    def __init__(self, protocol_version):
        pass

    def _motor(self, port, motor_id):
        return port.arm.ports[port.device].get(motor_id)

    def ping(self, port, motor_id):
        motor = self._motor(port, motor_id)
        if motor is None:
            return 0, COMM_RX_TIMEOUT, 0
        return motor.get(reg.MODEL_NUMBER), COMM_SUCCESS, motor.alert

    def _read(self, port, motor_id, addr):
        motor = self._motor(port, motor_id)
        if motor is None:
            return 0, COMM_RX_TIMEOUT, 0
        return motor.read(addr), COMM_SUCCESS, motor.alert

    read1ByteTxRx = read2ByteTxRx = read4ByteTxRx = _read

    def _write(self, port, motor_id, addr, raw):
        motor = self._motor(port, motor_id)
        if motor is None:
            return COMM_RX_TIMEOUT, 0
        return COMM_SUCCESS, motor.write(addr, raw)

    write1ByteTxRx = write2ByteTxRx = write4ByteTxRx = _write

    def reboot(self, port, motor_id):
        motor = self._motor(port, motor_id)
        if motor is None or motor.reboot_fails:
            return COMM_TX_FAIL, 0
        motor.reboot()
        return COMM_SUCCESS, 0

    def getTxRxResult(self, result):
        return "" if result == COMM_SUCCESS else "[TxRxResult] %d" % result

    def getRxPacketError(self, error):
        return "[RxPacketError] 0x%02X" % error


@pytest.fixture
def arm(monkeypatch):
    """An empty simulated arm. Add motors with arm.add(device, FakeMotor(...))."""
    fake = FakeArm()
    FakePortHandler.arm = fake
    monkeypatch.setattr(FakePortHandler, "arm", fake)
    monkeypatch.setattr(bus_module, "PortHandler", FakePortHandler)
    monkeypatch.setattr(bus_module, "PacketHandler", FakePacketHandler)
    monkeypatch.setattr(bus_module, "list_ports", lambda: sorted(fake.ports))
    monkeypatch.setattr(bus_module.time, "sleep", lambda seconds: None)
    return fake
