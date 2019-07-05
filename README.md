# climate_group

Home Assistant Climate Groupe

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
    entities:
    - climate.clima1
    - climate.clima2
    - climate.clima3
    - climate.heater
    - climate.termostate
```

(use the entities you want to have in your climate_group)
