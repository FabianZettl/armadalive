# Changelog

## Unreleased

- **Close game**: hold Start + Select for two seconds to close the game or emulator in front, with a countdown on the bottom screen. Setting to turn it off.
- **Follow game** theme: the palette is taken from the artwork of the game in front.
- **Media bar** for whatever plays on the main screen (MPRIS): title, previous, play/pause, next.
- **Battery**: low-battery warning (15/20/30 %, and 10 %), optional charge limit 80/90 % through the root helper.
- **Wi-Fi saver** tile (Wi-Fi power saving on or off) and a **Resolution** tile for PPSSPP, Dolphin and ARMSX2, stored as part of a game rule.
- **Backup** of settings, game rules and tile order as one file (Settings).
- The root helper learned `wifi-powersave` and `charge-limit`; Setup shows *Needs update* until it is updated.
- Dashboard tiles can be rearranged: hold one, tap another to swap; the order is saved.
- **Fixed:** theme, accent, language, logo animation and dimming were forgotten at every restart (the settings file was read wrongly and the defaults won).
- **Graphs** (FPS, CPU, temperature, power, battery) and the battery time left in the status line.
- **Game rule** and **System rule**: remember a power profile and FPS limit for a game or a whole system and apply it when the game starts; listed under Settings.
- **Screen off**: hold the AYN button, or the new tile; black, touches ignored, wake with the AYN button or a long touch.
- **Health check** in Settings: what is missing for ES-DE and Steam, with a hint for each.
- Fixed errors in the gauges while the dashboard was still being laid out.
- Updates are checked against a published SHA-256 and refused without one. Tests, a GitHub Actions workflow and `scripts/make-release.sh`.
- Five new themes: **SteamOS**, **SNES**, **Game Boy**, **PS2** and **Famicom**, all dark so the white system logos stay readable.
- The screen dims a little after 10 seconds without a touch; a touch, or a new game or logo, brightens it again. Can be switched off in Settings.
- On the Game page the bar and status line hide again after 3 seconds (was 5).

## 0.1.0

First public release.

- Bottom-screen companion for the AYN Thor on Armada OS, always full screen, status line and bar appear on a swipe up.
- **Game**: the running game with its logo and background (a gentle idle motion, cross-fade between games), taken from ES-DE's media. Detects ES-DE selections, running
  emulators (by the ROM they were started with), Steam games, and the app highlighted in Steam Big Picture.
- **Manual** and **Cheats** pages, listed only when the current game has them.
- **Apps**: a 3×3 grid of apps you choose, launched on the bottom screen.
- **Mode**: brightness of both screens and the stick LEDs, volume.
- **System**: dashboard with FPS, quick settings, temperature, fan and four gauges; power profile, fan curve and GPU clock.
- **Tuning** (optional root helper): governor, underclock, GPU limits, fan-curve editor, RGB.
- **Settings**: English (default) and German, five themes with accent colours, logo animation on or off, in-app update, about and AI disclosure.
- **Setup** in Settings: install the root helper and route the AYN button with a button and a password prompt; greyed out once done.
- The AYN button always brings the app to the front.
