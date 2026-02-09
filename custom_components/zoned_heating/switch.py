import logging
import datetime
import homeassistant.util.dt as dt_util

from homeassistant import config_entries
from homeassistant.const import (
    STATE_ON,
    ATTR_TEMPERATURE,
    Platform,
)
from homeassistant.core import (
    HomeAssistant,
    callback
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import ToggleEntity

from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_HVAC_ACTION,
    HVACMode,
    HVACAction,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_TARGET_TEMP_STEP,
)
from . import const
from .util import (
    parse_state,
    async_set_hvac_mode,
    async_set_temperature,
    async_set_switch_state,
    compute_domain,
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch(es) for zoned heating platform."""

    controller = config_entry.options.get(const.CONF_CONTROLLER)
    zones = config_entry.options.get(const.CONF_ZONES, [])
    max_setpoint = config_entry.options.get(const.CONF_MAX_SETPOINT)
    controller_delay_time = config_entry.options.get(const.CONF_CONTROLLER_DELAY_TIME, const.DEFAULT_CONTROLLER_DELAY_TIME)
    hysteresis = config_entry.options.get(const.CONF_HYSTERESIS, config_entry.data.get(const.CONF_HYSTERESIS, const.DEFAULT_HYSTERESIS))

    async_add_entities([
        ZonedHeaterSwitch(hass, controller, zones, max_setpoint, controller_delay_time, hysteresis)
    ])


class ZonedHeaterSwitch(ToggleEntity, RestoreEntity):

    _attr_name = "Zoned Heating"

    def __init__(self, hass, controller_entity, zone_entities, max_setpoint, controller_delay_time, hysteresis):
        self.hass = hass
        self._controller_entity = controller_entity
        self._zone_entities = zone_entities
        self._max_setpoint = max_setpoint
        self._controller_delay_time = controller_delay_time
        self._hysteresis = hysteresis

        self._enabled = None
        self._state_listeners = []
        self._ignore_controller_state_change_timer = None
        self._override_active = False
        self._temperature_increase = 0
        self._stored_controller_setpoint = None
        self._stored_controller_state = None

        super().__init__()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        _LOGGER.debug("Registering entity %s", self.entity_id)

        state = await self.async_get_last_state()
        if state:
            _LOGGER.debug("Restored data prior to restart: %s", state.attributes)
            self._enabled = state.state == STATE_ON
            self._override_active = state.attributes.get(const.ATTR_OVERRIDE_ACTIVE)
            self._temperature_increase = state.attributes.get(const.ATTR_TEMPERATURE_INCREASE)
            self._stored_controller_setpoint = state.attributes.get(const.ATTR_STORED_CONTROLLER_SETPOINT)
            self._stored_controller_state = state.attributes.get(const.ATTR_STORED_CONTROLLER_STATE)
        else:
            self._enabled = True

        if self._enabled:
            await self.async_start_state_listeners()
        await self.async_calculate_override()

    async def async_will_remove_from_hass(self):
        """remove entity from hass."""
        await self.async_stop_state_listeners()

    @property
    def is_on(self):
        """Return true if entity is on."""
        return self._enabled

    @property
    def state_attributes(self):
        """Return the data of the entity."""
        return {
            const.CONF_CONTROLLER: self._controller_entity,
            const.CONF_ZONES: self._zone_entities,
            const.CONF_MAX_SETPOINT: self._max_setpoint,
            const.CONF_CONTROLLER_DELAY_TIME: self._controller_delay_time,
            const.CONF_HYSTERESIS: self._hysteresis,
            const.ATTR_OVERRIDE_ACTIVE: self._override_active,
            const.ATTR_TEMPERATURE_INCREASE: self._temperature_increase,
            const.ATTR_STORED_CONTROLLER_STATE: self._stored_controller_state,
            const.ATTR_STORED_CONTROLLER_SETPOINT: self._stored_controller_setpoint,
        }

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        if self._enabled:
            return
        self._enabled = True
        _LOGGER.debug("Zoned heating turned on")
        await self.async_start_state_listeners()
        await self.async_calculate_override()

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        if not self._enabled:
            return
        self._enabled = False
        _LOGGER.debug("Zoned heating turned off")
        await self.async_stop_state_listeners()
        await self.async_calculate_override()

    async def async_start_state_listeners(self):
        """start watching for state changes of controller / zone entities"""
        await self.async_stop_state_listeners()
        if not len(self._zone_entities) or not self._controller_entity:
            return
        self._state_listeners = [
            async_track_state_change_event(
                self.hass,
                self._controller_entity,
                self.async_controller_state_changed,
            ),
            async_track_state_change_event(
                self.hass,
                self._zone_entities,
                self.async_zone_state_changed,
            )
        ]
        _LOGGER.debug("Registered state listeners for controller=%s zones=%s", self._controller_entity, self._zone_entities)

    async def async_stop_state_listeners(self):
        """stop watching for state changes of controller / zone entities"""
        while len(self._state_listeners):
            self._state_listeners.pop()()

    async def async_controller_state_changed(self, event):
        """fired when controller entity changes"""
        if self._ignore_controller_state_change_timer or not self._override_active:
            return
        old_state = parse_state(event.data["old_state"])
        new_state = parse_state(event.data["new_state"])

        if new_state[ATTR_TEMPERATURE] != old_state[ATTR_TEMPERATURE]:
            # if controller setpoint has changed, make sure to store it
            _LOGGER.debug("Storing controller setpoint=%s", new_state[ATTR_TEMPERATURE])
            self._stored_controller_setpoint = new_state[ATTR_TEMPERATURE]
            self.async_write_ha_state()

        if new_state[ATTR_HVAC_MODE] != old_state[ATTR_HVAC_MODE] and new_state[ATTR_HVAC_MODE] == HVACMode.OFF:
            _LOGGER.debug("Controller was turned off, disable zones")
            await self.async_turn_off_zones()

    async def async_zone_state_changed(self, event):
        """fired when zone entity changes"""
        entity = event.data["entity_id"]
        old_state = parse_state(event.data["old_state"])
        new_state = parse_state(event.data["new_state"])

        _LOGGER.debug("Zone event received for %s: old=%s new=%s", entity, {
            "temp": old_state.get(ATTR_TEMPERATURE),
            "current": old_state.get(ATTR_CURRENT_TEMPERATURE),
            "action": old_state.get(ATTR_HVAC_ACTION),
        }, {
            "temp": new_state.get(ATTR_TEMPERATURE),
            "current": new_state.get(ATTR_CURRENT_TEMPERATURE),
            "action": new_state.get(ATTR_HVAC_ACTION),
        })

        # Re-evaluate override when either the target setpoint or the current
        # measured temperature changes for a zone. This ensures drops in room
        # temperature trigger an evaluation even if the setpoint hasn't moved.
        if (
            (old_state[ATTR_TEMPERATURE] != new_state[ATTR_TEMPERATURE] or
             old_state[ATTR_CURRENT_TEMPERATURE] != new_state[ATTR_CURRENT_TEMPERATURE]) and
            isinstance(new_state[ATTR_TEMPERATURE], (int, float)) and
            isinstance(new_state[ATTR_CURRENT_TEMPERATURE], (int, float))
        ):
            if old_state[ATTR_TEMPERATURE] != new_state[ATTR_TEMPERATURE]:
                _LOGGER.debug("Zone %s updated: setpoint=%s", entity, new_state[ATTR_TEMPERATURE])
            if old_state[ATTR_CURRENT_TEMPERATURE] != new_state[ATTR_CURRENT_TEMPERATURE]:
                _LOGGER.debug("Zone %s updated: current=%s", entity, new_state[ATTR_CURRENT_TEMPERATURE])
            await self.async_calculate_override()

        if old_state[ATTR_HVAC_ACTION] != new_state[ATTR_HVAC_ACTION] or old_state[ATTR_HVAC_MODE] != new_state[ATTR_HVAC_MODE]:
            # action or mode of a zone was updated, check whether controller needs to be updated
            _LOGGER.debug("Zone %s updated: action=%s", entity, new_state[ATTR_HVAC_ACTION])
            await self.async_calculate_override()

    async def async_calculate_override(self):
        """calculate whether override should be active and determine setpoint"""
        states = [
            parse_state(self.hass.states.get(entity))
            for entity in self._zone_entities
        ]

        # Diagnostic: build a compact view of zones for logging to aid debugging
        try:
            zone_debug = [
                {
                    "entity": entity,
                    "temp": state.get(ATTR_TEMPERATURE),
                    "current": state.get(ATTR_CURRENT_TEMPERATURE),
                    "mode": state.get(ATTR_HVAC_MODE),
                    "action": state.get(ATTR_HVAC_ACTION),
                }
                for entity, state in zip(self._zone_entities, states)
            ]
        except Exception:
            zone_debug = None
        _LOGGER.debug("Hysteresis calc: enabled=%s hysteresis=%s zones=%s", self._enabled, self._hysteresis, zone_debug)

        # Compute how much each zone would need to increase to reach its
        # target setpoint. Consider zones where the HVAC mode is not OFF
        # (so heat/auto modes are included). We deliberately ignore the
        # `hvac_action` because some TRVs report `idle` even when in heat
        # mode due to their internal hysteresis.
        temperature_increase_per_state = []
        for state in states:
            t = state.get(ATTR_TEMPERATURE)
            cur = state.get(ATTR_CURRENT_TEMPERATURE)
            if (
                isinstance(t, (int, float)) and
                isinstance(cur, (int, float)) and
                state.get(ATTR_HVAC_MODE) != HVACMode.OFF
            ):
                try:
                    temperature_increase_per_state.append(float(t) - float(cur))
                except Exception:
                    continue

        override_active = False
        temperature_increase = 0

        if len(temperature_increase_per_state) and self._enabled:
            temperature_increase = round(max(temperature_increase_per_state), 1)
            # Only activate override when the required increase exceeds configured hysteresis
            try:
                hysteresis = float(self._hysteresis or 0)
            except Exception:
                hysteresis = float(const.DEFAULT_HYSTERESIS)
            override_active = temperature_increase > hysteresis

        if (not self._override_active and not override_active) or (
            self._temperature_increase == temperature_increase and
            override_active == self._override_active
        ):
            # nothing to do
            return

        _LOGGER.debug(
            "Updated override temperature_increase=%s, override_active=%s",
            temperature_increase,
            override_active,
        )

        if override_active and not self._override_active:
            await self.async_start_override_mode(temperature_increase)
        elif not override_active and self._override_active:
            await self.async_stop_override_mode()
        else:
            await self.async_update_override_setpoint(temperature_increase)

        self.async_write_ha_state()

    async def async_start_override_mode(self, temperature_increase: float):
        """Start the override of the controller"""

        self._override_active = True
        current_state = parse_state(self.hass.states.get(self._controller_entity))
        # store current controller entity settings for later
        _LOGGER.debug("Storing controller state=%s", current_state)
        self._stored_controller_state = current_state[ATTR_HVAC_MODE]
        self._stored_controller_setpoint = current_state[ATTR_TEMPERATURE]

        if current_state[ATTR_HVAC_MODE] != HVACMode.HEAT:
            # uupdate to heat mode if needed
            await self._ignore_controller_state_changes()
            if compute_domain(self._controller_entity) == Platform.CLIMATE:
                await async_set_hvac_mode(self.hass, self._controller_entity, HVACMode.HEAT)
            elif compute_domain(self._controller_entity) == Platform.SWITCH:
                await async_set_switch_state(self.hass, self._controller_entity, STATE_ON)

        await self.async_update_override_setpoint(temperature_increase)

    async def async_stop_override_mode(self):
        """Stop the override of the controller and revert its prior settings"""
        if not self._override_active:
            return

        _LOGGER.debug("Stopping override mode")
        self._override_active = False
        self._temperature_increase = 0

        current_state = parse_state(self.hass.states.get(self.entity_id))

        if current_state[ATTR_HVAC_MODE] != self._stored_controller_state and self._stored_controller_state is not None:
            if compute_domain(self._controller_entity) == Platform.CLIMATE:
                await async_set_hvac_mode(self.hass, self._controller_entity, self._stored_controller_state)
            elif compute_domain(self._controller_entity) == Platform.SWITCH:
                await async_set_switch_state(self.hass, self._controller_entity, self._stored_controller_state)

        if (
            current_state[ATTR_TEMPERATURE] != self._stored_controller_setpoint and
            isinstance(self._stored_controller_setpoint, float) and
            compute_domain(self._controller_entity) == Platform.CLIMATE
        ):
            await async_set_temperature(self.hass, self._controller_entity, self._stored_controller_setpoint)

        self._stored_controller_setpoint = None
        self._stored_controller_state = None

    async def async_update_override_setpoint(self, temperature_increase: float):
        """Update the override setpoint of the controller"""

        self._temperature_increase = temperature_increase

        controller_setpoint = 0
        if (
            self._stored_controller_state == HVACMode.HEAT and
            isinstance(self._stored_controller_setpoint, float)
         ):
            controller_setpoint = self._stored_controller_setpoint

        controller_state = self.hass.states.get(self._controller_entity)
        current_state = parse_state(controller_state)
        override_setpoint = 0

        if isinstance(current_state[ATTR_CURRENT_TEMPERATURE], (int, float)):
            override_setpoint = min([
                current_state[ATTR_CURRENT_TEMPERATURE] + temperature_increase,
                self._max_setpoint
            ])
        # else:
            # TBD: mirror setpoint of zone to controller

        new_setpoint = max([override_setpoint, controller_setpoint])

        if (
            new_setpoint != current_state[ATTR_TEMPERATURE] and
            compute_domain(self._controller_entity) == Platform.CLIMATE
        ):
            setpoint_resolution = controller_state.attributes.get(ATTR_TARGET_TEMP_STEP, 0.5)
            new_setpoint = round(new_setpoint / setpoint_resolution) * setpoint_resolution
            _LOGGER.debug("Updating override setpoint=%s (current controller setpoint=%s)", new_setpoint, current_state[ATTR_TEMPERATURE])
            await self._ignore_controller_state_changes()
            try:
                await async_set_temperature(self.hass, self._controller_entity, new_setpoint)
                # Read back controller state immediately and log its setpoint
                try:
                    post_state = parse_state(self.hass.states.get(self._controller_entity))
                    _LOGGER.debug("Controller post-update setpoint=%s mode=%s action=%s", post_state.get(ATTR_TEMPERATURE), post_state.get(ATTR_HVAC_MODE), post_state.get(ATTR_HVAC_ACTION))
                except Exception:
                    _LOGGER.debug("Controller post-update read failed")
            except Exception as exc:
                _LOGGER.exception("Failed to set controller temperature to %s: %s", new_setpoint, exc)

    async def async_turn_off_zones(self):
        """turn off all zones"""
        entity_list = [
            entity
            for entity in self._zone_entities
            if parse_state(self.hass.states.get(entity))[ATTR_HVAC_MODE] == HVACMode.HEAT
        ]
        if not len(entity_list):
            return

        _LOGGER.debug("Turning off zones %s", ", ".join(entity_list))
        await async_set_hvac_mode(self.hass, entity_list, HVACMode.OFF)

    async def _ignore_controller_state_changes(self):
        """temporarily stop watching for state changes of the controller"""
        if self._ignore_controller_state_change_timer:
            self._ignore_controller_state_change_timer()

        _LOGGER.debug("start ignoring controller state changes")

        now = dt_util.utcnow()
        delay = datetime.timedelta(seconds=self._controller_delay_time)

        @callback
        async def timer_finished(now):
            _LOGGER.debug("stop ignoring controller state changes")
            self._ignore_controller_state_change_timer = None

        self._ignore_controller_state_change_timer = async_track_point_in_time(
            self.hass, timer_finished, now + delay
        )
