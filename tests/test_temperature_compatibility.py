"""Construct real climate entities for logical, physical, and legacy registers."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyatrea import Atrea, AtreaMode

from custom_components.atrea.climate import AtreaDevice


def climate_for(status):
    unit = Atrea("192.0.2.1")
    unit.status = {"I00020": "2", "I00021": "3", "I00022": "41", **status}
    unit.params = {
        "ids": [], "coefs": {"I00200": 10, "I00202": 10, "I00210": 10},
        "offsets": {}, "warning": [], "alert": [],
    }
    unit.writable_modes = {AtreaMode.OFF: True, AtreaMode.VENTILATION: True}
    unit.idsToModes = {0: AtreaMode.OFF, 2: AtreaMode.VENTILATION}
    unit.forcedModes = {0: AtreaMode.OFF}
    data = {
        "atrea": unit, "status": unit.status, "params": unit.params,
        "model": {"category": "Test", "model": "Ventilation unit"},
        "coordinator": Mock(), "userLabels": {},
        "supportedModes": unit.writable_modes.items(),
    }
    entry = SimpleNamespace(entry_id="test", data={"ip_address": "192.0.2.1"})
    hass = SimpleNamespace(data={"atrea": {"test": data}})
    return AtreaDevice(hass, entry, "Atrea", "20,50,100", {"Off": True, "Ventilation": True})


@pytest.mark.parametrize("selector,expected", [(0, 22.3), (1, 23.1)])
def test_rd5_without_logical_temperature_registers(selector, expected):
    device = climate_for({
        "H10700": "0", "H10705": "2", "H10714": "50",
        "H10514": str(selector), "I10203": "231", "I10207": "223", "I10200": "195",
    })
    assert device.current_temperature == expected
    assert device.extra_state_attributes["supply_air_temp"] == 19.5


def test_rd4_temperature_registers_are_still_supported():
    device = climate_for({
        "H01015": "1", "H01000": "2", "H01005": "50", "H01001": "50",
        "I00210": "234", "I00200": "198", "I00202": "45",
    })
    assert device.current_temperature == 23.4
    assert device.extra_state_attributes["supply_air_temp"] == 19.8
    assert device.extra_state_attributes["outside_temp"] == 4.5


def test_logical_temperatures_take_precedence_on_rk5():
    device = climate_for({
        "H10700": "0", "H10705": "2", "H10714": "33",
        "I10215": "225", "I10212": "211", "I10211": "65511",
        "H10514": "1", "I10203": "231", "I10207": "223", "I10200": "195",
    })
    assert device.current_temperature == 22.5
    assert device.extra_state_attributes["supply_air_temp"] == 21.1
    assert device.extra_state_attributes["outside_temp"] == -2.5


@pytest.mark.parametrize("effective", [0, 1, 3, 4])
def test_preset_keeps_requested_automatic_during_effective_override(effective):
    device = climate_for({
        "H10700": "0", "H10705": str(effective), "H10715": "1",
        "H10714": "33", "H10712": "0", "D10200": "0",
    })
    assert device.preset_mode == "Automatic"
    assert device._current_preset == AtreaMode(effective)
    # The physical contact can already be released while the override continues.
    device.data["status"]["H10705"] = "3"
    device.manualUpdate(False)
    assert device.preset_mode == "Automatic"
    device.data["status"]["H10715"] = "4"
    device.manualUpdate(False)
    assert device.preset_mode == "Circulation"


@pytest.mark.parametrize("invalid", [None, "", "invalid", "65535", "-1"])
def test_invalid_requested_preset_does_not_show_effective_mode(invalid):
    device = climate_for({
        "H10700": "0", "H10705": "3", "H10715": invalid, "H10714": "33",
    })
    assert device.preset_mode is None


@pytest.mark.parametrize("status", [
    {"H10700": "0", "H10705": "2", "H10714": "50"},
    {"H01015": "1", "H01000": "2", "H01005": "50", "H01001": "50"},
])
def test_legacy_preset_without_requested_register(status):
    assert climate_for(status).preset_mode == "Ventilation"
