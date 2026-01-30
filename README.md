# Where-Ya-At Bulb (Home Assistant Add-on)

This repository is a Home Assistant OS add-on repo. The add-on provides an Ingress web UI that generates Home Assistant configuration (packages) for a location-driven “lighting mode” system.

## Install (Home Assistant OS)

1. Install Home Assistant OS on your Raspberry Pi and complete onboarding.
2. In Home Assistant: Settings -> Add-ons -> Add-on store.
3. Open the top-right menu (three dots) -> Repositories.
4. Add this GitHub repo URL.
5. Install the add-on: **Where-Ya-At Bulb**.
6. Start the add-on.
7. Open the add-on UI (Ingress).
8. Fill in your entities/zones/colors.
9. Click **Apply**.

## Requirement: enable packages

Add this to `configuration.yaml` (once):

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then restart Home Assistant.

## What gets generated

The add-on writes a generated package file to:

`/config/packages/where_ya_at_bulb_generated.yaml`

That package contains:

- `input_select` for `input_select.location_mode`
- `input_boolean` for manual override
- `timer.mode_dwell` for anti-flicker
- automations to compute the mode + apply the light state

## Notes

- This add-on does not talk to Govee directly. You add your Govee integration in Home Assistant, then select the resulting `light.*` entity in the UI.
