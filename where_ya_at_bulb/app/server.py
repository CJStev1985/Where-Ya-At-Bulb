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


def _parse_csv_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    s = str(value)
    parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p]


def _packages_enabled(config_dir: Path) -> tuple[bool, str | None]:
    configuration_yaml = config_dir / "configuration.yaml"
    if not configuration_yaml.exists():
        return False, "configuration.yaml not found in /config"

    text = configuration_yaml.read_text(encoding="utf-8")
    if "packages:" in text:
        return True, None

    return False, "Home Assistant packages are not enabled in configuration.yaml"


def _candidate_template(user_cfg: dict) -> str:
    phone_tracker = (user_cfg.get("phone_tracker") or "").strip()
    zones_florida = user_cfg.get("zones_florida") or []
    zone_work = (user_cfg.get("zone_work") or "").strip()
    zone_airport = (user_cfg.get("zone_airport") or "").strip()
    shopping_prefix = (user_cfg.get("shopping_prefix") or "shopping_").strip()

    loc_expr = "states('" + phone_tracker + "')"

    parts: list[str] = []
    if zones_florida:
        florida_list = ", ".join(["'" + z + "'" for z in zones_florida])
        parts.append("'FLORIDA' if " + loc_expr + " in [" + florida_list + "] else ")

    if zone_work:
        parts.append("'WORK' if " + loc_expr + " == '" + zone_work + "' else ")

    parts.append("'HOME' if " + loc_expr + " == 'home' else ")

    if zone_airport:
        parts.append("'TRAVELING' if " + loc_expr + " == '" + zone_airport + "' else ")

    if shopping_prefix:
        parts.append("'SHOPPING' if " + loc_expr + ".startswith('" + shopping_prefix + "') else ")

    parts.append("'UNKNOWN'")

    expr = "".join(parts)
    return "{{ (" + expr + ") | trim }}"


def _parse_rgb(value: object) -> list[int] | None:
    if not value:
        return None
    if isinstance(value, list) and len(value) == 3:
        return [int(value[0]), int(value[1]), int(value[2])]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        if len(parts) == 3:
            return [int(parts[0]), int(parts[1]), int(parts[2])]
    return None


def _parse_hex_color(value: object) -> list[int] | None:
    if not value or not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        return None
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return [r, g, b]
    except Exception:
        return None


def _rgb_to_hex(rgb: list[int]) -> str:
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _mode_rgb(cfg_mode: dict) -> list[int] | None:
    rgb = _parse_rgb(cfg_mode.get("rgb"))
    if rgb:
        return rgb
    return _parse_hex_color(cfg_mode.get("hex"))


