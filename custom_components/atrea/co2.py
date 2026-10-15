"""Opt-in, installation-specific analog CO2 calibration."""

from math import isfinite

CONF_CO2_INPUTS = "co2_inputs"
CO2_REGISTERS = {"in1": "I10205", "in2": "I10206"}


def calibration(options, input_key):
    """Return valid calibration, or None for an unconfigured input."""
    try:
        settings = options[CONF_CO2_INPUTS][input_key]
        slope, offset = float(settings["slope"]), float(settings["offset"])
        if isfinite(slope) and slope > 0 and isfinite(offset):
            return slope, offset
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def co2_value(raw_millivolts, coefficients):
    """Convert valid voltage to whole ppm, truncating like a HA int template."""
    if coefficients is None or raw_millivolts is None:
        return None
    try:
        # RD5 IN1/IN2 range: 0..12 V. Reject disconnected/error sentinel codes.
        millivolts = int(raw_millivolts)
        if not 0 <= millivolts <= 12000:
            return None
        slope, offset = coefficients
        ppm = millivolts / 1000 * slope + offset
        return int(ppm) if isfinite(ppm) and ppm >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None
