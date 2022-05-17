# climate_group

Home Assistant Climate Group

Groups multiple climate devices to a single entity. Useful if you have for instance multiple radiator thermostats in a room and want to control them all together.
Supports reading room temperature from external sensor or defaults to displaying the average current temperature reported by the configured climate devices.

Note: The value from the external temperature sensor is not reported back to the climate devices. It is only used to display the current temperature in the Climate Group entity card.

Inspired/copied from light_group component (https://github.com/home-assistant/home-assistant/blob/dev/homeassistant/components/group/light.py)

## How to install:

### HACS
Add this repo (https://github.com/daenny/climate_group) to the HACS store and install from there.

### local install
Put in "custom_components" folder located in hass.io inside the config folder.
(The 2 .py file must be config/custom_components/climate_group)



## Sample Configuration

Put this inside configuration.yaml in config folder of hass.io

```yaml
climate:
  - platform: climate_group
    name: 'Climate Friendly Name'
    temperature_unit: C  # Optional - default to celsius, 'C' or 'F'
    entities:
    - climate.clima1
    - climate.clima2
    - climate.clima3
    - climate.heater
    - climate.termostate
    external_sensor: sensor.temperaturesensor1 # Optional - defaults to not being used, enter entityID of the external sensor
```

(use the entities you want to have in your climate_group)
