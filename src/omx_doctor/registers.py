"""Dynamixel Protocol 2.0 control table.

Everything here is part of the motor's specification, so it does not vary
between setups. Values that differ from robot to robot (travel range,
gains, current limit) are not stored here: you measure them and pass them
in as arguments.
"""

PROTOCOL_VERSION = 2.0

# Both the OMX leader and follower arms ship at 1 Mbps.
DEFAULT_BAUDRATE = 1_000_000

# Register definitions: (address, byte width, signed)
MODEL_NUMBER = (0, 2, False)
OPERATING_MODE = (11, 1, False)
HOMING_OFFSET = (20, 4, True)
TEMPERATURE_LIMIT = (31, 1, False)
PWM_LIMIT = (36, 2, False)
CURRENT_LIMIT = (38, 2, False)
MAX_POSITION_LIMIT = (48, 4, True)
MIN_POSITION_LIMIT = (52, 4, True)
TORQUE_ENABLE = (64, 1, False)
HARDWARE_ERROR = (70, 1, False)
POSITION_D_GAIN = (80, 2, False)
POSITION_I_GAIN = (82, 2, False)
POSITION_P_GAIN = (84, 2, False)
GOAL_CURRENT = (102, 2, True)
GOAL_POSITION = (116, 4, True)
PRESENT_PWM = (124, 2, True)
PRESENT_CURRENT = (126, 2, True)
PRESENT_POSITION = (132, 4, True)
PRESENT_TEMPERATURE = (146, 1, False)

# Lookup by name, for messages and for the LeRobot source patch.
BY_NAME = {
    "Model_Number": MODEL_NUMBER,
    "Operating_Mode": OPERATING_MODE,
    "Homing_Offset": HOMING_OFFSET,
    "Temperature_Limit": TEMPERATURE_LIMIT,
    "PWM_Limit": PWM_LIMIT,
    "Current_Limit": CURRENT_LIMIT,
    "Max_Position_Limit": MAX_POSITION_LIMIT,
    "Min_Position_Limit": MIN_POSITION_LIMIT,
    "Torque_Enable": TORQUE_ENABLE,
    "Hardware_Error_Status": HARDWARE_ERROR,
    "Position_D_Gain": POSITION_D_GAIN,
    "Position_I_Gain": POSITION_I_GAIN,
    "Position_P_Gain": POSITION_P_GAIN,
    "Goal_Current": GOAL_CURRENT,
    "Goal_Position": GOAL_POSITION,
    "Present_PWM": PRESENT_PWM,
    "Present_Current": PRESENT_CURRENT,
    "Present_Position": PRESENT_POSITION,
    "Present_Temperature": PRESENT_TEMPERATURE,
}

# Registers that live in EEPROM. Writing one requires Torque_Enable to be
# 0 and Hardware_Error_Status to be clear, otherwise the write is refused.
EEPROM_ADDRESSES = frozenset(
    addr
    for addr, _, _ in (
        OPERATING_MODE,
        HOMING_OFFSET,
        TEMPERATURE_LIMIT,
        PWM_LIMIT,
        CURRENT_LIMIT,
        MAX_POSITION_LIMIT,
        MIN_POSITION_LIMIT,
    )
)

# Operating_Mode values
MODE_CURRENT = 0
MODE_VELOCITY = 1
MODE_POSITION = 3
MODE_EXTENDED_POSITION = 4
MODE_CURRENT_BASED_POSITION = 5
MODE_PWM = 16

MODE_NAMES = {
    MODE_CURRENT: "current control",
    MODE_VELOCITY: "velocity control",
    MODE_POSITION: "position control",
    MODE_EXTENDED_POSITION: "extended position control",
    MODE_CURRENT_BASED_POSITION: "current-based position control",
    MODE_PWM: "PWM control",
}

# Bit meanings in Hardware_Error_Status
ERROR_BITS = {
    0: "InputVoltage",
    2: "Overheating",
    3: "EncoderError",
    4: "ElectricalShock",
    5: "Overload",
}

# Encoder counts per full revolution
ENCODER_RESOLUTION = 4096

# ID range swept when looking for motors
SCAN_IDS = range(1, 31)
