# Fluix

External ESP for Roblox. Reads the game's memory with `ReadProcessMemory`
(nothing is injected, nothing is written) and draws a transparent,
click-through overlay over the game window.

> **DISCLAIMER** This is against the Roblox ToS and can get accounts banned.
> Roblox has Hyperion/Byfron anti-cheat and updates weekly. This is a memory
> reading / overlay project, basically for fun and to learn how it works. Use
> at your own risk.

## What it does

- Boxes around players (full or corner style)
- Health bar that goes green to red
- Name + distance labels
- Tracers, team filter (skips teammates), max render distance
- Role-based presets for specific games (e.g. Murder Mystery 2)
- Reads memory stealthily (see below)
- No third-party pip packages, stdlib only

## Requirements

- Windows 10/11 64-bit
- Python 3.8+ (from python.org)
- Roblox running, and you have to actually be inside a game
- Game must be **Windowed** or **Fullscreen (borderless)**. Real fullscreen
  (exclusive) can't be overlayed

No admin needed unless Roblox itself is running elevated, then run this the
same way.

## Run it

```
python main.py
```

That's it, no pip installs.

## Keys

| Key | Action |
|-----|--------|
| F8  | Toggle ESP on/off |
| F7  | Settings window |
| END | Quit |

## Config

Everything lives in `config.py` (just edit values, no coding):

- `ESP` - enable/disable boxes, healthbar, name, distance, tracers, team check,
  max distance, box style
- `GAMES` - role presets per game
- `COLORS` - RGB tuples for each element
- `STEALTH` - how the memory reader behaves (see below)
- `OFFSETS` - offset source settings (see below)
- `UPDATE` - GitHub auto-update (see below)

## Stealth

Roblox can't tell that another process is *reading* its memory the way it can
detect injected code, but the code still avoids obvious patterns:

- **Read-only**: no writes to Roblox, no injection, no remote threads
- **Throttled + jittered reads**: memory is polled at ~12 Hz, not every frame,
  with a random +-40% jitter and occasional skips, so there's no clean periodic
  pattern
- **Batched reads**: child arrays are read in one call, not element by element
- **No pattern scanning**: offsets come from a static pointer chain, so nothing
  looks like a scanner
- **Optional pauses**: set `pause_min` / `pause_max` in `STEALTH` to take
  multi-second breaks now and then

This lowers the risk but it's not safe. Accounts can still get banned.

## Offsets

Roblox changes memory layouts on most updates. Fluix grabs fresh offsets at
launch from https://offsets.imtheo.lol (community maintained) and falls back to
`offsets_bundled.json` if the network is down.

To force the bundled ones, set `auto_fetch` to `False` in `config.py`.

If ESP shows nothing and the console says offsets are stale, update
`offsets_bundled.json` with the current values or wait for the remote database
to match your Roblox version.

## Troubleshooting

- **"Could not open Roblox process"** - Roblox isn't running, you're not in a
  game, or privilege levels differ. Run both at the same elevation.
- **"Waiting for a game session"** - you're at the menu or loading screen. The
  script auto-detects the in-game client, so just hit Play and wait a few
  seconds. Joining spawns a new process and it attaches by itself.
- **"DataModel not found"** - Roblox updated and offsets are stale. Turn on
  auto-fetch or update `offsets_bundled.json`.
- **Overlay not showing / behind the game** - switch Roblox to Windowed or
  borderless Fullscreen. Close other always-on-top apps.
- **ESP empty inside a game** - wait a few seconds, the reader re-validates
  periodically. Make sure there are other players.
- **Team filter hides everyone** - set `team_check` to `False`. Games without
  teams treat everyone as enemies, which is what you want.

## Auto-update

The launcher checks GitHub for a newer release when it starts and swaps itself
if one exists. Publishing an update is just creating a new release:

1. Bump `APP_VERSION` in `config.py`
2. `python build.py` (builds `dist/FluixConsole.exe` + `dist/FluixNoConsole.exe`)
3. Push the new launchers to the `build` branch (they live at raw GitHub URLs)
4. Rebuild the installer and create a release: `gh release create vX.Y.Z dist\FluixSetup.exe --repo Aviixxyy/Fluix`

Friends grab `FluixSetup.exe` from the releases page. It only updates on relaunch,
never mid-session.

## Project layout

```
main.py               entry point (attach, overlay loop, hotkeys)
config.py             all toggles, colors, stealth, offset and update settings
memory.py             ReadProcessMemory helpers + process/module lookup
offsets.py            loads offsets (remote fetch + bundled fallback)
offsets_bundled.json  last-known-good offsets
roblox.py             Roblox object model reading + world-to-screen math
esp.py                background reader thread (stealth timing)
overlay.py            transparent GDI overlay window
status.py             single-line console status
stats.py              fps/ping offset finder
themes.py             launcher theme art + accent palettes
ui.py                 settings window
updater.py            GitHub auto-update
```