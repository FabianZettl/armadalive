# Changelog

## 0.8.0

- **The mode pill is the screen's refresh rate** ("120 Hz MODE"): a tap sets the display's dynamic refresh rate and the frame limit to 60 or 120 together, and the pill shows the rate that is set. With frame generation on, FPS above the mode say "with frame gen". Not checked with a game running.
- **Rules page** (System > Rules): the game rules moved out of Settings. One Rules tile replaces the four rule tiles, the resolution tile and the GPU tile (GPU limits are in Tuning). The list names each game (from its saved title, the play history or Steam), not only its Steam id. Wi-Fi saver and Airplane moved to Settings, and the Tailscale tile only shows when Tailscale is installed.
- **Favorites**: a heart on the Game info page; the smart folder "Favorites" lists them. Every folder has a Random button that starts a random game from it.
- **Search in the app picker**, across all tabs.
- **Charge limit**: if the battery's firmware refuses the limit (the Thor's does), the setting says so and goes away instead of failing silently.
- **One playtime record**: the Game page's play time now uses the same history as the Playtime page (the old separate `playtime.json` counter is no longer used).
- **ES-DE system folders** show the system picture from the ES-DE theme in use.
- **Folders in the Apps grid**: manual folders (long-press a slot, "Add to folder") and smart folders: Recently played, Steam, and one per ES-DE system. Folder tiles show a cover mosaic. A dice tile launches a random game. Not tried with real touch input.
- **Game info page** (Game page, "Info" button): ES-DE description, genre, developer, year, rating, playtime, times started, last played and screenshots.
- **Playtime page** (System page): bars for the last 7 days, total and most played. Playtime is recorded while a game runs; the first start imports Steam and ES-DE last-played data.
- **Frame gen tile** (System page): switches frame generation for Eglantine, Eden and TotK on or off. It only creates or removes `~/.config/mako-thor/off`, which the launchers read at start, so a running game keeps the setting it started with.
- **Controls page: Esc is always there**, left of the emulator buttons, whichever emulator is running (it opens the menu of recompiled PC ports such as Savage Wind and TotK).

## 0.7.2

