"""
This platform allows several climate devices to be grouped into one climate device.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/climate.group/

For more details on climate component, please refer to the documentation at
https://developers.home-assistant.io/docs/en/entity_climate.html
"""
import itertools
import logging
from collections import Counter
from typing import List, Optional, Iterator, Any, Callable

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components import climate
from homeassistant.components import sensor
from homeassistant.components.climate import ClimateEntity, PLATFORM_SCHEMA
from homeassistant.components.climate.const import *
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
    CONF_TEMPERATURE_UNIT,
    CONF_ENTITIES,
    CONF_NAME,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import State, callback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.typing import HomeAssistantType, ConfigType

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['sensor']

DEFAULT_NAME = "Climate Group"
CONF_EXT_SENSOR = "external_sensor"
CONF_EXCLUDE = "exclude"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TEMPERATURE_UNIT, default=TEMP_CELSIUS): cv.string,
        vol.Optional(CONF_EXT_SENSOR, default=''): cv.string, # would rather use cv.entity_id or cv.entity_domain(sensor.DOMAIN) but HA configuration checker does not allow "entity" checks to be None, which breaks the "optional" part
        vol.Required(CONF_ENTITIES): cv.entities_domain(climate.DOMAIN),
        vol.Optional(CONF_EXCLUDE, default=[]): vol.All(
            cv.ensure_list,
            [
                vol.In(
                    [
                        PRESET_ACTIVITY,
                        PRESET_AWAY,
                        PRESET_BOOST,
                        PRESET_COMFORT,
                        PRESET_ECO,
                        PRESET_HOME,
                        PRESET_SLEEP,
                    ]
                )
            ],
        ),
    }
)
# edit the supported_flags
SUPPORT_FLAGS = (
    SUPPORT_TARGET_TEMPERATURE | SUPPORT_TARGET_TEMPERATURE_RANGE | SUPPORT_PRESET_MODE | SUPPORT_SWING_MODE | SUPPORT_FAN_MODE
)


# HVAC Action priority
HVAC_ACTIONS = [
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_DRY,
    CURRENT_HVAC_FAN,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    None,
]


async def async_setup_platform(
    hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None
) -> None:
    """Initialize climate.group platform."""
    async_add_entities(
        [
            ClimateGroup(
                config.get(CONF_NAME),
                config[CONF_ENTITIES],
                config.get(CONF_EXCLUDE),
                config.get(CONF_TEMPERATURE_UNIT),
                config.get(CONF_EXT_SENSOR)
            )
        ]
    )


