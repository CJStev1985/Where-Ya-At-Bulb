# Location Lighting Mode (Home Assistant Add-on)

This repository contains a Home Assistant OS add-on that provides a small web UI (Ingress) to generate Home Assistant configuration for a location-driven lighting mode system.

## Quick start (Home Assistant OS)

1. Install Home Assistant OS on your Raspberry Pi and complete onboarding.
2. In Home Assistant: Settings -> Add-ons -> Add-on store -> (three dots) Repositories.
3. Add the URL of this GitHub repository.
4. Install the add-on: "Location Lighting Mode".
5. Start the add-on.
6. Open the add-on UI (Ingress) and fill in the form.
7. Click Apply.

## What this add-on does

- Writes a generated package YAML file to:

`/config/packages/location_lighting_mode_generated.yaml`

- Optionally creates helpers (or uses existing ones)
- Generates automations for:
  - location mode computation with dwell/anti-flicker
  - lighting reaction per mode
  - optional home arrival flourish

## Requirement: enable packages

Home Assistant must include packages in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

If you do not have that yet, add it and restart Home Assistant.
