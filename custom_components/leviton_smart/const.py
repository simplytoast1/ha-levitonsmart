"""
Constants for the Leviton Decora Smart integration.
"""

from datetime import timedelta

DOMAIN = "leviton_smart"
PLATFORMS = ["light", "switch", "fan", "binary_sensor"]

UPDATE_INTERVAL = timedelta(seconds=30)

LEVITON_SPEEDS = ["low", "medium", "high", "max"]

# Supported device models by category
# Reference: https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi

# Controllers (Scene Controllers, Button Controllers)
MODELS_CONTROLLER = ["D2SCS", "DW4BC"]

# Fans (Fan Speed Controllers)
MODELS_FAN = ["D24SF", "DW4SF"]

# GFCI Outlets
MODELS_GFCI = ["D2GF1", "D2GF2"]

# Lights (Dimmers)
MODELS_LIGHT = [
    "D23LP",  # Dimmer without LED bar
    "D26HD",  # 600W Dimmer
    "D2ELV",  # ELV Dimmer
    "D2MSD",  # Motion Sensor Dimmer
    "DW1KD",  # 1000W Dimmer
    "DW3HL",  # 300W Dimmer
    "DW6HD",  # 600W Dimmer
    "DWVAA",  # Voice Assistant Dimmer
]

# Motion Sensors
MODELS_MOTION_SENSOR = ["D2MSD"]

# Outlets (Plug-in and Receptacles)
MODELS_OUTLET = [
    "D215P",  # Plug-in Outlet
    "D215R",  # Receptacle
    "DW15A",  # 15A Outlet
    "DW15P",  # Plug-in Outlet
    "DW15R",  # Receptacle
]

# Switches (On/Off)
MODELS_SWITCH = [
    "D215O",  # Outdoor Switch
    "D215S",  # Switch
    "D2SCS",  # Scene Controller Switch
    "DW15S",  # 15A Switch
]

# All dimmable models (support brightness control)
MODELS_DIMMABLE = MODELS_LIGHT + MODELS_FAN

# All models that are switches (on/off only, no dimming)
MODELS_ON_OFF_ONLY = MODELS_SWITCH + MODELS_OUTLET + MODELS_GFCI

# All supported models
MODELS_ALL = (
    MODELS_CONTROLLER
    + MODELS_FAN
    + MODELS_GFCI
    + MODELS_LIGHT
    + MODELS_OUTLET
    + MODELS_SWITCH
)