class ClimateGroup(ClimateEntity):
    """Representation of a climate group."""

    def __init__(
        self,
        name: str,
        entity_ids: List[str],
        excluded: List[str],
        unit: str,
        external_sensor: Optional[str] = None,
    ) -> None:
        """Initialize a climate group."""
        self._name = name  # type: str
        self._entity_ids = entity_ids  # type: List[str]
        self._sensor_entity_id = external_sensor
        if "c" in unit.lower():
            self._unit = TEMP_CELSIUS
        else:
            self._unit = TEMP_FAHRENHEIT
        self._min_temp = 0
        self._max_temp = 0
        self._current_temp = 0
        self._target_temp = 0
        # added the temp_low and temp_high
        self._target_temp_high = None
        self._target_temp_low = None
        self._mode = None
        self._action = None
        self._mode_list = None
        self._available = True  # type: bool
        self._supported_features = 0  # type: int
        self._async_unsub_state_changed = None
        self._fan_modes = None
        self._fan_mode = None
        self._swing_modes = None
        self._swing_mode = None
        self._preset_modes = None
        self._preset = None
        self._excluded = excluded
    

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        @callback
        def async_state_changed_listener(
            entity_id: str, old_state: State, new_state: State
        ):
            """Handle child updates."""
            self.async_schedule_update_ha_state(True)

        self._async_unsub_state_changed = async_track_state_change(
            self.hass, self._entity_ids, async_state_changed_listener
        )

        # Track changes of the temperature sensor - Only if external sensor is used
        if self._sensor_entity_id:
            # Add listener
            async_track_state_change(self.hass, self._sensor_entity_id, 
                                     self._async_temp_sensor_changed)
            sensor_state = self.hass.states.get(self._sensor_entity_id)
            if sensor_state is not None and sensor_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                self._async_update_temp(sensor_state)

        await self.async_update()

    async def async_will_remove_from_hass(self):
        """Handle removal from HASS."""
        if self._async_unsub_state_changed is not None:
            self._async_unsub_state_changed()
            self._async_unsub_state_changed = None

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def available(self) -> bool:
        """Return whether the climate group is available."""
        return self._available

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def hvac_mode(self):
        """What is the thermostat intending to do"""
        return self._mode

    @property
    def hvac_action(self):
        """What is the thermostat _actually_ doing right now"""
        return self._action

    @property
    def hvac_modes(self):
        return self._mode_list

    @property
    def min_temp(self):
        return self._min_temp

    @property
    def max_temp(self):
        return self._max_temp

    @property
    def current_temperature(self):
        return self._current_temp

    @property
    def target_temperature(self):
        return self._target_temp

    # added the target_temperature_low and target_temperature_high
    @property
    def target_temperature_low(self):
        return self._target_temp_low

    @property
    def target_temperature_high(self):
        return self._target_temp_high

    @property
    def temperature_unit(self):
        """Return the unit of measurement that is used."""
        return self._unit

    @property
    def should_poll(self) -> bool:
        """No polling needed for a climate group."""
        return False

    @property
    def extra_state_attributes(self):
        """Return the state attributes for the climate group."""
        return {ATTR_ENTITY_ID: self._entity_ids}

    async def async_set_temperature(self, **kwargs):
        """Forward the turn_on command to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}
        if ATTR_HVAC_MODE in kwargs:
            hvac_mode = kwargs.get(ATTR_HVAC_MODE)
            await self.async_set_hvac_mode(hvac_mode)
        # start add
        elif (
            ATTR_TEMPERATURE in kwargs
            or ATTR_TARGET_TEMP_LOW in kwargs
            or ATTR_TARGET_TEMP_HIGH in kwargs
        ):
            if ATTR_TEMPERATURE in kwargs:
                temperature = kwargs.get(ATTR_TEMPERATURE)
                data[ATTR_TEMPERATURE] = temperature
            elif ATTR_TARGET_TEMP_LOW in kwargs or ATTR_TARGET_TEMP_HIGH in kwargs:
                temperature_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
                temperature_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
                data[climate.ATTR_TARGET_TEMP_LOW] = temperature_low
                data[climate.ATTR_TARGET_TEMP_HIGH] = temperature_high
            # end add
            await self.hass.services.async_call(
                climate.DOMAIN, climate.SERVICE_SET_TEMPERATURE, data, blocking=True
            )

    async def async_set_operation_mode(self, operation_mode):
        """Forward the turn_on command to all climate in the climate group. LEGACY CALL.
        This will be used only if the hass version is old."""
        data = {ATTR_ENTITY_ID: self._entity_ids,
                ATTR_HVAC_MODE: operation_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_HVAC_MODE, data, blocking=True
        )

    @property
    def fan_mode(self):
        """Return the current fan mode."""
        return self._fan_mode

    @property
    def fan_modes(self):
        """Return a list of available fan modes."""
        return self._fan_modes

    @property
    def swing_mode(self):
        """Return the current swing mode."""
        return self._swing_mode

    @property
    def swing_modes(self):
        """Return a list of available swing modes."""
        return self._swing_modes

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return self._preset

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        return self._preset_modes

    async def async_set_hvac_mode(self, hvac_mode):
        """Forward the turn_on command to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_HVAC_MODE: hvac_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_HVAC_MODE, data, blocking=True
        )

    # Update climate group current temperature - Only used if external temperature sensor is configured
    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature sensor changes. External sensor???"""
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        
        self._async_update_temp(new_state)
        await self.async_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != "STATE_UNKNOWN":
                self._current_temp = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)

    async def async_update(self):
        """Query all members and determine the climate group state."""
        raw_states = [self.hass.states.get(x) for x in self._entity_ids]
        states = list(filter(None, raw_states))

        # if nothing is in excluded everything will be in 'filtered states'
        filtered_states = list(
            filter(
                lambda x: x.attributes.get(ATTR_PRESET_MODE, None)
                not in self._excluded,
                states,
            )
        )

        if not filtered_states:  # everything is being filtered, so show everything
            filtered_states = states

        _LOGGER.debug(f"Excluded by config: {self._excluded}")
        _LOGGER.debug(f"Resulting filtered states: {filtered_states}")

        all_modes = [x.state for x in filtered_states]
        # return the Mode (what the thermostat is set to do) in priority order (heat, cool, ...)
        self._mode = None
        # iterate through all hvac modes (skip first, as its off)
        for hvac_mode in HVAC_MODES[1:] + [HVAC_MODE_OFF]:
            # if any thermostat is in the given mode return it
            if any([mode == hvac_mode for mode in all_modes]):
                self._mode = hvac_mode
                break

        all_actions = [
            state.attributes.get(ATTR_HVAC_ACTION, None) for state in filtered_states
        ]
        for hvac_action in HVAC_ACTIONS:
            # if any thermostat is in the given action return it
            if any([action == hvac_action for action in all_actions]):
                self._action = hvac_action
                break

        # get the most common state of non-filtered devices
        all_fan_modes = [
            state.attributes.get(ATTR_FAN_MODE, None) for state in filtered_states
        ]
        self._fan_mode = None
        if all_fan_modes:
            # Report the most common fan_mode.
            self._fan_mode = Counter(itertools.chain(
                all_fan_modes)).most_common(1)[0][0]

        all_swing_modes = [
            state.attributes.get(ATTR_SWING_MODE, None) for state in filtered_states
        ]
        self._swing_mode = None
        if all_swing_modes:
            # Report the most common swing_mode.
            self._swing_mode = Counter(itertools.chain(
                all_swing_modes)).most_common(1)[0][0]

        all_presets = [
            state.attributes.get(ATTR_PRESET_MODE, None) for state in filtered_states
        ]
        self._preset = None
        if all_presets:
            # Report the most common preset_mode.
            self._preset = Counter(itertools.chain(
                all_presets)).most_common(1)[0][0]

        self._target_temp = _reduce_attribute(
            filtered_states, ATTR_TEMPERATURE)

        # start add
        self._target_temp_low = _reduce_attribute(
            filtered_states, ATTR_TARGET_TEMP_LOW)
        self._target_temp_high = _reduce_attribute(
            filtered_states, ATTR_TARGET_TEMP_HIGH
        )
        # end add

        # Only if external temperature sensor is NOT used
        if not self._sensor_entity_id:
            self._current_temp = _reduce_attribute(
                filtered_states, ATTR_CURRENT_TEMPERATURE
            )

        _LOGGER.debug(
            f"Target temp: {self._target_temp}; Target temp low: {self._target_temp_low}; Target temp high: {self._target_temp_high}; Current temp: {self._current_temp}"
        )
        self._min_temp = _reduce_attribute(states, ATTR_MIN_TEMP, reduce=max)
        self._max_temp = _reduce_attribute(states, ATTR_MAX_TEMP, reduce=min)

        # Supported HVAC modes
        self._mode_list = None
        all_mode_lists = list(_find_state_attributes(states, ATTR_HVAC_MODES))
        if all_mode_lists:
            # Merge all effects from all effect_lists with a union merge.
            self._mode_list = list(set().union(*all_mode_lists))

        self._supported_features = 0
        for support in _find_state_attributes(states, ATTR_SUPPORTED_FEATURES):
            # Merge supported features by emulating support for every feature
            # we find.
            self._supported_features |= support
        # Bitwise-and the supported features with the Grouped climate's features
        # so that we don't break in the future when a new feature is added.
        self._supported_features &= SUPPORT_FLAGS

        self._fan_modes = None
        fan_modes = []
        for fan_mode in _find_state_attributes(states, ATTR_FAN_MODES):
            fan_modes.extend(fan_mode)

        if len(fan_modes):
            self._fan_modes = set(fan_modes)

        self._swing_modes = None
        swing_modes = []
        for swing_mode in _find_state_attributes(states, ATTR_SWING_MODES):
            swing_modes.extend(swing_mode)

        if len(swing_modes):
            self._swing_modes = set(swing_modes)

        self._preset_modes = None
        presets = []
        for preset in _find_state_attributes(states, ATTR_PRESET_MODES):
            presets.extend(preset)

        if len(presets):
            self._preset_modes = set(presets)

        _LOGGER.debug(
            f"State update complete. Supported: {self._supported_features}, mode: {self._mode}"
        )

    async def async_set_fan_mode(self, fan_mode: str):
        """Forward the fan_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_FAN_MODE: fan_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_FAN_MODE, data, blocking=True
        )

    async def async_set_swing_mode(self, swing_mode: str):
        """Forward the swing_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_SWING_MODE: swing_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_SWING_MODE, data, blocking=True
        )

    async def async_set_preset_mode(self, preset_mode: str):
        """Forward the preset_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids,
                ATTR_PRESET_MODE: preset_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_PRESET_MODE, data, blocking=True
        )


def _find_state_attributes(states: List[State], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        value = state.attributes.get(key)
        if value is not None:
            yield value


def _mean(*args):
    """Return the mean of the supplied values."""
    return sum(args) / len(args)


def _reduce_attribute(
    states: List[State],
    key: str,
    default: Optional[Any] = None,
    reduce: Callable[..., Any] = _mean,
) -> Any:
    """Find the first attribute matching key from states.
    If none are found, return default.
    """
    attrs = list(_find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)
