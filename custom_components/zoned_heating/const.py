"""Store constants."""

VERSION = "1.1.2"
DOMAIN = "zoned_heating"
NAME = "Zoned Heating"
DATA = "data"
UPDATE_LISTENER = "update_listener"

CONF_CONTROLLER = "controller"
CONF_ZONES = "zones"
CONF_MAX_SETPOINT = "max_setpoint"
CONF_CONTROLLER_DELAY_TIME = "controller_delay_time"

DEFAULT_MAX_SETPOINT = 21
DEFAULT_CONTROLLER_DELAY_TIME = 10

ATTR_OVERRIDE_ACTIVE = "override_active"
ATTR_TEMPERATURE_INCREASE = "temperature_increase"
ATTR_STORED_CONTROLLER_STATE = "stored_controller_state"
ATTR_STORED_CONTROLLER_SETPOINT = "stored_controller_setpoint"
