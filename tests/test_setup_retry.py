"""A powered-off unit must cause a retriable setup, not a permanent error."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from requests.exceptions import ConnectionError, Timeout
from homeassistant.exceptions import ConfigEntryNotReady
from custom_components.atrea import async_setup_entry


@pytest.fixture
def setup():
    unit = Mock()
    unit.getStatus.return_value = {'H10700': '0'}
    unit.getSupportedModes.return_value = {}
    unit.getSupportedForcedModes.return_value = {}
    unit.loadUserLabels.return_value = {}
    unit.getPowerModeOptions.return_value = {}
    entry = SimpleNamespace(entry_id='test', data={}, add_update_listener=Mock(), async_on_unload=Mock())
    hass = SimpleNamespace(data={},
        async_add_executor_job=AsyncMock(side_effect=lambda fn,*args: fn(*args)),
        async_create_task=AsyncMock(side_effect=lambda task: task),
        config_entries=SimpleNamespace(async_forward_entry_setups=Mock(return_value=True)))
    return hass, entry, unit


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [ConnectionError('unit offline'), Timeout('unit offline')])
async def test_unreachable_unit_requests_setup_retry(setup, error):
    hass, entry, unit = setup
    unit.getStatus.side_effect = error
    with patch('custom_components.atrea.Atrea',return_value=unit), patch('custom_components.atrea.DataUpdateCoordinator'):
        with pytest.raises(ConfigEntryNotReady) as exc:
            await async_setup_entry(hass,entry)
    assert exc.value.__cause__ is error
    hass.config_entries.async_forward_entry_setups.assert_not_called()
    entry.add_update_listener.assert_not_called()
    assert not hass.data


@pytest.mark.asyncio
async def test_setup_recovers_on_next_attempt(setup):
    hass, entry, unit = setup
    unit.getStatus.side_effect = [ConnectionError('unit offline'), {'H10700':'0'}]
    with patch('custom_components.atrea.Atrea',return_value=unit), patch('custom_components.atrea.DataUpdateCoordinator'):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass,entry)
        assert await async_setup_entry(hass,entry) is True
    hass.config_entries.async_forward_entry_setups.assert_called_once()
    entry.add_update_listener.assert_called_once()
    assert hass.data['atrea']['test']['status']=={'H10700':'0'}


@pytest.mark.asyncio
async def test_rejected_status_remains_retriable(setup):
    hass, entry, unit = setup
    unit.getStatus.return_value = False
    with patch('custom_components.atrea.Atrea',return_value=unit), patch('custom_components.atrea.DataUpdateCoordinator'):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass,entry)


@pytest.mark.asyncio
async def test_programming_error_is_not_misclassified_as_offline(setup):
    hass, entry, unit = setup
    unit.getStatus.side_effect = ValueError('invalid data')
    with patch('custom_components.atrea.Atrea',return_value=unit), patch('custom_components.atrea.DataUpdateCoordinator'):
        with pytest.raises(ValueError):
            await async_setup_entry(hass,entry)


@pytest.mark.asyncio
async def test_running_coordinator_recovers_without_reloading_entry(setup, tmp_path):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    hass, entry, unit = setup
    real_hass = HomeAssistant(str(tmp_path))
    def coordinator_factory(_hass, logger, **kwargs):
        return DataUpdateCoordinator(real_hass, logger, config_entry=None, **kwargs)
    try:
        with patch('custom_components.atrea.Atrea',return_value=unit), \
             patch('custom_components.atrea.DataUpdateCoordinator',side_effect=coordinator_factory):
            await async_setup_entry(hass,entry)
        coordinator = hass.data['atrea']['test']['coordinator']
        changes=[]
        unsubscribe=coordinator.async_add_listener(lambda: changes.append(coordinator.last_update_success))
        try:
            unit.getStatus.side_effect=ConnectionError('power lost')
            await coordinator.async_refresh()
            assert not coordinator.last_update_success
            unit.getStatus.side_effect=None
            unit.getStatus.return_value={'H10700':'1'}
            await coordinator.async_refresh()
            assert coordinator.last_update_success
            assert hass.data['atrea']['test']['status']=={'H10700':'1'}
            assert changes==[False,True]
            hass.config_entries.async_forward_entry_setups.assert_called_once()
        finally:
            unsubscribe()
    finally:
        await real_hass.async_stop()
