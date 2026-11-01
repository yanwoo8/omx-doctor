"""Unit tests for decode.py.

Bit decoding, sign conversion and the verdict logic can all be verified
without a robot attached.
"""

from omx_doctor import decode
from omx_doctor.registers import ENCODER_RESOLUTION


class TestToSigned:
    def test_positive_values_pass_through(self):
        assert decode.to_signed(100, 2) == 100
        assert decode.to_signed(0, 4) == 0

    def test_two_byte_negative(self):
        assert decode.to_signed(65374, 2) == -162
        assert decode.to_signed(65535, 2) == -1

    def test_four_byte_negative(self):
        assert decode.to_signed(0xFFFFFFFF, 4) == -1
        assert decode.to_signed(0xFFFFFF9C, 4) == -100

    def test_boundary(self):
        assert decode.to_signed(32767, 2) == 32767
        assert decode.to_signed(32768, 2) == -32768


class TestDecodeError:
    def test_no_error(self):
        assert decode.decode_error(0) == []
        assert decode.decode_error(None) == []

    def test_overload_is_32(self):
        assert decode.decode_error(32) == ["Overload"]

    def test_overheating_is_4(self):
        assert decode.decode_error(4) == ["Overheating"]

    def test_several_bits(self):
        assert decode.decode_error(36) == ["Overheating", "Overload"]

    def test_undefined_bit(self):
        assert decode.decode_error(64) == ["Unknown(0x40)"]

    def test_defined_and_undefined_mixed(self):
        names = decode.decode_error(32 | 64)
        assert "Overload" in names
        assert "Unknown(0x40)" in names


class TestFormatError:
    def test_clear(self):
        assert decode.format_error(0) == "clear"

    def test_read_failure(self):
        assert decode.format_error(None) == "read failed"

    def test_value_and_name_together(self):
        text = decode.format_error(32)
        assert "32" in text
        assert "Overload" in text


class TestFormatMode:
    def test_known_mode(self):
        text = decode.format_mode(5)
        assert "5" in text
        assert "current-based" in text

    def test_unknown_mode(self):
        assert "unknown" in decode.format_mode(99)

    def test_read_failure(self):
        assert decode.format_mode(None) == "read failed"


class TestTriage:
    def test_no_error_points_at_section_4(self):
        assert "section 4" in decode.triage(0)

    def test_overload_points_at_section_2(self):
        assert "section 2" in decode.triage(32)

    def test_overheating_says_cool_down(self):
        assert "cool" in decode.triage(4)

    def test_encoder_error_points_at_assembly(self):
        assert "assembled" in decode.triage(8)

    def test_read_failure_mentions_power(self):
        assert "power" in decode.triage(None)

    def test_overload_wins_over_overheating(self):
        # With both set, the Overload path takes precedence.
        assert "section 2." in decode.triage(36)


class TestCounts:
    def test_full_revolution_is_360_degrees(self):
        assert decode.counts_to_degrees(ENCODER_RESOLUTION) == 360.0

    def test_round_trip(self):
        assert decode.degrees_to_counts(decode.counts_to_degrees(1000)) == 1000

    def test_quarter_turn(self):
        assert decode.counts_to_degrees(1024) == 90.0


class TestPwmVerdict:
    def test_pinned_at_the_limit_is_saturated(self):
        text = decode.pwm_verdict(-885, 885)
        assert "saturated" in text
        assert "not saturated" not in text

    def test_headroom_is_not_saturated(self):
        assert "not saturated" in decode.pwm_verdict(285, 885)

    def test_sign_is_ignored(self):
        assert decode.pwm_verdict(-885, 885) == decode.pwm_verdict(885, 885)

    def test_no_verdict_without_the_limit(self):
        assert "no verdict" in decode.pwm_verdict(500, None)
        assert "no verdict" in decode.pwm_verdict(500, 0)


class TestTemperatureVerdict:
    def test_too_few_samples(self):
        assert "Not enough" in decode.temperature_verdict([])
        assert "Not enough" in decode.temperature_verdict([30])

    def test_climbing_warns(self):
        assert "kept climbing" in decode.temperature_verdict([29, 32, 36, 41])

    def test_steady_is_fine(self):
        assert "held steady" in decode.temperature_verdict([29, 30, 31, 32])

    def test_none_samples_are_skipped(self):
        assert "held steady" in decode.temperature_verdict([29, None, 32])


class TestDiffVerdict:
    def test_small_offset_is_normal(self):
        assert "normal" in decode.diff_verdict(12)
        assert "normal" in decode.diff_verdict(-50)

    def test_offsets_seen_on_a_working_arm_are_normal(self):
        # 2:12 read 91 to 105 in every session and teleoperation still worked.
        assert "normal" in decode.diff_verdict(99)
        assert "normal" in decode.diff_verdict(-105)

    def test_medium_offset_is_the_zero_point(self):
        text = decode.diff_verdict(230)
        assert "zero point" in text
        assert "section 3" in text

    def test_large_offset_is_the_assembly(self):
        text = decode.diff_verdict(2048)
        assert "assembled" in text
        assert "4.3" in text

    def test_degrees_are_reported(self):
        assert "90" in decode.diff_verdict(1024)

    def test_read_failure(self):
        assert "nothing to compare" in decode.diff_verdict(None)


class TestRangeVerdict:
    def test_normal_range(self):
        assert "750" in decode.range_verdict(2123, 2873)

    def test_inverted_range(self):
        assert "Measure again" in decode.range_verdict(2873, 2123)

    def test_range_too_narrow(self):
        assert "all the way" in decode.range_verdict(2000, 2010)

    def test_range_beyond_the_resolution(self):
        assert "outside" in decode.range_verdict(0, ENCODER_RESOLUTION + 100)

    def test_no_measurement(self):
        assert "No measurement" in decode.range_verdict(None, 100)

    def test_a_joint_that_did_not_move(self):
        assert "did not move" in decode.range_verdict(2048, 2048)

    def test_the_boundary_points_to_reassembly(self):
        assert "4.3" in decode.range_verdict(-51, 4045)


class TestRangeUsable:
    def test_normal_range(self):
        assert decode.range_usable(2123, 2873)

    def test_noise_is_not_usable(self):
        assert not decode.range_usable(2047, 2049)

    def test_beyond_the_boundary_is_not_usable(self):
        assert not decode.range_usable(-51, 4045)

    def test_no_measurement_is_not_usable(self):
        assert not decode.range_usable(None, 2048)


class TestBoundary:
    def test_middle_of_the_range(self):
        assert not decode.near_boundary(2048)

    def test_readings_from_the_session(self):
        for position in (7, 0, -149, 3947, 4146):
            assert decode.near_boundary(position)

    def test_pair_verdict(self):
        assert decode.boundary_verdict(2039, 1999) is None
        assert "4.3" in decode.boundary_verdict(3947, 7)
