"""Turn raw register values into readings a person can act on.

Nothing here touches hardware, so all of it is covered by unit tests that
run without a robot attached.
"""

from .registers import ENCODER_RESOLUTION, ERROR_BITS, MODE_NAMES

# These thresholds only choose the wording of a verdict. They never change
# a setting, and the raw numbers are printed alongside every verdict so
# you can draw your own conclusion.
PWM_SATURATION_RATIO = 0.95  # at or above this fraction of PWM_Limit, call it saturated
DIFF_SMALL = 150  # leader/follower offsets within this are normal
DIFF_JOINT = 400  # beyond this, suspect how the joint was assembled
MIN_SPAN = 50  # a travel range narrower than this means the joint was not moved
BOUNDARY_MARGIN = 200  # a reading this close to 0 or 4095 sits on the encoder boundary


def to_signed(value, nbytes):
    """Reinterpret an unsigned register read as a signed value."""
    limit = 1 << (8 * nbytes - 1)
    if value >= limit:
        value -= limit * 2
    return value


def decode_error(status):
    """List the error names set in a Hardware_Error_Status value."""
    if not status:
        return []
    names = []
    for bit, name in sorted(ERROR_BITS.items()):
        if status & (1 << bit):
            names.append(name)
    unknown = status & ~sum(1 << bit for bit in ERROR_BITS)
    if unknown:
        names.append("Unknown(0x%02X)" % unknown)
    return names


def format_error(status):
    """Render an error status as one field."""
    if status is None:
        return "read failed"
    if not status:
        return "clear"
    return "%d (%s)" % (status, ", ".join(decode_error(status)))


def format_mode(mode):
    """Render an Operating_Mode value with its name."""
    if mode is None:
        return "read failed"
    return "%d (%s)" % (mode, MODE_NAMES.get(mode, "unknown"))


def counts_to_degrees(counts):
    """Convert encoder counts to degrees."""
    return counts * 360.0 / ENCODER_RESOLUTION


def degrees_to_counts(degrees):
    """Convert degrees to encoder counts."""
    return degrees * ENCODER_RESOLUTION / 360.0


def triage(status):
    """Say which section of the README to go to for this error status."""
    if status is None:
        return "Cannot read the motor. Check power and the USB connection."
    names = decode_error(status)
    if not names:
        return "No error. If the motion itself is wrong, go to section 4."
    if "Overload" in names:
        return "Overload: go to section 2."
    if "Overheating" in names:
        return "Overheating: cut power, let it cool, then go to section 2."
    if "EncoderError" in names:
        return "EncoderError: check how the joint is assembled. Section 4.3."
    if "InputVoltage" in names:
        return "InputVoltage: check the power adapter and the wiring."
    if "ElectricalShock" in names:
        return "ElectricalShock: cut power and check the wiring for a short."
    return "Unexpected error: %s" % ", ".join(names)


def pwm_verdict(peak_pwm, pwm_limit):
    """Say whether the recorded peak PWM pinned against the limit."""
    if pwm_limit in (None, 0) or peak_pwm is None:
        return "PWM_Limit could not be read, so there is no verdict."
    ratio = abs(peak_pwm) / float(pwm_limit)
    if ratio >= PWM_SATURATION_RATIO:
        return (
            "PWM saturated (peak %d, limit %d). Start at section 2.2."
            % (abs(peak_pwm), pwm_limit)
        )
    return "PWM not saturated (peak %d, limit %d)." % (abs(peak_pwm), pwm_limit)


def temperature_verdict(samples):
    """Say whether the recorded temperature kept climbing."""
    values = [v for v in samples if v is not None]
    if len(values) < 2:
        return "Not enough temperature samples."
    rise = values[-1] - values[0]
    if rise >= 5:
        return (
            "Temperature kept climbing (%d C to %d C). Cut power and let it cool."
            % (values[0], values[-1])
        )
    return "Temperature held steady (%d C to %d C, peak %d C)." % (
        values[0],
        values[-1],
        max(values),
    )


def diff_verdict(diff):
    """Interpret the offset between a leader and a follower position."""
    if diff is None:
        return "One side could not be read, so there is nothing to compare."
    size = abs(diff)
    if size <= DIFF_SMALL:
        return "Offset %d. Within the normal range." % diff
    if size < DIFF_JOINT:
        return (
            "Offset %d. The zero point has drifted. Measure the range and zero "
            "again in section 3." % diff
        )
    return (
        "Offset %d (about %.0f degrees). The joint is assembled at a different "
        "angle. See section 4.3." % (diff, counts_to_degrees(size))
    )


def near_boundary(position):
    """Say whether a position reading sits on or past the 0/4095 boundary.

    In extended position mode the count keeps going past one revolution,
    so a joint whose rest pose reads near 0 or 4095 can read 4090 one
    moment and -6 the next. The controller treats that as a jump of a full
    turn.
    """
    if position is None:
        return False
    return (
        position < BOUNDARY_MARGIN
        or position > ENCODER_RESOLUTION - 1 - BOUNDARY_MARGIN
    )


def boundary_verdict(leader, follower):
    """Warn when either side of a pair sits on the encoder boundary."""
    if not (near_boundary(leader) or near_boundary(follower)):
        return None
    return (
        "The zero point sits on the 0/%d encoder boundary, so the reading "
        "can jump by a full turn. Reassemble the joint so the rest pose reads "
        "near 2048. See section 4.3." % (ENCODER_RESOLUTION - 1)
    )


def range_usable(low, high):
    """Say whether a measured range is safe to write to the motor."""
    if low is None or high is None:
        return False
    return high - low >= MIN_SPAN and 0 <= low and high < ENCODER_RESOLUTION


def range_verdict(low, high):
    """Say whether a hand-measured travel range looks usable."""
    if low is None or high is None:
        return "No measurement was taken."
    span = high - low
    if span < 0:
        return "The minimum is above the maximum. Measure again."
    if span == 0:
        return (
            "The joint did not move. Move it slowly to each end until it "
            "stops, then measure again."
        )
    if span < MIN_SPAN:
        return (
            "The range is only %d counts wide. Check that you moved the joint "
            "all the way to both ends." % span
        )
    if not (0 <= low and high < ENCODER_RESOLUTION):
        return (
            "The range fell outside 0 to %d, so the joint's zero sits on the "
            "encoder boundary. Measuring again will not fix this: reassemble "
            "the joint so the rest pose reads near 2048. See section 4.3."
            % (ENCODER_RESOLUTION - 1)
        )
    return "Range %d to %d (span %d, about %.0f degrees)." % (
        low,
        high,
        span,
        counts_to_degrees(span),
    )
