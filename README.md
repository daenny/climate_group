# climate_group

STATUS: [UN-MAINTAINED]. Due to personal reasons I am not using this integration anymore. I do not have the time to actively maintain it. Feel free to fork/take-over. 
I had made in try to get it merged into home assistant: https://github.com/home-assistant/core/pull/77737 but never got around to finish it. 

Home Assistant Climate Group

Groups multiple climate devices to a single entity. Useful if you have for instance multiple radiator thermostats in a room and want to control them all together.
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
    temperature_unit: C  # default to celsius, 'C' or 'F'
    entities:
    - climate.clima1
    - climate.clima2
    - climate.clima3
    - climate.heater
    - climate.termostate
```

(use the entities you want to have in your climate_group)
