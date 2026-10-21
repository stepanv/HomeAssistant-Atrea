"""Regression tests for retained D1–D4 activity; no controller writes."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
import requests
from pyatrea import AtreaMode

from custom_components.atrea.activity import ActivityLog, fetch_log, parse_samples

MODULE = "custom_components.atrea.activity"
TODAY = date(2026, 10, 21)


@pytest.fixture
def reader():
    hass = NS(config=NS(time_zone="Europe/Prague"),
              bus=NS(async_fire=Mock()), states=NS(get=Mock(return_value=None)),
              async_add_executor_job=AsyncMock())
    entry = NS(entry_id="test", data={"ip_address": "192.0.2.1"})
    with patch(f"{MODULE}.Store"):
        obj = ActivityLog(hass, entry, Mock(), {
            "supportedForcedModes": [(3, AtreaMode.D1), (4, AtreaMode.D2),
                                     (5, AtreaMode.D3), (6, AtreaMode.D4)]})
    obj.store = NS(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))
    with patch(f"{MODULE}.dt_util.now", return_value=datetime(2026, 10, 21, 10, 1, tzinfo=ZoneInfo("Europe/Prague"))), patch(
        f"{MODULE}._entity_id", side_effect=lambda h, ip, reg: f"binary_sensor.{reg.lower()}"
    ):
        yield obj


def events(reader):
    return [call.args[1] for call in reader.hass.bus.async_fire.call_args_list]


def test_parser_preserves_same_second_and_clock_rollback():
    assert parse_samples("0,0;3600,3;3600,0;3500,4;") == [(0, 0), (3600, 3), (3600, 0), (3500, 4)]


@pytest.mark.parametrize("raw", ["broken;", "86400,3;", "-1,3;", "1,no;"])
def test_malformed_log_is_not_partially_consumed(raw):
    with pytest.raises(ValueError):
        parse_samples(raw)


@pytest.mark.asyncio
async def test_dynamic_mapping_all_inputs_and_current_event_timestamp(reader):
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3), (36001, 4), (36002, 5), (36003, 6)]
    await reader.async_poll()
    await reader.async_poll()
    assert [e["entity_id"] for e in events(reader)] == [f"binary_sensor.d1020{i}" for i in range(4)]
    assert "2026-10-21 10:00:00" in events(reader)[0]["message"]
    assert all("time_fired" not in c.kwargs for c in reader.hass.bus.async_fire.call_args_list)
    assert reader.store.async_save.await_count == 1


@pytest.mark.asyncio
async def test_midnight_snapshot_and_unchanged_values_are_not_activations(reader):
    reader.cursor = {"date": "2026-10-20", "seconds": 86399}
    reader.hass.async_add_executor_job.side_effect = [[date(2026, 10, 20)], [(0, 3)], [(0, 3), (36000, 3), (36001, 0), (36002, 3)]]
    await reader.async_poll()
    assert len(events(reader)) == 1
    assert "10:00:02" in events(reader)[0]["message"]


@pytest.mark.asyncio
async def test_multiday_outage_catches_up_in_bounded_batches(reader):
    reader.cursor = {"date": "2026-10-17", "seconds": 86399}
    available = [date(2026, 10, d) for d in range(17, 22)]
    async def fetch(fn, atrea, day):
        return available if day is None else [(0, 0), (36000, 3)]
    reader.hass.async_add_executor_job.side_effect = fetch
    await reader.async_poll()
    assert reader.cursor["date"] == "2026-10-19"
    await reader.async_poll()
    assert reader.cursor["date"] == "2026-10-21"
    assert len(events(reader)) == 4


@pytest.mark.asyncio
async def test_expired_days_are_skipped_using_controller_index(reader):
    reader.cursor = {"date": "2026-10-17", "seconds": 0}
    reader.hass.async_add_executor_job.side_effect = [[TODAY], [(0, 0), (36000, 3)]]
    await reader.async_poll()
    assert reader.cursor["date"] == TODAY.isoformat()
    assert len(events(reader)) == 1


@pytest.mark.asyncio
async def test_restart_and_same_second_appends_and_clock_rollback(reader):
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3)]
    await reader.async_poll()
    saved = dict(reader.cursor)
    reader.cursor = saved  # persisted cursor after restart
    reader.hass.async_add_executor_job.return_value += [(36000, 4), (35990, 5)]
    await reader.async_poll()
    assert len(events(reader)) == 3


@pytest.mark.asyncio
async def test_old_seconds_cursor_migrates_without_duplicates(reader):
    reader.cursor = {"date": TODAY.isoformat(), "seconds": 36000}
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3), (36001, 4)]
    await reader.async_poll()
    assert len(events(reader)) == 1
    assert reader.cursor["position"] == 3


@pytest.mark.asyncio
async def test_missing_entity_retried_without_replaying_earlier_events(reader):
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3), (36001, 4)]
    with patch(f"{MODULE}._entity_id", side_effect=["binary_sensor.d1", None]):
        await reader.async_poll()
    assert reader.cursor["position"] == 2
    await reader.async_poll()
    assert len(events(reader)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [requests.Timeout(), ValueError("unsupported")])
async def test_failure_keeps_cursor_and_retries(reader, error):
    reader.cursor = {"date": TODAY.isoformat(), "seconds": 35000}
    before = dict(reader.cursor)
    reader.hass.async_add_executor_job.side_effect = error
    await reader.async_poll()
    assert reader.cursor == before
    assert not events(reader)
    reader.hass.async_add_executor_job.side_effect = None
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3)]
    await reader.async_poll()
    assert len(events(reader)) == 1


@pytest.mark.asyncio
async def test_truncated_log_not_replayed(reader):
    reader.cursor = {"date": TODAY.isoformat(), "position": 2, "sample": [36000, 3]}
    reader.hass.async_add_executor_job.return_value = [(0, 0)]
    await reader.async_poll()
    assert reader.cursor["position"] == 2
    assert not events(reader)


@pytest.mark.asyncio
async def test_stop_cancels_inflight_poll_and_prevents_rescheduling(reader):
    started = asyncio.Event()
    async def fetch(*args):
        started.set()
        await asyncio.Event().wait()
    reader.hass.async_add_executor_job.side_effect = fetch
    reader.hass.async_create_task = asyncio.create_task
    reader._unsub = Mock()
    unsub = reader._unsub
    reader._schedule()
    await started.wait()
    task = reader._task
    reader._schedule()
    assert reader._task is task
    await reader.async_stop()
    reader._schedule()
    assert task.cancelled()
    unsub.assert_called_once()
    assert not events(reader)
    reader.store.async_save.assert_not_awaited()


def test_fetch_uses_read_endpoint_and_parses_available_dates():
    atrea = Mock()
    atrea.getURL.side_effect = lambda path: f"http://example.invalid/{path}"
    response = Mock(text="20261020\n20261021\n")
    response.json.return_value = {"H10712": "0,0;36000,3;"}
    with patch(f"{MODULE}.requests.get", return_value=response) as get:
        assert fetch_log(atrea, None) == [date(2026, 10, 20), TODAY]
        assert fetch_log(atrea, TODAY) == [(0, 0), (36000, 3)]
        assert all("config/log.cgi?type=" in c.args[0] for c in get.call_args_list)
        assert all(c.kwargs["timeout"] == 15 for c in get.call_args_list)


@pytest.mark.parametrize("payload", [{}, [], {"H10712": None}])
def test_unsupported_response_does_not_become_empty_success(payload):
    response = Mock()
    response.json.return_value = payload
    with patch(f"{MODULE}.requests.get", return_value=response), pytest.raises(ValueError):
        fetch_log(Mock(), TODAY)


@pytest.mark.asyncio
async def test_real_home_assistant_bus_uses_discovery_time(reader, tmp_path):
    from homeassistant.core import HomeAssistant, callback
    from homeassistant.const import EVENT_LOGBOOK_ENTRY
    from homeassistant.util import dt as dt_util

    hass = HomeAssistant(str(tmp_path))
    received = []

    @callback
    def receive(event):
        received.append(event)

    unsub = hass.bus.async_listen(EVENT_LOGBOOK_ENTRY, receive)
    reader.hass.bus = hass.bus
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3)]
    before = dt_util.utcnow().timestamp()
    await reader.async_poll()
    await hass.async_block_till_done()
    unsub()
    assert len(received) == 1
    assert received[0].time_fired_timestamp >= before
    assert "10:00:00" in received[0].data["message"]


@pytest.mark.asyncio
async def test_start_loads_persisted_cursor_before_polling(reader):
    saved = {"date": TODAY.isoformat(), "position": 2, "sample": [36000, 3]}
    reader.store.async_load.return_value = saved
    reader.hass.async_create_task = asyncio.create_task
    reader.hass.async_add_executor_job.return_value = [(0, 0), (36000, 3)]
    with patch(f"{MODULE}.async_track_time_interval", return_value=Mock()):
        await reader.async_start()
        await reader._task
        await reader.async_stop()
    assert reader.cursor == saved
    assert not events(reader)