def _parse_brightness(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_effect(value: object) -> str | None:
    if value in (None, ""):
        return None
    s = str(value).strip()
    return s or None


def _build_package_yaml(options: dict, user_cfg: dict) -> str:
    location_mode_entity = (
        user_cfg.get("location_mode_entity")
        or options.get("location_mode_entity")
        or "input_select.location_mode"
    )
    manual_override_entity = (
        user_cfg.get("manual_override_entity")
        or options.get("manual_override_entity")
        or "input_boolean.light_manual_override"
    )
    dwell_seconds = int(user_cfg.get("dwell_seconds") or options.get("dwell_seconds") or 300)

    phone_tracker = (user_cfg.get("phone_tracker") or "").strip()
    light_entity = (user_cfg.get("light_entity") or "").strip()
    flourish_enabled = bool(user_cfg.get("flourish_enabled"))

    modes = ["FLORIDA", "WORK", "HOME", "SHOPPING", "TRAVELING", "UNKNOWN"]

    dom_ls, obj_ls = location_mode_entity.split(".", 1)
    dom_mo, obj_mo = manual_override_entity.split(".", 1)

    package: dict = {}

    package[dom_ls] = {
        obj_ls: {
            "name": "Location Mode",
            "options": modes,
        }
    }

    package[dom_mo] = {
        obj_mo: {
            "name": "Light Manual Override",
        }
    }

    if flourish_enabled:
        package.setdefault("input_boolean", {})
        package["input_boolean"].update(
            {
                "home_flourish_done_today": {
                    "name": "Home Arrival Flourish Done Today",
                }
            }
        )

    package["timer"] = {
        "mode_dwell": {
            "name": "Mode Dwell Timer",
            "duration": f"00:{dwell_seconds // 60:02d}:{dwell_seconds % 60:02d}",
        }
    }

    automations: list[dict] = []

    if phone_tracker:
        candidate = _candidate_template(user_cfg)

        automations.append(
            {
                "id": "wyab_compute_mode_start_dwell",
                "alias": "Where-Ya-At Bulb - Start dwell on location change",
                "trigger": [{"platform": "state", "entity_id": phone_tracker}],
                "condition": [],
                "action": [
                    {"variables": {"candidate": candidate}},
                    {
                        "choose": [
                            {
                                "conditions": [
                                    {
                                        "condition": "template",
                                        "value_template": "{{ candidate != states('" + location_mode_entity + "') }}",
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
                "id": "wyab_compute_mode_commit",
                "alias": "Where-Ya-At Bulb - Commit mode after dwell",
                "trigger": [
                    {
                        "platform": "event",
                        "event_type": "timer.finished",
                        "event_data": {"entity_id": "timer.mode_dwell"},
                    }
                ],
                "action": [
                    {"variables": {"candidate": candidate}},
                    {
                        "condition": "template",
                        "value_template": "{{ candidate != states('" + location_mode_entity + "') }}",
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
        colors = user_cfg.get("colors") or {}

        choose_sequences: list[dict] = []
        for mode in modes:
            cfg_mode = colors.get(mode, {})
            rgb = _mode_rgb(cfg_mode)
            bri = _parse_brightness(cfg_mode.get("brightness"))
            eff = _parse_effect(cfg_mode.get("effect"))

            light_data: dict = {}
            if rgb:
                light_data["rgb_color"] = rgb
            if bri is not None:
                light_data["brightness"] = bri
            if eff:
                light_data["effect"] = eff

            if not light_data:
                continue

            choose_sequences.append(
                {
                    "conditions": [{"condition": "state", "entity_id": location_mode_entity, "state": mode}],
                    "sequence": [
                        {"condition": "state", "entity_id": manual_override_entity, "state": "off"},
                        {"service": "light.turn_on", "target": {"entity_id": light_entity}, "data": light_data},
                    ],
                }
            )

        if choose_sequences:
            automations.append(
                {
                    "id": "wyab_apply_light_on_mode_change",
                    "alias": "Where-Ya-At Bulb - Apply lighting on mode change",
                    "trigger": [{"platform": "state", "entity_id": location_mode_entity}],
                    "action": [{"choose": choose_sequences}],
                    "mode": "restart",
                }
            )

    if flourish_enabled and light_entity:
        automations.append(
            {
                "id": "wyab_home_flourish_once_daily",
                "alias": "Where-Ya-At Bulb - Home arrival flourish",
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
                "id": "wyab_reset_flourish_daily",
                "alias": "Where-Ya-At Bulb - Reset flourish daily",
                "trigger": [{"platform": "time", "at": "00:00:05"}],
                "action": [{"service": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.home_flourish_done_today"}}],
                "mode": "single",
            }
        )

    if automations:
        package["automation"] = automations

    return yaml.safe_dump(package, sort_keys=False, allow_unicode=True)


app = Flask(__name__)


@app.get("/")
def index():
    options = _get_addon_options()
    cfg = _load_user_config()
    merged = {**options, **cfg}
    colors = merged.get("colors")
    if isinstance(colors, dict):
        for mode, cfg_mode in colors.items():
            if not isinstance(cfg_mode, dict):
                continue
            if cfg_mode.get("hex"):
                continue
            rgb = _parse_rgb(cfg_mode.get("rgb"))
            if rgb:
                cfg_mode["hex"] = _rgb_to_hex(rgb)
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
        "effects": _parse_csv_list(form.get("effects_csv", "")),
        "colors": {
            "HOME": {
                "hex": form.get("home_color", "").strip(),
                "brightness": form.get("home_brightness", "").strip(),
                "effect": form.get("home_effect", "").strip(),
            },
            "WORK": {
                "hex": form.get("work_color", "").strip(),
                "brightness": form.get("work_brightness", "").strip(),
                "effect": form.get("work_effect", "").strip(),
            },
            "FLORIDA": {
                "hex": form.get("florida_color", "").strip(),
                "brightness": form.get("florida_brightness", "").strip(),
                "effect": form.get("florida_effect", "").strip(),
            },
            "SHOPPING": {
                "hex": form.get("shopping_color", "").strip(),
                "brightness": form.get("shopping_brightness", "").strip(),
                "effect": form.get("shopping_effect", "").strip(),
            },
            "TRAVELING": {
                "hex": form.get("traveling_color", "").strip(),
                "brightness": form.get("traveling_brightness", "").strip(),
                "effect": form.get("traveling_effect", "").strip(),
            },
            "UNKNOWN": {
                "hex": form.get("unknown_color", "").strip(),
                "brightness": form.get("unknown_brightness", "").strip(),
                "effect": form.get("unknown_effect", "").strip(),
            },
        },
    }

    _save_user_config(cfg)
    return redirect(url_for("index"))


@app.post("/apply")
def apply():
    options = _get_addon_options()
    user_cfg = _load_user_config()

    package_rel_path = (
        user_cfg.get("package_path")
        or options.get("package_path")
        or "packages/where_ya_at_bulb_generated.yaml"
    )

    config_dir = Path("/config")
    ok, err = _packages_enabled(config_dir)
    if not ok:
        return render_template("result.html", ok=False, message=err), 400

    out_path = config_dir / package_rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    content = _build_package_yaml(options, user_cfg)
    out_path.write_text(content, encoding="utf-8")

    return render_template(
        "result.html",
        ok=True,
        message=(
            f"Wrote {out_path}. If this is your first time using packages, restart Home Assistant. "
            "Otherwise reload Automations (and restart if helpers don't appear immediately)."
        ),
    )


def main() -> None:
    app.run(host="0.0.0.0", port=8099)


if __name__ == "__main__":
    main()
