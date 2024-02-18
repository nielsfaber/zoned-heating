# zoned-heating

## Introduction
This is an integration for Home Assistant, which can be used to create a multi-zone heating system in your house.

It creates a 'link' between your main thermostat and smart radiator valves (TRVs). 

**Note:** This is a work-in-progress, so things may not work properly. Report issues when you find them.

## Installation
No HACS support yet, only manual installation is possible

1. Place files in `custom_components` folder.
2. Restart HA to load the custom component. 
3. In HA, go to Configuration -> Integrations and click 'add integration'. Look for Zoned Heating. If it does not appear, reload your browser cache.
4. Click the 'configure' button to start the configuration.

## Configuration

| Option           | Description                                                                | Remarks                                              |
| ---------------- | -------------------------------------------------------------------------- | ---------------------------------------------------- |
| Controller       | The device in your house that controls the boiler.                         | The controller can be of type `climate` or `switch`. |
| Zones            | The device in your house which controls the areas.                         | The zones must be of type `climate`.                 |
| Maximum setpoint | Limits the maximum temperature setpoint that can be sent to the controller |                                                      |
| Controller delay time | Time it takes for the controller entity to be updated after a new setpoint is sent |  Default is 10 seconds (most thermostats update almost instantly)                                                    |

## Switch entity

The Zoned heating integration creates a switch entity `switch.zoned_heating` which can be used to control the Zoned Heating:
* `On`: Zoned heating is enabled, the integration watches the zones for heat demand and controls the controller accordingly.
* `Off`: Zoned heating is disabled, zones are independent from the controller.

### Attributes
The `switch.zoned_heating` entity exposes the following attributes:

| Name                   | Description                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- |
| `controller`           | Entity which has been set up as controller                                                                 |
| `zones`                | Entities which have been set up as zones                                                                   |
| `max_setpoint`         | Setting for maximum temperature setpoint                                                                   |
| `controller_delay_time`         | Setting for controller delay time setpoint                                                                   |
| `override_active`      | `True`: The controller is turned due to one or more zones.<br>`False`: The controller operates standalone. |
| `temperature_increase` | Maximum difference in requested temperature and actual temperature of the zones.                           |

## Functionality

### Temperature override
The main goal of the zoned heating is to override the controller when one or more zones request heat.

The override logic is triggered when the setpoint or operation mode of a zone is changed.
The following flow is executed:
1. For all zones which are in heating mode, the temperature setpoint minus actual temperature (=temperature increase) is calculated.
2. The zone with the highest temperature increase is considered dominant and will be used to operate the controller.
3. In case no zone is calling for heat, the override is stopped. Otherwise, the override is started or updated.
4. If override is active, the controller will be turned on (set to `heat` in case of a `climate` entity). Otherwise, its prior state is restored (see below).
5. If override is active, the temperature setpoint of the controller will be updated to its current (sensor) temperature + temperature increase. Only applies in case the controller is a `climate` entity.

### Controller restoration
If the override mode is stopped, the controller is restored to its setting (state/mode and temperature setpoint) prior to the override mode. The settings are stored at the moment the override becomes active.

The restoration settings are kept when HA is restarted.

### Controller operation during override
When the temperature setpoint of the controller entity is changed when override mode is active, this change is maintained and saved in the restoration settings.
This could mean that the zones no longer get heat. 
When any zone requests heat, the override continues as before.

When the controller entity is turned off while override is active, the override mode is stopped and all zones which were requesting heat are  turned off as well.

**Note:** after the zoned-heating integration has updated the setpoint of the controller, a manual change made to the controller within the time defined by the 'controller delay time' setting will not cause the restoration settings to be updated.

## Limitations
The following limitations are known and possibly addressed in future updates:
* The integration is only tested for `climate` modes `heat` and `off`. Modes `cool` and `heat_cool` might result in unwanted behaviour.
* The override logic assumes that your zones can heat up quicker than the controller. If this is not the case, the zones may never reach the desired temperature.
* This integration does not handle presets for `climate` devices.
