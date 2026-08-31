import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


PROCESS_NAME = "RobloxPlayerBeta.exe"

ESP = {
    "box": True,
    "box_corners": False,
    "healthbar": True,
    "name": True,
    "distance": True,
    "tracers": False,
    "tool": False,
    "tool_refresh_s": 0.5,
    "team_check": True,
    "exceptions": "",
    "show_local_player": False,
    "max_distance": 1500.0,
    "distance_units": "studs",
    "character_height": 5.0,
    "hrp_ratio": 0.45,
    "dynamic_box": True,
    "extents_refresh_s": 1.5,
    "box_width_ratio": 0.5,
    "min_box_height": 1.5,
    "max_esp_entries": 0,
    "camera_distance": 8.0,
    "fade_dead": True,
    "skip_dead": False,
    "dead_box_scale": 0.5,
    "dead_tracer_scale": 0.55,
    "highlight_target": True,
    "auto_preset": True,
    "item_esp": True,
    "item_classes": "Tool",
    "item_distance": 300.0,
    "role_refresh_s": 2.0,
    "occlusion": False,
    "occ_scan_s": 4.0,
    "occ_rate": 0.12,
    "debug": False,
}





GAMES = {
    "phantom_forces": {
        "name": "Phantom Forces",
        "enabled": True,
        "place_id": "292439477",
        "no_closest_highlight": False,
        "alt_characters": True,
        "team_color_teams": True,
        "roles": {},
    },
    "murder_mystery_2": {        "name": "Murder Mystery 2",
        "enabled": False,
        "place_id": "142823291",
        "no_closest_highlight": True,
        "roles": {
            "murderer": {
                "label": "Murderer",
                "color": [255, 60, 60],
                "tracer": True,
                "box": True,
                "name": True,
                "weapons": ["knife", "blade", "murderer", "shank"],
                "teams": ["murderer", "killer", "murd"],
            },
            "sheriff": {
                "label": "Sheriff",
                "color": [80, 140, 255],
                "tracer": True,
                "box": True,
                "name": True,
                "weapons": ["gun", "pistol", "revolver", "shotgun", "sheriff"],
                "teams": ["sheriff", "sher", "police"],
            },
            "innocent": {
                "label": "Innocent",
                "color": [80, 255, 140],
                "tracer": True,
                "box": True,
                "name": False,
                "weapons": [],
                "teams": ["innocent", "civilian"],
            },
        },
    },
    "pordier_at_war": {
        "name": "Pordier at War",
        "enabled": True,
        "place_id": "8791578652",
        "no_closest_highlight": False,
        "alt_characters": False,
        "max_esp_entries": 20,
        "roles": {},
    },
}

COLORS = {
    "box": (255, 255, 255),
    "box_teammate": (80, 255, 140),
    "box_enemy": (255, 70, 70),
    "name": (255, 255, 255),
    "name_teammate": (80, 255, 140),
    "name_enemy": (255, 90, 90),
    "distance": (255, 255, 255),
    "tool": (255, 220, 120),
    "shadow": (35, 35, 35),
    "health_bg": (35, 35, 35),
    "health_border": (20, 20, 20),
    "health_full": (0, 255, 0),
    "health_low": (255, 0, 0),
    "tracer": (255, 255, 255),
    "tracer_teammate": (80, 255, 140),
    "tracer_enemy": (255, 70, 70),
    "dead": (125, 125, 138),
    "dead_tracer": (80, 80, 94),
    "highlight": (139, 92, 246),
    "occlusion": (139, 92, 246),
    "item": (0, 200, 255),
}

STEALTH = {
    "update_hz": 144.0,
    "jitter": 0.02,
    "skip_chance": 0.0,
    "humanize": True,
    "hz_min": 90.0,
    "hz_max": 144.0,
    "pause_min": 0.0,
    "pause_max": 0.0,
    "validate_every": 120,
}

AIMBOT = {
    "enabled": False,
    "mode": "hold",
    "hotkey": 0x45,
    "fov_px": 250.0,
    "speed": 0.06,
    "max_distance": 300.0,
    "target": "head",
    "stutter": 3.0,
    "curve": 0.5,
    "orbit_radius": 60.0,
    "lock_keep": 1.5,
    "threat_first": True,
    "threat_fov_deg": 14.0,
    "fallback_closest": True,
    "show_fov": True,
    "trigger": False,
    "trigger_hotkey": 0x05,
    "trigger_interval": 0.18,
    "trigger_padding": 1.15,
}

OFFSETS = {
    "auto_fetch": True,
    "fetch_url": "https://offsets.imtheo.lol/offsets.json",
    "fetch_timeout": 8,
}

KEYS = {
    "toggle": 0x77,
    "quit": 0x23,
    "settings": 0x76,
}

HUD = {
    "enabled": True,
    "show_title": True,
    "font_size": 1,
    "fps": True,
    "ping": True,
    "players": True,
    "follow_theme": True,
    "bg": [18, 20, 26],
    "border": [139, 92, 246],
    "text": [236, 234, 242],
    "layout": {
        "fps": [12, 12, 96, 30],
        "ping": [108, 12, 96, 30],
        "players": [204, 12, 116, 30],
    },
}

CONSOLE_TITLE = "Fluix Launcher"
FONT_SIZE = 14

THEME = "fluix"

APP_VERSION = "2.3.5"




UPDATE = {
    "enabled": True,
    "github_user": "Aviixxyy",
    "github_repo": "Fluix",
    "check_timeout": 3,
    "download_timeout": 120,
}
