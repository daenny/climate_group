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
from homeassistant.components.climate import (ClimateDevice, PLATFORM_SCHEMA)
from homeassistant.components.climate.const import *
from homeassistant.const import (ATTR_ENTITY_ID, ATTR_TEMPERATURE, TEMP_CELSIUS,
                                 CONF_ENTITIES, CONF_NAME, ATTR_SUPPORTED_FEATURES)
from homeassistant.core import State, callback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.typing import HomeAssistantType, ConfigType

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Climate Group'

CONF_EXCLUDE = 'exclude'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_ENTITIES): cv.entities_domain(climate.DOMAIN),
    vol.Optional(CONF_EXCLUDE, default=[]): vol.All(
        cv.ensure_list,
        [vol.In([
            PRESET_ACTIVITY,
            PRESET_AWAY,
            PRESET_BOOST,
            PRESET_COMFORT,
            PRESET_ECO,
            PRESET_HOME,
            PRESET_SLEEP
        ])
    ])
})

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE


async def async_setup_platform(hass: HomeAssistantType, config: ConfigType,
                               async_add_entities,
                               discovery_info=None) -> None:
    """Initialize climate.group platform."""
    async_add_entities([ClimateGroup(
        config.get(CONF_NAME),
        config[CONF_ENTITIES],
        config.get(CONF_EXCLUDE)
    )])


