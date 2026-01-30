import json
import os
from pathlib import Path

import yaml
from flask import Flask, redirect, render_template, request, url_for


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return value


def _get_addon_options() -> dict:
    raw = _get_env("OPTIONS", "{}")
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _data_dir() -> Path:
    return Path(_get_env("DATA_DIR", "/data"))


def _load_user_config() -> dict:
    p = _data_dir() / "ui_config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_user_config(cfg: dict) -> None:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "ui_config.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _ensure_packages_enabled(config_dir: Path) -> tuple[bool, str | None]:
    configuration_yaml = config_dir / "configuration.yaml"
    if not configuration_yaml.exists():
        return False, "configuration.yaml not found in /config"

    text = configuration_yaml.read_text(encoding="utf-8")
    if "packages:" in text:
        return True, None

    return False, "Home Assistant packages are not enabled in configuration.yaml"


def _build_package_yaml(options: dict, user_cfg: dict) -> str:
    location_mode_entity = user_cfg.get("location_mode_entity") or options.get("location_mode_entity") or "input_select.location_mode"
    manual_override_entity = user_cfg.get("manual_override_entity") or options.get("manual_override_entity") or "input_boolean.light_manual_override"
    dwell_seconds = int(user_cfg.get("dwell_seconds") or options.get("dwell_seconds") or 300)

    phone_tracker = (user_cfg.get("phone_tracker") or "").strip()
    light_entity = (user_cfg.get("light_entity") or "").strip()

    zones_florida = user_cfg.get("zones_florida") or []
    zone_work = (user_cfg.get("zone_work") or "").strip()
    zone_airport = (user_cfg.get("zone_airport") or "").strip()
    shopping_prefix = (user_cfg.get("shopping_prefix") or "shopping_").strip()

    flourish_enabled = bool(user_cfg.get("flourish_enabled"))

    colors = user_cfg.get("colors") or {}

    def _rgb(mode: str) -> list[int] | None:
        v = colors.get(mode, {}).get("rgb")
        if not v:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
            if len(parts) == 3:
                return [int(parts[0]), int(parts[1]), int(parts[2])]
        if isinstance(v, list) and len(v) == 3:
            return [int(v[0]), int(v[1]), int(v[2])]
        return None

    def _brightness(mode: str) -> int | None:
        v = colors.get(mode, {}).get("brightness")
        if v in (None, ""):
            return None
        return int(v)

    modes = ["FLORIDA", "WORK", "HOME", "SHOPPING", "TRAVELING", "UNKNOWN"]

    input_select_block = {
        location_mode_entity.split(".")[0]: {
            location_mode_entity.split(".")[1]: {
                "name": "Location Mode",
                "options": modes,
            }
        }
    }

    input_boolean_block = {
        manual_override_entity.split(".")[0]: {
            manual_override_entity.split(".")[1]: {
                "name": "Light Manual Override",
            }
        }
    }

    timer_block = {
        "timer": {
            "mode_dwell": {
                "name": "Mode Dwell Timer",
                "duration": f"00:{dwell_seconds // 60:02d}:{dwell_seconds % 60:02d}",
            }
        }
    }

    flourish_flag_block = {
        "input_boolean": {
            "home_flourish_done_today": {
                "name": "Home Arrival Flourish Done Today",
            }
        }
    }

    def _candidate_template() -> str:
        florida_list = ", ".join(["'" + z + "'" for z in zones_florida])
        if florida_list.strip() == "":
            florida_list = "''"

        return (
            "{% set loc = states('" + phone_tracker + "') %}\n"
            "{% if loc in [" + florida_list + "] %}FLORIDA"
            + ("{% elif loc == '" + zone_work + "' %}WORK" if zone_work else "")
            + "{% elif loc == 'home' %}HOME"
            + ("{% elif loc == '" + zone_airport + "' %}TRAVELING" if zone_airport else "")
            + ("{% elif loc.startswith('" + shopping_prefix + "') %}SHOPPING" if shopping_prefix else "")
            + "{% else %}UNKNOWN{% endif %}"
        )

    automations = []

    if phone_tracker:
        automations.append(
            {
                "id": "llm_compute_mode_start_dwell",
                "alias": "Location Lighting Mode - Start dwell on location change",
                "trigger": [{"platform": "state", "entity_id": phone_tracker}],
                "condition": [],
                "action": [
                    {"variables": {"candidate": f"{{{{ {_candidate_template()} }}}}"}},
                    {
                        "choose": [
                            {
                                "conditions": [
                                    {
                                        "condition": "template",
                                        "value_template": f"{{{{ candidate != states('{location_mode_entity}') }}}}",
                                    }
                                ],
                                "sequence": [
                                    {"service": "timer.start", "target": {"entity_id": "timer.mode_dwell"}},
                                ],
                            }
                        ]
                    },
                ],
                "mode": "restart",
            }
        )

        automations.append(
            {
                "id": "llm_compute_mode_commit",
                "alias": "Location Lighting Mode - Commit mode after dwell",
                "trigger": [{"platform": "event", "event_type": "timer.finished", "event_data": {"entity_id": "timer.mode_dwell"}}],
                "action": [
                    {"variables": {"candidate": f"{{{{ {_candidate_template()} }}}}"}},
                    {
                        "condition": "template",
                        "value_template": f"{{{{ candidate != states('{location_mode_entity}') }}}}",
                    },
                    {
                        "service": "input_select.select_option",
                        "target": {"entity_id": location_mode_entity},
                        "data": {"option": "{{ candidate }}"},
                    },
                ],
                "mode": "single",
            }
        )

    if light_entity:
        choose_sequences = []
        for mode in modes:
            rgb = _rgb(mode)
            bri = _brightness(mode)
            light_data: dict = {}
            if rgb:
                light_data["rgb_color"] = rgb
            if bri is not None:
                light_data["brightness"] = bri

            if light_data:
                choose_sequences.append(
                    {
                        "conditions": [{"condition": "state", "entity_id": location_mode_entity, "state": mode}],
                        "sequence": [
                            {
                                "condition": "state",
                                "entity_id": manual_override_entity,
                                "state": "off",
                            },
                            {
                                "service": "light.turn_on",
                                "target": {"entity_id": light_entity},
                                "data": light_data,
                            },
                        ],
                    }
                )

        automations.append(
            {
                "id": "llm_apply_light_on_mode_change",
                "alias": "Location Lighting Mode - Apply lighting on mode change",
                "trigger": [{"platform": "state", "entity_id": location_mode_entity}],
                "action": [{"choose": choose_sequences}],
                "mode": "restart",
            }
        )

    if flourish_enabled and light_entity:
        automations.append(
            {
                "id": "llm_home_flourish_once_daily",
                "alias": "Location Lighting Mode - Home arrival flourish",
                "trigger": [{"platform": "state", "entity_id": location_mode_entity, "to": "HOME"}],
                "condition": [
                    {"condition": "state", "entity_id": manual_override_entity, "state": "off"},
                    {"condition": "state", "entity_id": "input_boolean.home_flourish_done_today", "state": "off"},
                ],
                "action": [
                    {"service": "light.turn_on", "target": {"entity_id": light_entity}, "data": {"flash": "short"}},
                    {"delay": "00:00:01"},
                    {"service": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.home_flourish_done_today"}},
                ],
                "mode": "single",
            }
        )

        automations.append(
            {
                "id": "llm_reset_flourish_daily",
                "alias": "Location Lighting Mode - Reset flourish daily",
                "trigger": [{"platform": "time", "at": "00:00:05"}],
                "action": [{"service": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.home_flourish_done_today"}}],
                "mode": "single",
            }
        )

    package: dict = {}

    package.update(input_select_block)

    if "input_boolean" not in package:
        package["input_boolean"] = {}
    package["input_boolean"].update(input_boolean_block.get("input_boolean", {}))

    if flourish_enabled:
        package["input_boolean"].update(flourish_flag_block.get("input_boolean", {}))

    package.update(timer_block)

    package["automation"] = automations

    return yaml.safe_dump(package, sort_keys=False, allow_unicode=True)


app = Flask(__name__)


@app.get("/")
def index():
    options = _get_addon_options()
    cfg = _load_user_config()
    merged = {**options, **cfg}
    return render_template("index.html", cfg=merged)


@app.post("/save")
def save():
    form = request.form

    cfg = {
        "phone_tracker": form.get("phone_tracker", "").strip(),
        "light_entity": form.get("light_entity", "").strip(),
        "location_mode_entity": form.get("location_mode_entity", "input_select.location_mode").strip(),
        "manual_override_entity": form.get("manual_override_entity", "input_boolean.light_manual_override").strip(),
        "dwell_seconds": int(form.get("dwell_seconds", "300")),
        "zone_work": form.get("zone_work", "").strip(),
        "zone_airport": form.get("zone_airport", "").strip(),
        "shopping_prefix": form.get("shopping_prefix", "shopping_").strip(),
        "zones_florida": [z.strip() for z in form.get("zones_florida", "").split(",") if z.strip()],
        "flourish_enabled": form.get("flourish_enabled") == "on",
        "colors": {
            "HOME": {"rgb": form.get("home_rgb", "").strip(), "brightness": form.get("home_brightness", "").strip()},
            "WORK": {"rgb": form.get("work_rgb", "").strip(), "brightness": form.get("work_brightness", "").strip()},
            "FLORIDA": {"rgb": form.get("florida_rgb", "").strip(), "brightness": form.get("florida_brightness", "").strip()},
            "SHOPPING": {"rgb": form.get("shopping_rgb", "").strip(), "brightness": form.get("shopping_brightness", "").strip()},
            "TRAVELING": {"rgb": form.get("traveling_rgb", "").strip(), "brightness": form.get("traveling_brightness", "").strip()},
            "UNKNOWN": {"rgb": form.get("unknown_rgb", "").strip(), "brightness": form.get("unknown_brightness", "").strip()},
        },
    }

    _save_user_config(cfg)
    return redirect(url_for("index"))


@app.post("/apply")
def apply():
    options = _get_addon_options()
    user_cfg = _load_user_config()

    package_rel_path = user_cfg.get("package_path") or options.get("package_path") or "packages/location_lighting_mode_generated.yaml"

    config_dir = Path("/config")
    ok, err = _ensure_packages_enabled(config_dir)

    if not ok:
        return render_template("result.html", ok=False, message=err), 400

    out_path = config_dir / package_rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = _build_package_yaml(options, user_cfg)
    out_path.write_text(content, encoding="utf-8")

    return render_template(
        "result.html",
        ok=True,
        message=f"Wrote {out_path}. If this is your first time using packages, restart Home Assistant. Otherwise reload Automations (and Helpers if needed).",
    )


def main():
    app.run(host="0.0.0.0", port=8099)


if __name__ == "__main__":
    main()
