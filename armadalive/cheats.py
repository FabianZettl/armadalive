"""Manage and activate cheats for RetroArch games."""
import os, re
from PySide6.QtCore import Property, QObject, Signal, Slot

CONFIG = os.path.expanduser("~/.config/retroarch")


class Cheats(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._active = {}  # game_key -> set of cheat indices that are active

    @Slot(str, int)
    def toggle_cheat(self, game_key, cheat_index):
        """Toggle a cheat on/off and write to RetroArch config."""
        if game_key not in self._active:
            self._active[game_key] = set()
        if cheat_index in self._active[game_key]:
            self._active[game_key].remove(cheat_index)
        else:
            self._active[game_key].add(cheat_index)
        self._write_config(game_key)
        self.changed.emit()

    def is_active(self, game_key, cheat_index):
        """Check if a cheat is active."""
        return cheat_index in self._active.get(game_key, set())

    def _write_config(self, game_key):
        """Write active cheats to RetroArch's .opt config file for a game."""
        # game_key format: "system/gamename" for emulated, "steam/appid" for Steam
        if not game_key.startswith("snes/") and not game_key.startswith("nes/") and \
           not game_key.startswith("genesis/") and not game_key.startswith("n64/"):
            return  # only write for emulated games, not Steam

        system = game_key.split("/")[0]
        # assume RetroArch core names match system (snes -> Snes9x, etc)
        # this is a simplification; real mapping would be more complex
        core_name = {"snes": "Snes9x", "nes": "Nestopia", "genesis": "Genesis-Plus-GX"}.get(system, system)

        opt_file = os.path.join(CONFIG, "config", core_name, game_key.split("/")[1] + ".opt")
        os.makedirs(os.path.dirname(opt_file), exist_ok=True)

        # read existing opt file if it exists
        opts = {}
        if os.path.exists(opt_file):
            for line in open(opt_file):
                if "=" in line:
                    k, v = line.split("=", 1)
                    opts[k.strip()] = v.strip()

        # set cheat enables
        opts["cheats_enabled"] = '"true"'
        active = self._active.get(game_key, set())
        for i in range(16):  # RetroArch supports up to 16 cheats
            opts[f"cheat{i}_enable"] = '"true"' if i in active else '"false"'

        # write back
        with open(opt_file, "w") as f:
            for k, v in opts.items():
                f.write(f"{k} = {v}\n")
