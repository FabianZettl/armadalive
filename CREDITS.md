# Credits

ArmadaLive stands on other people's work. Thank you.

- **[Armada OS](https://github.com/armada-os/armada)** – the operating system this runs on, and the `armada-power`,
  `armada-rgb` and InputPlumber integration it exposes.
- **[ThorHUD](https://github.com/mtklein/thorhud)** by Mike Klein (MIT) – showed that a bottom-screen dashboard is possible on
  Armada OS and how the AYN button can be routed to an app through an InputPlumber capability-map override.
  `scripts/ayn-button.sh` is adapted from ThorHUD's `ayn-button.sh`; its license text follows below.
- **[Better Dual Screen Assistant](https://github.com/stormpanda/better-dual-screen-assistant)** by stormpanda, and AYN's
  stock dual-screen app – the look this interface follows. Only public screenshots were used as a reference; **no code,
  icons or colour values were taken from the repository**, which is under its own source-available license.
- **[ES-DE](https://es-de.org)** – the frontend whose event scripts, media and gamelists ArmadaLive reads.
- **[Decky Loader](https://decky.xyz)** – enables the local Steam UI debug port that lets ArmadaLive see which app is
  highlighted in Big Picture.
- **[libretro database](https://github.com/libretro/libretro-database)** – the cheat files (`.cht`) shown on the Cheats page
  are read from the user's own RetroArch cheats folder; none are bundled here.
- **[Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/)** – the toolkit, shipped with Armada OS.
- **Claude Code** by Anthropic – wrote much of the code, see [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

AYN, AYN Thor, Steam, Valve, ES-DE, RetroArch and the other names mentioned belong to their owners. ArmadaLive is an
independent project and is not affiliated with or endorsed by any of them.

## ThorHUD license

```
MIT License

Copyright (c) 2026 Mike Klein

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
