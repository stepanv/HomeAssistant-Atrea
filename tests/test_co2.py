"""Calibrated analog CO2: opt-in configuration, lifecycle and legacy parity."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.atrea.co2 import calibration, co2_value
from custom_components.atrea.config_flow import AtreaOptionsFlowHandler
from custom_components.atrea.sensor import AtreaCO2Sensor, async_setup_entry


def context(options=None, status=None):
    listeners = []
    coordinator = SimpleNamespace(last_update_success=True, config_entry=None,
        async_add_listener=lambda fn: (listeners.append(fn) or (lambda: None)),
        async_update_listeners=lambda: [fn() for fn in listeners])
    entry = SimpleNamespace(entry_id="test", data={"ip_address": "192.0.2.1"},
        options=options or {}, async_on_unload=Mock(), add_update_listener=Mock(return_value=lambda: None))
    data = {"status": status or {"I10205": "4680", "I10206": "3470"}, "coordinator": coordinator}
    return entry, data


def configured():
    return {"co2_inputs": {"in1": {"slope": 200, "offset": 100}, "in2": {"slope": 200, "offset": 100}}}


@pytest.mark.parametrize("raw,expected", [("0",100),("4680",1036),("3470",794),("3504",800),
    ("10000",2100),("12000",2500),(None,None),("",None),("bad",None),("nan",None),
    (float("inf"),None),("65535",None),("-1",None),("12001",None)])
def test_empirical_calibration_and_invalid_readings(raw, expected):
    entry, data = context(configured())
    entity = AtreaCO2Sensor(entry, data, "in1")
    data["status"]["I10205"] = raw
    assert entity.native_value == expected
    assert entity.available == (expected is not None)
    assert entity.device_class == SensorDeviceClass.CO2
    assert entity.native_unit_of_measurement == "ppm"
    assert entity.state_class == "measurement"
    assert entity.unique_id == "atrea_192_0_2_1_in1_co2"
    assert entity.entity_registry_enabled_default


@pytest.mark.asyncio
async def test_conversion_matches_existing_yaml_template(tmp_path):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.template import Template
    hass = HomeAssistant(str(tmp_path))
    try:
        template = Template("{{ (value * 200 + 100) | int }}", hass)
        for raw in [0, 1, 3470, 3504, 4680, 4999, 10000, 12000]:
            assert co2_value(raw, (200, 100)) == template.async_render({"value": raw / 1000})
    finally:
        await hass.async_stop(force=True)


@pytest.mark.parametrize("slope,offset", [(0,0),(-1,0),(float("nan"),0),(float("inf"),0),(1,float("inf")),(1,None)])
def test_invalid_calibration_rejected(slope,offset):
    assert calibration({"co2_inputs":{"in1":{"slope":slope,"offset":offset}}},"in1") is None


def test_negative_result_missing_register_and_poll_failure():
    entry,data=context(configured())
    entity=AtreaCO2Sensor(entry,data,"in1")
    entry.options={"co2_inputs":{"in1":{"slope":10,"offset":-100}}}
    assert entity.native_value is None and not entity.available
    entry.options=configured()
    data["status"]={}
    assert not entity.available
    data["status"]={"I10205":"1000"}
    data["coordinator"].last_update_success=False
    assert not entity.available


@pytest.mark.asyncio
async def test_opt_in_reconfiguration_disable_reenable_and_voltage_preserved():
    entry,data=context()
    hass=SimpleNamespace(data={"atrea":{"test":data}})
    entities=[]
    await async_setup_entry(hass,entry,entities.extend)
    assert [e.name for e in entities] == ["IN1 voltage","IN2 voltage"]
    changed=entry.add_update_listener.call_args.args[0]
    entry.options=configured()
    await changed(hass,entry)
    assert len(entities)==4
    in1,in2=entities[2:]
    assert (in1.native_value,in2.native_value)==(1036,794)
    entry.options={"co2_inputs":{"in1":{"slope":100,"offset":-10}}}
    await changed(hass,entry)
    assert in1.native_value==458 and not in2.available
    assert entities[0].native_value==4.68 and entities[1].native_value==3.47
    entry.options=configured()
    await changed(hass,entry)
    assert len(entities)==4 and in2.available
    assert in1.unique_id=="atrea_192_0_2_1_in1_co2"


@pytest.mark.asyncio
async def test_options_flow_validation_and_preservation():
    entry,_=context({"unrelated":"keep"})
    flow=AtreaOptionsFlowHandler(entry)
    # Exercise the actual step without a network client or config entry writes.
    flow.async_show_form=Mock(side_effect=lambda **kwargs: kwargs)
    flow.async_create_entry=Mock(side_effect=lambda **kwargs: kwargs)
    empty=await flow.async_step_co2()
    assert empty["data_schema"]({}) == {"in1_enabled":False,"in2_enabled":False}
    bad=await flow.async_step_co2({"in1_enabled":True,"in1_slope":200})
    assert bad["errors"]=={"base":"invalid_co2_calibration"}
    valid=await flow.async_step_co2({"in1_enabled":True,"in1_slope":200,"in1_offset":100,
                                    "in2_enabled":True,"in2_slope":150,"in2_offset":50})
    assert valid["data"]=={"unrelated":"keep","co2_inputs":{
        "in1":{"slope":200,"offset":100},"in2":{"slope":150,"offset":50}}}
    assert entry.options=={"unrelated":"keep"}


@pytest.mark.asyncio
async def test_native_registry_identity_can_take_over_unregistered_template_id(tmp_path):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er, device_registry as dr
    hass=HomeAssistant(str(tmp_path))
    dr.async_setup(hass)
    await dr.async_load(hass, load_empty=True)
    registry=er.async_get(hass)
    await registry.async_load(load_empty=True)
    entry,data=context(configured())
    entity=AtreaCO2Sensor(entry,data,"in1")
    old_id="sensor.room_a_co2"
    try:
        hass.states.async_set(old_id,"1036",{"unit_of_measurement":"ppm","device_class":"carbon_dioxide","state_class":"measurement"})
        native=registry.async_get_or_create("sensor","atrea",entity.unique_id,suggested_object_id="atrea_in1_co2")
        # Template reload removes the old state; the native registry entry then takes its exact ID.
        hass.states.async_remove(old_id)
        registry.async_update_entity(native.entity_id,new_entity_id=old_id,name="Room A CO₂")
        assert registry.async_get_entity_id("sensor","atrea",entity.unique_id)==old_id
        assert registry.async_get(old_id).name=="Room A CO₂"
        assert entity.native_unit_of_measurement=="ppm" and entity.state_class=="measurement"
    finally:
        await hass.async_stop(force=True)
