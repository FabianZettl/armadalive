# Changelog

## Unreleased

- **Survives a system image without PySide6:** `install.sh` now creates its own Python environment with PySide6 and PyMuPDF when the system has none (a system update removed it and the service no longer started). Manuals are drawn with PyMuPDF where Qt has no PDF module.
- **The AYN button is a toggle:** a tap brings ArmadaLive up, and a tap while it is in front sends it to the background, so a dual-screen game such as Azahar shows again. Holding the button still switches the screen off.
- **Apps page** can be switched off in Settings; the bar then has four entries. The app grid still shows on the Game page while nothing is running.
- **Tailscale** tile: switch Tailscale on or off, with a shield in the status line while it is connected. Needs the user to be Tailscale's operator (`sudo tailscale set --operator=<user>`); without it the app says so.
- **Heat warning:** a popup at 80, 85 or 90 °C (Settings → Battery and heat, default 85), with the running power profile, at most every five minutes.
- **Add to Steam** tile: puts the game in front into Steam's library as a shortcut, with cover, background and logo from ES-DE's media. It uses the launch command ES-DE logged when it started the game (so start the game from ES-DE once first), knows when the shortcut exists already, and answers with a popup.

## 0.2.0

- **Mode** page redone: bigger cards and thick bars, the stick LEDs get on/off, brightness, a rainbow bar and colour swatches.
- **Settings** page tidied: one button per option that flips it, grouped into *General* and *Appearance*. More room to the screen edge on every page.
- The window goes back to full screen whenever something takes it out of it. The app grid no longer flashes oversized cells on the first swipe.
- The FPS reader can no longer die silently on a bad line, and shows 0 when gamescope restarts.
- **Manual** and **Cheats** left the bar: tap the Game page to show them as buttons.
- **Close game**: hold Start + Select for two seconds to close the program in front (emulator, ES-DE or a Steam game, never Steam itself), with a countdown on the bottom screen. Setting to turn it off.
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