- **The AYN tap in desktop mode raises ArmadaLive above other windows** (issue #5): the app looked for the Plasma window manager only on the bottom screen's private bus, so in desktop mode, where Plasma sits on the ordinary session bus, it could not ask Plasma to bring the window forward and the taskbar icon only blinked. It now also looks on the session bus. Not tried in desktop mode on a Thor.
- **Without a Plasma window manager the AYN tap only brings ArmadaLive up** (it never hides itself there): on the bare X11 side of the bottom screen nothing can bring a hidden window back, so a tap that "sent it to the background" looked like it did nothing. The tap log line now says which platform the app runs on and whether it found Plasma, so the next report shows it.

## 0.7.1

- **The screen stays bright while you use it** (fixes 0.7.0, where this did not work, issue #4): the 10 second timer is now restarted by every touch, tap, click and key press on the window, however an item takes it (a list that scrolls, a button, the app grid). Before, only touches that reached one particular item restarted it, so tapping or swiping in some places still let it run out. A finger going down or up always counts, movement counts a few times a second. Checked with simulated clicks and a list drag in a real Qt Quick window (they were all seen), not by watching the screen.

## 0.7.0

- **Tasks** (new tile on the System page): a small task manager for the bottom screen. It lists what is open there (a browser, a file manager, ...) with the memory each program uses, one line per program even if it has several windows. Tap a line to go to that window, *Close* asks it to close like its own close button, *End* (two taps) ends the program and everything it started if it hangs. ArmadaLive's own window and Plasma's panels are not listed. It asks the bottom session's KWin through a short script, as kdotool does. Tried on a Thor with Firefox: listed and closed; not tried with several different programs at once. Asked for by users who could only close Firefox with its own X.
- **The AYN tap works after a boot in Game mode** (issue #5): if the Plasma session was not up within 30 seconds, ArmadaLive started on the X11 side of the bottom screen, where Plasma cannot raise it (no AYN tap, no keyboard) and it stayed there. Now it ends itself as soon as the Plasma session shows up, and the unit starts it again as a Plasma client. That also explains why going to the desktop and back helped: it restarts the app.
- **The screen no longer dims while a finger is on it** (issue #4): the 10 second timer only restarted when the finger moved; a finger that rests, or slow scrolling, let it run out. It now checks whether a touch is active before it dims.
- **Steam Big Picture link** (issue #3): the check no longer requires the marker file `~/.steam/steam/.cef-enable-remote-debugging`, the working connection is the test (the switch in Steam's developer settings does not create that file), and the Big Picture window is also found under the title "Steam Big Picture Mode" (before it only matched titles starting with "Big").

## 0.6.1

- **ArmadaLive starts in the bottom Plasma session at boot, not on its X11 side**: the start script used the bottom gamescope's X11 display as soon as that gamescope had written its environment file, which at boot is before the Plasma session is up. An X11 window is invisible to Plasma's KWin, so tapping the AYN button could not bring the window to the front and the on-screen keyboard could not attach to it. It now waits for the Plasma session (up to 30 seconds) before it falls back to X11. Found by a health check after the Armada OS beta update (`scripts/armada-check.sh`, new: checks services, the bottom session, the keyboard, the AYN button route, brightness, power, helper, Steam and ES-DE and prints PASS / FAIL). Tested by restarting the service and by tests for the wait; not by a reboot.
- **Known, not ours: the charge limit on the Armada OS beta `20261109`**: writing the limit now fails with "the battery did not accept the limit (Connection timed out)" (before, the write passed but the battery always read back 0). The battery controller or the image refuses it; ArmadaLive only shows the message.

## 0.6.0

- **Themes change more than colours**: each theme now also has a *shape* (round, pill, soft, square or cut corners for buttons, cards, icon discs and app tiles), a faint *backdrop pattern* (dots, grid, scan lines, diagonal stripes, checkerboard or stars), a *motion* feel (smooth, snappy, bouncy, gentle or stepped animations, used for the app grid and the buttons) a *font* (six fonts ship with the app: pixel, terminal, techno, rounded, fantasy and handwriting, plus the system's monospace and serif) and an *icon style* (thin, normal, bold, blocky with square ends, sharp lines or duotone with a tinted fill), and thicker outlines. For example Game Boy and Minecraft are square, monospace and stepped, Kirby and Mario are pill-shaped and bouncy, Cyberpunk has cut corners and scan lines. The picker previews each theme's shape and outline. Seen in snapshots on a Thor, not on the display; the animations are only described by their timing, not watched.
- **The stick LEDs follow the theme** by default: they take the theme's accent colour, also when the theme or the accent changes (a moment later, because it fades), as long as the LEDs are on and the root helper is installed. Picking a colour of your own on the Mode page stops that; the *Theme* circle there turns it on again (kept in `ui.json` as `ledFollow`). Tried on a Thor by switching themes: the colour in `/etc/armada/rgb.json` followed.
- **Themes in groups, and 40 new themes**: Settings lists the themes under *General*, *Consoles*, *Operating systems and launchers* and *Games*. *Games* gets Ocarina of Time, Breath of the Wild, Tears of the Kingdom, God of War and Final Fantasy VII, and also Super Mario, Pokémon, Sonic, Metroid, Cyberpunk 2077, Hollow Knight, Celeste, Halo, Minecraft, Animal Crossing, Splatoon, Kirby, Skyrim and Stardew Valley. *Consoles* gets Dreamcast, Sega Saturn, Mega Drive, Nintendo 64, GameCube, Wii, Switch, Xbox, PlayStation Vita and Atari 2600. *Operating systems and launchers* gets Windows XP, Windows 11, macOS, Android, Ubuntu and KDE Plasma. *General* gets Dracula, Nord, Gruvbox, Solarized Dark and an amber terminal. Several are light themes. The picker is tabs for the four groups with a small preview for each theme (its background, a card, its accent and its name in its own colours) instead of one long list. The colours are my guess at each look, not measured, and a test checks that text stays readable; the accent can be changed as for every theme.

## 0.5.2

- **ArmadaLive now starts on boot in Game mode** (reported again on issue #2 after 0.5.1, with a fresh install): the 0.5.1 wait only applied once the bottom session's marker file existed, but this unit starts before that session is even started, so the script found nothing, exited with success and was never started again (journal: "no bottom session and no desktop display found; nothing to show it on"). The start script now keeps looking for the bottom session or a desktop display for up to 60 seconds and then fails, so the unit retries. Checked with tests for both outcomes and by restarting the service on a Thor; not by a reboot.
- **Idle rule and base rule** (tiles on the System page): the base rule applies to every game that has no game or system rule of its own, the idle rule when no game runs any more (not while Steam's menu is only in front of a running game). Both save the current power profile and FPS limit like the other rules and show in the rule list in Settings. A short message says when a rule was saved, removed or loaded, and Settings shows which was loaded last. Tried with a game rule for a non-Steam shortcut (power profile and FPS limit switched when it started); the idle rule is covered by tests, not tried on the device.
- **Non-Steam shortcuts that are games** (Tears of the Kingdom, Moonlight, ...) are recognised as the game in front, so game rules work for them. ES-DE itself is not counted as a game.
- **The app grid scrolls sideways again**: the page swipe took the drag over (the first fix locked it on touch-down, which came too late). On the Apps page, and on the Game page while nothing runs, a sideways drag now scrolls the grid; pages are switched with the bar there. Checked with a simulated drag (the grid moved 420 px alone, and none with the page swipe around it), not with a finger.
- **ES-DE games in a folder of their own**: the app picker reads a system from the folder ES-DE's own `es_systems.xml` gives it, not only from `<ROM directory>/<system>`.

## 0.5.1

- **ArmadaLive starts again on boot in Game mode** (reported on issue #2): since 0.4.6 `scripts/run.sh` took a bottom session that was still starting for desktop mode, found no screen, and ended without an error, so the unit never retried. It now sees that the bottom session has been started (its marker file exists), waits up to 20 seconds for its socket and otherwise fails, so the unit tries again after 3 seconds. Desktop mode is unchanged. Found by reading the script, not by rebooting a Thor; the test covers the decision, not the boot itself.

## 0.5.0

- **Light themes**: *Nintendo DS* (icy white and blue), *Nintendo 3DS* (white and red) and *iiSU* (pale lavender and blue), plus the dark *iiSU Night*. Text on an accent colour (buttons, slider icons, toasts) turns dark or white to stay readable on a light theme; the dark themes look as before. ES-DE's white system logos get a dark plate behind them on a light theme. The colours are guesses from screenshots of the Nintendo handhelds and the iiSU launcher, not measured; the accent can be changed as for every theme.
- **Settings left the bar** (one icon less): it is a tile on the System page now, next to Tuning and Graphs, and opens the same page. The tile starts at the end of the tile order; move it where you like.
- The bar entry *Trackpad* is called **Controls** now (same page).
- **Apps grid with Steam games and shortcuts**: the grid scrolls sideways (three rows, as many tiles as you add, the last empty tile adds one). Besides desktop apps the picker lists your installed Steam games and non-Steam shortcuts (read from Steam's `appmanifest_*.acf` and `shortcuts.vdf`), shown as rounded square covers from Steam's own cover cache. A Steam tile starts the game through Steam on the main screen. Covers are cut once and cached in `~/.cache/armadalive/covers`. A game without a cover shows its first letter. The picker has tabs: Apps, Steam and one per ES-DE system that has games. An ES-DE game starts through a Steam shortcut: ArmadaLive rebuilds the launch command from ES-DE's own system definitions and find rules (read from the ES-DE AppImage and your `custom_systems`, honouring the alternative emulator set in the gamelist; the result matched ES-DE's log for the three games it could be compared with), creates the shortcut with the ES-DE artwork on the first tap and starts it, so it runs on the main screen like any other game. The tile size comes from the window (the width, and the height left with the status line, media bar and dock showing), so three rows always fit, the tiles keep their size when the dock is hidden and just stay centred; scrolling the grid or the picker's tabs no longer switches the page; tiles pop in, and a tapped tile swells and flashes. Not tried: starting an ES-DE game from a tile, games on a library Steam has not mounted, and covers of shortcuts that have no picture in Steam's `grid` folder.

## 0.4.6

- **Desktop mode**: the start script no longer sends Qt to the bottom screen's Wayland socket when that session does not exist. Without it Qt aborted, and the service started and died every three seconds (the icon that flashed in the taskbar, issue #2). In desktop mode `scripts/run.sh` now uses the desktop's own Wayland socket (`wayland-*`, else X11) and starts the app with `--windowed`, an ordinary window instead of the always-fullscreen bottom screen. With no display at all it exits quietly. The unit restarts only after a failure (`Restart=on-failure`; run `install.sh` again for it). Not tried in desktop mode itself, it is chosen by which sockets exist.
- **FPS no longer drops to 0 between readings** (issue #1): gamescope writes its `fps=` line every 5 seconds, and the display went to 0 after 3 seconds without one, so it alternated between the value and 0. It now waits for two missing readings. Not changed: the value is gamescope's own, which can differ from Steam's performance overlay (the report has 39/40 against Steam's 29/30), and that needs a second look.

## 0.4.5

- **Quieter and smoother**: the quick-settings read (Wi-Fi, Bluetooth, volume, Wi-Fi saver, VPN), the media player check, Gamescope's X properties and the game-process scan ran on the UI thread and spawned a handful of processes each; the quick-settings read alone blocked it for about 200 ms every 2 seconds on a Thor. They now run on a worker thread (`armadalive/poller.py`), Wi-Fi and Bluetooth come from `/sys/class/rfkill` instead of `nmcli` and `rfkill`, and the volume is one `wpctl` call instead of two. The app's idle CPU use went from about 7 % to 4 % of one core. Still polled on the UI thread: the system monitor (20 ms a second, mostly D-Bus property reads).
- **Dimming**: the 10-second timer no longer runs (and dims) when *Dim after 10 s* is off, and a finger that stays down and moves (slider, scroll, trackpad) keeps the screen awake; before, only the first touch did.
- **Charge limit**: a battery that refuses the limit (the Thor's controller times out on the Preview image: writing `charge_control_end_threshold` fails with *Connection timed out*) now gives a plain message instead of a Python traceback, and the limit is only remembered once the battery kept it.

## 0.4.0

- **Trackpad** page: the bottom screen as a Steam Deck's two trackpads and back buttons. The right pad moves the pointer, the left one scrolls; a tap clicks (left pad: right click) and holding a moment before moving drags. A flick lets the pointer glide on like a trackball (switch *Glide*). L4, L5, R4 and R5 and the shortcut keys Esc, Tab, Enter, Space and Backspace are on the page too. Touches buzz the haptic motor: a click for taps and keys, a light tick every 40 px of pointer travel and for every scroll step. It all comes from virtual devices on `/dev/uinput` (the `input` group may use it, no setup). The back buttons are a second controller to Steam and are mapped in Steam Input, because InputPlumber's own Steam Deck controller has no input for them from here (its D-Bus `SendEvent` crashes in 0.83). Not tested in a game yet.
- **Ludo (RomM) on the bottom screen**: while Ludo checks and syncs saves before a game starts, a bar shows *Checking saves…*, *Syncing saves: <game>*, *Starting: <game>*, and *Uploading saves…* after a game closed. The game highlighted in Ludo shows its logo and background like in ES-DE: the ES-DE media of its ROM for a downloaded game, the RomM server's screenshot behind the title for any other (RomM has no logos); a running game from Ludo is recognised too. It reads Ludo's log (`~/homebrew/logs/ludo`, written for v1.0.0-beta.27, a different wording only means no bar) and `~/.config/ludo/library_snapshot.json`; the highlighted game needs Steam's debug port like the Steam selection.
- **Tuning changes are taken back unless you keep them**, like a new screen resolution: after changing the governor, underclock, GPU limits or a fan curve (also with the fan tile on System), a bar asks *Keep this setting?* for 15 seconds, and without an answer the old value is restored. A change that was never confirmed (app closed, crash) is undone the next time the app starts. A chain of changes goes back to the value before the first one and can stay unconfirmed for 60 seconds at most.
- **Presets** on the Tuning page: *Cool*, *Quiet* and *Fast* for the selected profile. They only use what the device has (GPU limits snap to a real step, governors and fan curves that do not exist are left out), and `armadalive/presets.json` can override a preset for one model (`ayn,thor` or `ayn,thor:pro`). The model comes from the device tree; Pro, Base and Max are told apart by memory, which is a guess.
- **Starts after a system update that drops PySide6**: the service now starts through `scripts/run.sh`, which uses the system Python when it has PySide6 and the private copy otherwise, instead of the one interpreter install.sh happened to find. Before, such an update left the app in a restart loop until `install.sh` was run again.
- **Shows up when the bottom Plasma session is down**: `scripts/run.sh` then starts the app on the bottom screen's own gamescope through its X11 side (`DISPLAY` from `armada-bottom-env`) instead of crashing on the missing `armada-plasma-bottom` socket. What needs Plasma (bringing the window forward through KWin, the keyboard tile) does not work there. Seen on Preview 20261101.648e7ef, where the Plasma session fails to start (armada-os/armada#821).
- **Bug report form** for GitHub issues (device model, Armada OS version, ArmadaLive version, page).

## 0.3.0

- **Keyboard** tile: shows the system on-screen keyboard of the bottom screen and keeps it up (it is put back if Plasma hides it) until the tile is tapped again, for dialogs (such as the wallet password) that do not ask for it themselves.
- **Password dialog has its own on-screen keyboard** (letters, shift, numbers and symbols). Keys from a Bluetooth or system keyboard go to the session on the top screen, so typing the sudo password for Setup was impossible before.
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
