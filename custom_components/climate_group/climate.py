"""This platform allows several climate devices to be grouped into one climate device."""
from __future__ import annotations

import logging
from statistics import mean
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TARGET_TEMP_STEP,
    DOMAIN,
    PLATFORM_SCHEMA,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    ATTR_TEMPERATURE,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TEMPERATURE_UNIT,
    CONF_UNIQUE_ID,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from homeassistant.components.group.entity import GroupEntity
from homeassistant.components.group.util import (
    find_state_attributes,
    most_frequent_attribute,
    reduce_attribute,
    states_equal,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Climate Group"

# No limit on parallel updates to enable a group calling another group
PARALLEL_UPDATES = 0

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_TEMPERATURE_UNIT): cv.temperature_unit,
        vol.Required(CONF_ENTITIES): cv.entities_domain(DOMAIN),
    }
)
# edit the supported_flags
SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    | ClimateEntityFeature.PRESET_MODE
    | ClimateEntityFeature.SWING_MODE
    | ClimateEntityFeature.FAN_MODE
)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Initialize climate.group platform."""
    async_add_entities(
        [
            ClimateGroup(
                config.get(CONF_UNIQUE_ID),
                config[CONF_NAME],
                config[CONF_ENTITIES],
                config.get(CONF_TEMPERATURE_UNIT, hass.config.units.temperature_unit),
            )
        ]
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Climate Group config entry."""
    registry = er.async_get(hass)
    entities = er.async_validate_entity_ids(
        registry, config_entry.options[CONF_ENTITIES]
    )

    async_add_entities(
        [
            ClimateGroup(
                config_entry.entry_id,
                config_entry.title,
                entities,
                config_entry.options.get(
                    CONF_TEMPERATURE_UNIT, hass.config.units.temperature_unit
                ),
            )
        ]
    )


