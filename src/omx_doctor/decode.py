"""Turn raw register values into readings a person can act on.

Nothing here touches hardware, so all of it is covered by unit tests that
run without a robot attached.
"""

from .registers import ENCODER_RESOLUTION, ERROR_BITS, MODE_NAMES

# These thresholds only choose the wording of a verdict. They never change
# a setting, and the raw numbers are printed alongside every verdict so
# you can draw your own conclusion.
PWM_SATURATION_RATIO = 0.95  # at or above this fraction of PWM_Limit, call it saturated
DIFF_SMALL = 50  # leader/follower offsets within this are normal
DIFF_JOINT = 400  # beyond this, suspect how the joint was assembled


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


def range_verdict(low, high):
    """Say whether a hand-measured travel range looks usable."""
    if low is None or high is None:
        return "No measurement was taken."
    span = high - low
    if span <= 0:
        return "The minimum is above the maximum. Measure again."
    if span < 50:
        return (
            "The range is only %d counts wide. Check that you moved the joint "
            "all the way to both ends." % span
        )
    if not (0 <= low and high < ENCODER_RESOLUTION):
        return "The range fell outside 0 to %d. Measure again." % (
            ENCODER_RESOLUTION - 1
        )
    return "Range %d to %d (span %d, about %.0f degrees)." % (
        low,
        high,
        span,
        counts_to_degrees(span),
    )
