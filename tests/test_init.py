"""Tests for Bayrol Cloud integration setup (async_setup_entry).

These guard the setup retry behaviour: when the initial login or data fetch
fails (for example because DNS is not ready yet right after a reboot), setup
must raise ConfigEntryNotReady so Home Assistant retries with backoff, instead
of returning False and staying dead until the next manual restart.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bayrol_cloud import async_setup, async_setup_entry
from custom_components.bayrol_cloud.const import DOMAIN


@pytest.fixture(autouse=True)
def _mock_clientsession():
    """Avoid creating a real aiohttp session (the API is mocked anyway)."""
    with patch(
        "custom_components.bayrol_cloud.async_get_clientsession",
        return_value=MagicMock(),
    ):
        yield

ENTRY_DATA = {
    "username": "user@example.com",
    "password": "secret",
    "cid": "12345",
    "refresh_interval": 300,
}

POOL_DATA = {
    "pH": 7.2,
    "mV": 700.0,
    "T": 28.0,
    "status": "online",
    "pH_alarm": False,
    "mV_alarm": False,
    "T_alarm": False,
}


def _make_api(*, login=True, get_data=None, device_status=""):
    """Build a mocked BayrolPoolAPI with async methods."""
    api = MagicMock()
    api.debug_mode = False
    api.login = AsyncMock(return_value=login)
    api.get_data = AsyncMock(return_value=POOL_DATA if get_data is None else get_data)
    api.get_device_status = AsyncMock(return_value=device_status)
    return api


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="test")
    entry.add_to_hass(hass)
    return entry


async def test_setup_raises_not_ready_when_login_fails(hass: HomeAssistant) -> None:
    """Login never succeeds -> ConfigEntryNotReady, after exhausting retries."""
    api = _make_api(login=False)
    with patch("custom_components.bayrol_cloud.BayrolPoolAPI", return_value=api):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, _entry(hass))
    # It should have retried, not given up after a single attempt.
    assert api.login.await_count == 3


async def test_setup_raises_not_ready_when_no_initial_data(hass: HomeAssistant) -> None:
    """Login works but the first data fetch is empty -> ConfigEntryNotReady."""
    api = _make_api(login=True, get_data={})
    with patch("custom_components.bayrol_cloud.BayrolPoolAPI", return_value=api):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, _entry(hass))


async def test_setup_raises_not_ready_on_unexpected_error(hass: HomeAssistant) -> None:
    """An unexpected error during setup is wrapped as ConfigEntryNotReady."""
    api = _make_api(login=True)
    api.get_data = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("custom_components.bayrol_cloud.BayrolPoolAPI", return_value=api):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, _entry(hass))


async def test_setup_success(hass: HomeAssistant) -> None:
    """Happy path: coordinator is created, entry stored, platforms forwarded."""
    api = _make_api(login=True)
    entry = _entry(hass)
    await async_setup(hass, {})  # initialises hass.data[DOMAIN], as HA does at boot
    with patch("custom_components.bayrol_cloud.BayrolPoolAPI", return_value=api), patch.object(
        hass.config_entries, "async_forward_entry_setups", AsyncMock()
    ) as forward:
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.entry_id in hass.data[DOMAIN]
    assert "coordinator" in hass.data[DOMAIN][entry.entry_id]
    forward.assert_awaited_once()
