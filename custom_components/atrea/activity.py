"""Recover forced-input activity from the controller's retained H10712 log."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, timedelta
from typing import Any

import requests
from homeassistant.const import CONF_IP_ADDRESS, EVENT_LOGBOOK_ENTRY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN, LOGGER

LOG_REGISTER = "H10712"
INPUT_REGISTERS = {f"D{i + 1}": f"D1020{i}" for i in range(4)}
POLL_INTERVAL = timedelta(seconds=30)
INITIAL_LOOKBACK_SECONDS = 600
MAX_DAYS_PER_POLL = 3


def parse_samples(value: str) -> list[tuple[int, int]]:
    """Preserve log order, including same-second changes and clock adjustments."""
    samples = []
    for item in value.split(";"):
        if not item:
            continue
        seconds, raw = item.split(",", maxsplit=1)
        sample = int(seconds), int(raw)
        if not 0 <= sample[0] < 86400:
            raise ValueError("Invalid time in Atrea log")
        samples.append(sample)
    return samples


def input_for_mode(value: int, supported: dict[int, Any]) -> str | None:
    mode = supported.get(value)
    name = getattr(mode, "name", "").upper()
    return name if name in INPUT_REGISTERS else None


def fetch_log(atrea: Any, day: date | None) -> Any:
    """Read log dates or one day's samples using the existing controller session."""
    query = "type=0" if day is None else f"type=1&date={day:%Y%m%d}"
    response = requests.get(atrea.getURL(f"config/log.cgi?{query}"), timeout=15)
    response.raise_for_status()
    if day is None:
        return sorted({datetime.strptime(line.strip(), "%Y%m%d").date()
                       for line in response.text.splitlines() if line.strip()})
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get(LOG_REGISTER), str):
        raise ValueError("H10712 is not available in the controller log")
    return parse_samples(payload[LOG_REGISTER])


def _entity_id(hass: HomeAssistant, ip: str, register: str) -> str | None:
    unique_id = slugify(f"{slugify(f'atrea_{ip}')}_{register}")
    return er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, unique_id)


class ActivityLog:
    """Track retained transitions; never change input states or send commands."""

    def __init__(self, hass: HomeAssistant, entry: Any, atrea: Any, data: dict) -> None:
        self.hass, self.entry, self.atrea, self.data = hass, entry, atrea, data
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_activity")
        self.cursor: dict = {}
        self._task: asyncio.Task | None = None
        self._unsub = None
        self._stopped = False
        self._lock = asyncio.Lock()

    async def async_start(self) -> None:
        self.cursor = await self.store.async_load() or {}
        self._unsub = async_track_time_interval(self.hass, self._schedule, POLL_INTERVAL)
        self._schedule()

    @callback
    def _schedule(self, _now=None) -> None:
        if not self._stopped and (self._task is None or self._task.done()):
            self._task = self.hass.async_create_task(self.async_poll())

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def async_poll(self) -> None:
        async with self._lock:
            if self._stopped:
                return
            try:
                await self._poll()
            except (requests.RequestException, ValueError, TypeError):
                # Unsupported controllers and transient/auth failures are retried;
                # neither can advance the cursor or affect normal status polling.
                LOGGER.debug("Unable to read Atrea input history", exc_info=True)

    async def _poll(self) -> None:
        timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        now = dt_util.now(timezone)
        today = now.date()
        saved_day = date.fromisoformat(self.cursor["date"]) if self.cursor else today
        days = [today]
        if saved_day < today:
            available = await self.hass.async_add_executor_job(fetch_log, self.atrea, None)
            days = sorted({day for day in available if saved_day <= day <= today} | {today})
        supported = dict(self.data.get("supportedForcedModes") or [])
        if not supported:
            return
        for day in days[:MAX_DAYS_PER_POLL]:
            samples = await self.hass.async_add_executor_job(fetch_log, self.atrea, day)
            if self._stopped or not samples:
                return
            same_day = self.cursor.get("date") == day.isoformat()
            start = 0
            if same_day and "position" in self.cursor:
                start = self.cursor["position"]
                # A rewritten/truncated log cannot be safely replayed. Retry until
                # it matches rather than inventing duplicate activations.
                if start > len(samples) or (start and list(samples[start - 1]) != self.cursor["sample"]):
                    LOGGER.warning("Atrea history changed before its saved cursor for %s", day)
                    return
            elif same_day:
                # Migrate the earlier seconds-only cursor without replaying it.
                while start < len(samples) and samples[start][0] <= self.cursor.get("seconds", -1):
                    start += 1
            elif not self.cursor:
                cutoff = now.hour * 3600 + now.minute * 60 + now.second - INITIAL_LOOKBACK_SECONDS
                while start < len(samples) and samples[start][0] < cutoff:
                    start += 1
            previous = samples[start - 1][1] if start else None
            for index in range(start, len(samples)):
                seconds, value = samples[index]
                input_name = input_for_mode(value, supported)
                # The first midnight row is a snapshot, not an input activation.
                if input_name and value != previous and not (index == 0 and seconds == 0):
                    entity_id = _entity_id(self.hass, self.entry.data.get(CONF_IP_ADDRESS, ""), INPUT_REGISTERS[input_name])
                    if entity_id is None:
                        # Save earlier rows, but retry this one after discovery.
                        if index:
                            await self._save(day, index, samples[index - 1])
                        return
                    state = self.hass.states.get(entity_id)
                    name = state.attributes.get("friendly_name") if state else None
                    when = datetime.combine(day, datetime.min.time()) + timedelta(seconds=seconds)
                    self.hass.bus.async_fire(EVENT_LOGBOOK_ENTRY, {
                        "name": name or f"{input_name} input",
                        "message": f"became the forced operating source at {when:%Y-%m-%d %H:%M:%S} (controller local time)",
                        "entity_id": entity_id,
                    })
                previous = value
            await self._save(day, len(samples), samples[-1])

    async def _save(self, day: date, position: int, sample: tuple[int, int]) -> None:
        cursor = {"date": day.isoformat(), "position": position, "sample": list(sample)}
        if cursor != self.cursor:
            await self.store.async_save(cursor)
            self.cursor = cursor