class ClimateGroup(GroupEntity, ClimateEntity):
    """Representation of a climate group."""

    _attr_available: bool = False
    _attr_assumed_state: bool = True

    def __init__(
        self,
        unique_id: str | None,
        name: str,
        entity_ids: list[str],
        temperature_unit: str,
    ) -> None:
        """Initialize a climate group."""
        self._entity_ids = entity_ids

        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_extra_state_attributes = {ATTR_ENTITY_ID: entity_ids}

        self._attr_temperature_unit = temperature_unit

        # Set some defaults (will be overwritten on update)
        self._attr_supported_features = 0
        self._attr_hvac_modes = [HVACMode.OFF]
        self._attr_hvac_mode = None
        self._attr_hvac_action = None

        self._attr_swing_modes = None
        self._attr_swing_mode = None

        self._attr_fan_modes = None
        self._attr_fan_mode = None

        self._attr_preset_modes = None
        self._attr_preset_mode = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        @callback
        def async_state_changed_listener(event: Event) -> None:
            """Handle child updates."""
            self.async_set_context(event.context)
            self.async_defer_or_update_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._entity_ids, async_state_changed_listener
            )
        )

        await super().async_added_to_hass()

    @callback
    def async_update_group_state(self) -> None:
        """Query all members and determine the climate group state."""
        self._attr_assumed_state = False

        states = [
            state
            for entity_id in self._entity_ids
            if (state := self.hass.states.get(entity_id)) is not None
        ]
        self._attr_assumed_state |= not states_equal(states)

        # Set group as unavailable if all members are unavailable or missing
        self._attr_available = any(state.state != STATE_UNAVAILABLE for state in states)

        # Temperature settings
        self._attr_target_temperature = reduce_attribute(
            states, ATTR_TEMPERATURE, reduce=lambda *data: mean(data)
        )

        self._attr_target_temperature_step = reduce_attribute(
            states, ATTR_TARGET_TEMP_STEP, reduce=max
        )

        self._attr_target_temperature_low = reduce_attribute(
            states, ATTR_TARGET_TEMP_LOW, reduce=lambda *data: mean(data)
        )
        self._attr_target_temperature_high = reduce_attribute(
            states, ATTR_TARGET_TEMP_HIGH, reduce=lambda *data: mean(data)
        )

        self._attr_current_temperature = reduce_attribute(
            states, ATTR_CURRENT_TEMPERATURE, reduce=lambda *data: mean(data)
        )

        self._attr_min_temp = reduce_attribute(states, ATTR_MIN_TEMP, reduce=max)
        self._attr_max_temp = reduce_attribute(states, ATTR_MAX_TEMP, reduce=min)
        # End temperature settings

        # available HVAC modes
        all_hvac_modes = list(find_state_attributes(states, ATTR_HVAC_MODES))
        if all_hvac_modes:
            # Merge all effects from all effect_lists with a union merge.
            self._attr_hvac_modes = list(set().union(*all_hvac_modes))

        
        current_hvac_modes = [x.state for x in states if x.state != HVACMode.OFF]
        # return the most common hvac mode (what the thermostat is set to do) except OFF
        if current_hvac_modes:
            self._attr_hvac_mode = max(set(current_hvac_modes), key=current_hvac_modes.count)
        # return off if all are off
        elif all(x.state == HVACMode.OFF for x in states):
            self._attr_preset_mode = HVACMode.OFF
        # else it's none
        else:
            self._attr_hvac_mode = None

        # return the most common action if it is not off
        hvac_actions = list(find_state_attributes(states, ATTR_HVAC_ACTION))
        current_hvac_actions = [a for a in hvac_actions if a != HVACAction.OFF]
        # return the most common action if it is not off
        if current_hvac_actions:
            self._attr_hvac_action = max(set(current_hvac_actions), key=current_hvac_actions.count)
        # return action off if all are off
        elif all(a == HVACAction.OFF for a in hvac_actions):
            self._attr_hvac_action = HVACAction.OFF
        # else it's none
        else:
            self._attr_hvac_action = None

        # available swing modes
        all_swing_modes = list(find_state_attributes(states, ATTR_SWING_MODES))
        if all_swing_modes:
            self._attr_swing_modes = list(set().union(*all_swing_modes))

        # Report the most common swing_mode.
        self._attr_swing_mode = most_frequent_attribute(states, ATTR_SWING_MODE)

        # available fan modes
        all_fan_modes = list(find_state_attributes(states, ATTR_FAN_MODES))
        if all_fan_modes:
            # Merge all effects from all effect_lists with a union merge.
            self._attr_fan_modes = list(set().union(*all_fan_modes))

        # Report the most common fan_mode.
        self._attr_fan_mode = most_frequent_attribute(states, ATTR_FAN_MODE)

        # available preset modes
        all_preset_modes = list(find_state_attributes(states, ATTR_PRESET_MODES))
        if all_preset_modes:
            # Merge all effects from all effect_lists with a union merge.
            self._attr_preset_modes = list(set().union(*all_preset_modes))

        # Report the most common fan_mode.
        self._attr_preset_mode = most_frequent_attribute(states, ATTR_PRESET_MODE)

        # Supported flags
        for support in find_state_attributes(states, ATTR_SUPPORTED_FEATURES):
            # Merge supported features by emulating support for every feature
            # we find.
            self._attr_supported_features |= support

        # Bitwise-and the supported features with the Grouped climate's features
        # so that we don't break in the future when a new feature is added.
        self._attr_supported_features &= SUPPORT_FLAGS

        _LOGGER.debug("State update complete")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Forward the turn_on command to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}

        if ATTR_HVAC_MODE in kwargs:
            _LOGGER.debug("Set temperature with HVAC MODE")
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])

        if ATTR_TEMPERATURE in kwargs:
            data[ATTR_TEMPERATURE] = kwargs[ATTR_TEMPERATURE]
        if ATTR_TARGET_TEMP_LOW in kwargs:
            data[ATTR_TARGET_TEMP_LOW] = kwargs[ATTR_TARGET_TEMP_LOW]
        if ATTR_TARGET_TEMP_HIGH in kwargs:
            data[ATTR_TARGET_TEMP_HIGH] = kwargs[ATTR_TARGET_TEMP_HIGH]

        _LOGGER.debug("Setting temperature: %s", data)

        await self.hass.services.async_call(
            DOMAIN, SERVICE_SET_TEMPERATURE, data, blocking=True, context=self._context
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Forward the turn_on command to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_HVAC_MODE: hvac_mode}
        _LOGGER.debug("Setting hvac mode: %s", data)
        await self.hass.services.async_call(
            DOMAIN, SERVICE_SET_HVAC_MODE, data, blocking=True, context=self._context
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Forward the fan_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_FAN_MODE: fan_mode}
        _LOGGER.debug("Setting fan mode: %s", data)
        await self.hass.services.async_call(
            DOMAIN, SERVICE_SET_FAN_MODE, data, blocking=True, context=self._context
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Forward the swing_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_SWING_MODE: swing_mode}
        _LOGGER.debug("Setting swing mode: %s", data)
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SWING_MODE,
            data,
            blocking=True,
            context=self._context,
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Forward the preset_mode to all climate in the climate group."""
        data = {ATTR_ENTITY_ID: self._entity_ids, ATTR_PRESET_MODE: preset_mode}
        _LOGGER.debug("Setting preset mode: %s", data)
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_SET_PRESET_MODE,
            data,
            blocking=True,
            context=self._context,
        )
