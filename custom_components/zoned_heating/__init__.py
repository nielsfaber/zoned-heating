"""The zoned_heating component."""
import logging

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from . import const

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    """Track states and offer events for sensors."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Zoned Heating integration from a config entry."""

    # _async_import_options_from_data_if_missing(hass, entry)

    update_listener = entry.add_update_listener(async_update_options)

    hass.data.setdefault(const.DOMAIN, {})
    hass.data[const.DOMAIN][entry.entry_id] = {
        const.UPDATE_LISTENER: update_listener,
    }

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, SWITCH_DOMAIN)
    )
    return True


async def async_update_options(hass, config_entry: ConfigEntry):
    """Update options."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass, entry):
    """Unload Zoned Heating config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, SWITCH_DOMAIN)

    hass.data[const.DOMAIN][entry.entry_id][const.UPDATE_LISTENER]()

    if unload_ok:
        hass.data[const.DOMAIN].pop(entry.entry_id)

    return unload_ok


@callback
def _async_import_options_from_data_if_missing(hass: HomeAssistant, entry: ConfigEntry):
    options = dict(entry.options)
    if const.CONF_CONTROLLER not in options:
        options[const.CONF_CONTROLLER] = None
        options[const.CONF_ZONES] = []
        options[const.CONF_MAX_SETPOINT] = None
        hass.config_entries.async_update_entry(entry, options=options)
