# AI disclosure

ArmadaLive was developed with the help of AI. The assistant was **Claude Code** (Anthropic), working in a terminal session
with the author, Fabian Zettl, who set the goals, the design direction and the priorities, and who ran and judged the
result on a real AYN Thor.

What that means in practice:

- **A large part of the code, the documentation and the texts was written by the AI.** That includes the Python backend, the
  QML interface, the installer and helper scripts, and this repository's documents.
- **The AI tested on a real device** through SSH (rendering pages to images, calling the helper with valid and invalid input,
  reading logs), but it could not press buttons or watch the screen. Everything that needs a finger on the touch screen
  or a hardware button was checked by the author, and some of it only partly. The README lists what is known to be
  unverified.
- **Mistakes are possible**, including in the parts that touch the system: the optional root helper, fan curves, power
  profiles and RGB settings. Read `scripts/armadalive-helper` before you install it; it is short on purpose.
- **Design and third-party work was not copied.** The dashboard layout follows the look of AYN's stock dual-screen app and
  of the Better Dual Screen Assistant as seen in public screenshots; colours were measured from a screenshot and every
  icon is drawn in this project. No code or assets from those projects are included. See [CREDITS.md](CREDITS.md).

Use ArmadaLive at your own risk. See the [license](LICENSE).
