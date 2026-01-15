# Leviton Decora Smart for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A modern Home Assistant integration for Leviton Decora Smart Wi-Fi devices with real-time WebSocket updates.

<p align="center">
  <img src="images/logo.png" alt="Leviton Logo" width="200"/>
</p>

## Features

- **Automatic Discovery**: Instantly finds all devices from your My Leviton account.
- **Real-Time Updates**: Uses WebSocket connection for instant state changes.
- **Two-Factor Authentication**: Full support for accounts with 2FA enabled.
- **Full Dimmer Support**: On/off and brightness control (1-100%).
- **Fan Speed Control**: 4-speed fan controllers with proper speed mapping.
- **Motion Sensors**: Motion dimmers expose both light and motion sensor entities.
- **Switches & Outlets**: On/off control for all switch, outlet, and GFCI types.
- **Session Persistence**: Maintains authentication across Home Assistant restarts.

## Supported Devices

### Dimmers
- D23LP - Dimmer (no LED bar)
- D26HD - 600W Dimmer
- D2ELV - ELV Dimmer
- D2MSD - Motion Sensor Dimmer
- DW1KD - 1000W Dimmer
- DW3HL - 300W Dimmer
- DW6HD - 600W Dimmer
- DWVAA - Voice Assistant Dimmer

### Switches
- D215O - Outdoor Switch
- D215S - Switch
- D2SCS - Scene Controller Switch
- DW15S - 15A Switch

### Outlets
- D215P - Plug-in Outlet
- D215R - Receptacle
- DW15A - 15A Outlet
- DW15P - Plug-in Outlet
- DW15R - Receptacle

### GFCI Outlets
- D2GF1, D2GF2

### Fan Controllers
- D24SF, DW4SF - 4-Speed Fan Controllers

### Controllers
- D2SCS - Scene Controller
- DW4BC - Button Controller

## Installation

### Option 1: HACS (Recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** > **Explore & Download Repositories**.
3. Search for "Leviton Decora Smart" or add this repository as a custom repository.
4. Click **Download**.
5. Restart Home Assistant.

### Option 2: Manual

1. Download the `custom_components/leviton_smart` folder from this repository.
2. Copy it to your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration**.
3. Search for **Leviton Decora Smart**.
4. Enter your **My Leviton Email** and **Password**.
5. If you have 2FA enabled, enter the code when prompted.
6. Your devices will be automatically discovered and added.

## Troubleshooting

- **Authentication Failed**: Ensure your email and password are correct.
- **2FA Issues**: Make sure you're entering the current 2FA code from your authenticator app.
- **No Devices Found**: Verify that your devices are visible in the My Leviton app.
- **Updates Not Reflecting**: Check that Home Assistant can reach `wss://socket.cloud.leviton.com`.

## How It Works

This integration connects to the My Leviton cloud API to:
1. Authenticate your account (with 2FA support)
2. Discover all devices in your residence
3. Establish a WebSocket connection for real-time updates
4. Poll for state every 30 seconds as a backup

## Disclaimer

This is an unofficial custom integration and is not affiliated with or endorsed by Leviton.
Use at your own risk.

## Credits

- Inspired by [homebridge-myleviton](https://github.com/tbaur/homebridge-myleviton)
- Device model reference from [home-assistant-leviton-decora-smart-wifi](https://github.com/schmittx/home-assistant-leviton-decora-smart-wifi)