class ClimateGroup(ClimateDevice):
    """Representation of a climate group."""

    def __init__(self, name: str, entity_ids: List[str], excluded: List[str]) -> None:
        """Initialize a climate group."""
        self._name = name  # type: str
        self._entity_ids = entity_ids  # type: List[str]

        self._min_temp = 0
        self._max_temp = 0
        self._current_temp = 0
        self._target_temp = 0
        self._mode = None
        self._action = None
        self._mode_list = None
        self._available = True  # type: bool
        self._supported_features = 0  # type: int
        self._async_unsub_state_changed = None
        self._preset_modes = None
        self._preset = None
        self._excluded = excluded

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def async_state_changed_listener(entity_id: str, old_state: State,
                                         new_state: State):
            """Handle child updates."""
            self.async_schedule_update_ha_state(True)

        self._async_unsub_state_changed = async_track_state_change(
            self.hass, self._entity_ids, async_state_changed_listener)
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

    @property
    def temperature_unit(self):
        """Return the unit of measurement that is used."""
        return TEMP_CELSIUS

    @property
    def should_poll(self) -> bool:
        """No polling needed for a climate group."""
        return False

    async def async_set_temperature(self, **kwargs):
        """Forward the turn_on command to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}
        if ATTR_HVAC_MODE in kwargs:
            hvac_mode = kwargs.get(ATTR_HVAC_MODE)
            await self.async_set_hvac_mode(hvac_mode)
        elif ATTR_TEMPERATURE in kwargs:
            temperature = kwargs.get(ATTR_TEMPERATURE)
            data[ATTR_TEMPERATURE] = temperature
            await self.hass.services.async_call(
                climate.DOMAIN, climate.SERVICE_SET_TEMPERATURE, data, blocking=True)

    async def async_set_operation_mode(self, operation_mode):
        """Forward the turn_on command to all climate in the climate group. LEGACY CALL.
        This will be used only if the hass version is old."""
        data = {ATTR_ENTITY_ID: self._entity_ids,
                ATTR_HVAC_MODE: operation_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_HVAC_MODE, data, blocking=True)

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
        data = {ATTR_ENTITY_ID: self._entity_ids,
                ATTR_HVAC_MODE: hvac_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_HVAC_MODE, data, blocking=True)

    async def async_update(self):
        """Query all members and determine the climate group state."""
        raw_states = [self.hass.states.get(x) for x in self._entity_ids]
        all_states = list(filter(None, raw_states))

        states = list(filter(lambda x: x is not None and 'preset_mode' in x.attributes, raw_states))

        heat_states = list(filter(lambda x: x.state == HVAC_MODE_HEAT, states))
        cool_states = list(filter(lambda x: x.state == HVAC_MODE_COOL, states))

        # return the Mode (what the thermostat is set to do) in priority order (heat, then cool, then off)
        self._mode = HVAC_MODE_OFF
        if len(heat_states):
            self._mode = HVAC_MODE_HEAT
        elif len(cool_states):
            self._mode = HVAC_MODE_COOL

        heat_actions = list(filter(lambda x: x.attributes.get('hvac_action', None) == CURRENT_HVAC_HEAT, states))
        cool_actions = list(filter(lambda x: x.attributes.get('hvac_action', None) == CURRENT_HVAC_COOL, states))
        idle_actions = list(filter(lambda x: x.attributes.get('hvac_action', None) == CURRENT_HVAC_IDLE, states))
        off_actions = list(filter(lambda x: x.attributes.get('hvac_action', None) == CURRENT_HVAC_OFF, states))
        # return what the thermostat is _actually_ doing. If _any_ are actively
        # heating or cooling, this is reported
        self._action = None
        if heat_actions:
            self._action = CURRENT_HVAC_HEAT
        elif cool_actions:
            self._action = CURRENT_HVAC_COOL
        elif idle_actions:
            self._action = CURRENT_HVAC_IDLE
        elif off_actions:
            self._action = CURRENT_HVAC_OFF

        # if nothing is in excluded everything will be in 'filtered states'
        filtered_states = list(filter(
            lambda x: x.attributes.get('preset_mode', None) not in self._excluded, states
        ))
        if not filtered_states:  # everything is being filtered, so show everything
            filtered_states = states

        _LOGGER.debug(f"Excluded by config: {self._excluded}")
        _LOGGER.debug(f"Resulting filtered states: {filtered_states}")

        # get the most common state of non-filtered devices
        all_presets = [state.attributes.get('preset_mode', None) for state in filtered_states]
        if all_presets:
            # Report the most common preset_mode.
            self._preset = Counter(itertools.chain(all_presets)).most_common(1)[0][0]

        self._target_temp = _reduce_attribute(filtered_states, 'temperature')
        self._current_temp = _reduce_attribute(filtered_states, 'current_temperature')

        _LOGGER.debug(f"Target temp: {self._target_temp}; Current temp: {self._current_temp}")

        self._min_temp = _reduce_attribute(all_states, 'min_temp', reduce=max)
        self._max_temp = _reduce_attribute(all_states, 'max_temp', reduce=min)

        self._mode_list = None
        all_mode_lists = list(
            _find_state_attributes(states, 'hvac_modes'))
        if all_mode_lists:
            # Merge all effects from all effect_lists with a union merge.
            self._mode_list = list(set().union(*all_mode_lists))

        self._supported_features = 0
        for support in _find_state_attributes(all_states, ATTR_SUPPORTED_FEATURES):
            # Merge supported features by emulating support for every feature
            # we find.
            self._supported_features |= support

        presets = []
        for preset in _find_state_attributes(all_states, ATTR_PRESET_MODES):
            presets.extend(preset)

        if len(presets):
            self._preset_modes = set(presets)
        else:
            self._preset_modes = None

    async def async_set_preset_mode(self, preset_mode: str):
        """Forward the preset_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids,
                ATTR_PRESET_MODE: preset_mode}

        await self.hass.services.async_call(
            climate.DOMAIN, climate.SERVICE_SET_PRESET_MODE, data, blocking=True)


def _find_state_attributes(states: List[State],
                           key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        value = state.attributes.get(key)
        if value is not None:
            yield value


def _mean(*args):
    """Return the mean of the supplied values."""
    return sum(args) / len(args)


def _reduce_attribute(states: List[State],
                      key: str,
                      default: Optional[Any] = None,
                      reduce: Callable[..., Any] = _mean) -> Any:
    """Find the first attribute matching key from states.
    If none are found, return default.
    """
    attrs = list(_find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)

