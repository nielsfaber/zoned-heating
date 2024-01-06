"""Config flow for the Zoned Heating component."""
import secrets
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import (
    ATTR_MIN_TEMP,
    ATTR_MAX_TEMP
)
from homeassistant.const import Platform
from . import const

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=const.DOMAIN):
    """Config flow for Zoned Heating."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""

        _LOGGER.debug("async_step_user")

        # Only a single instance of the integration
        # if self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        id = secrets.token_hex(6)

        await self.async_set_unique_id(id)
        self._abort_if_unique_id_configured(updates=user_input)

        return self.async_create_entry(title=const.NAME, data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Zoned Heating."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

        self.controller = None
        self.zones = None
        self.max_setpoint = None
        self.controller_delay_time = None

    async def async_step_init(self, user_input=None):
        """Handle options flow."""

        if user_input is not None:
            self.controller = user_input.get(const.CONF_CONTROLLER)
            return await self.async_step_zones()

        all_climates = [
            climate
            for climate in self.hass.states.async_entity_ids("climate")
        ]
        all_switches = [
            switch
            for switch in self.hass.states.async_entity_ids("switch")
        ]
        controller_options = sorted(all_climates) + sorted(all_switches)

        default = self.config_entry.options.get(const.CONF_CONTROLLER)
        if default not in controller_options:
            default = None

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        const.CONF_CONTROLLER,
                        default=default
                    ): vol.In(controller_options)
                }
            )
        )

    async def async_step_zones(self, user_input=None):
        """Handle options flow."""

        if user_input is not None:
            self.zones = user_input.get(const.CONF_ZONES)
            return await self.async_step_max_setpoint()

        zone_options = [
            climate
            for climate in self.hass.states.async_entity_ids("climate")
            if climate != self.controller
        ]

        default = [
            climate
            for climate in self.config_entry.options.get(const.CONF_ZONES, [])
            if climate in zone_options
        ]

        return self.async_show_form(
            step_id=const.CONF_ZONES,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        const.CONF_ZONES,
                        default=default
                    ): vol.All(
                        cv.multi_select(sorted(zone_options)),
                        vol.Length(min=1),
                    ),
                }
            )
        )

    async def async_step_max_setpoint(self, user_input=None):
        """Handle options flow."""

        if user_input is not None:
            self.max_setpoint = user_input.get(const.CONF_MAX_SETPOINT)
            return await self.async_step_controller_delay_time()

        controller_state = self.hass.states.get(self.controller)
        min_temp = 0
        max_temp = 100
        if self.controller.startswith(Platform.CLIMATE):
            min_temp = round(controller_state.attributes.get(ATTR_MIN_TEMP))
            max_temp = round(controller_state.attributes.get(ATTR_MAX_TEMP))

        default = self.config_entry.options.get(const.CONF_MAX_SETPOINT)
        if not default or default < min_temp or default > max_temp:
            default = round((min_temp + max_temp)/2)

        return self.async_show_form(
            step_id=const.CONF_MAX_SETPOINT,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        const.CONF_MAX_SETPOINT,
                        default=const.DEFAULT_MAX_SETPOINT
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=min_temp, max=max_temp)
                    )
                }
            )
        )

    async def async_step_controller_delay_time(self, user_input=None):
        """Handle options flow."""

        if user_input is not None:
            self.controller_delay_time = user_input.get(const.CONF_CONTROLLER_DELAY_TIME)

            return self.async_create_entry(title="", data={
                const.CONF_ZONES: self.zones,
                const.CONF_CONTROLLER: self.controller,
                const.CONF_MAX_SETPOINT: self.max_setpoint,
                const.CONF_CONTROLLER_DELAY_TIME: self.controller_delay_time,
            })

        default = self.config_entry.options.get(const.CONF_CONTROLLER_DELAY_TIME)
        if not default:
            default = const.DEFAULT_CONTROLLER_DELAY_TIME

        return self.async_show_form(
            step_id=const.CONF_CONTROLLER_DELAY_TIME,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        const.CONF_CONTROLLER_DELAY_TIME,
                        default=default
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=10, max=300)
                    )
                }
            )
        )
