pragma Singleton
import QtQuick

// Interface language: the English text is the key, German is looked up; anything missing falls back to English.
QtObject {
    property string lang: "en"
    function t(s) { return lang === "de" && de[s] !== undefined ? de[s] : s }

    readonly property var de: ({
        "Game": "Spiel", "Manual": "Handbuch", "Mode": "Modus", "Settings": "Einstellungen", "Tuning": "Tuning",
        "CURRENT FPS": "AKTUELLE FPS", "TEMP": "TEMP", "FAN": "LÜFTER",
        "Clear RAM": "RAM leeren", "Stick LEDs": "Stick-LEDs", "Wi-Fi": "WLAN", "Airplane": "Flugmodus", "Sound": "Ton",
        "Muted": "Stumm", "Auto": "Auto",
        "Brightness": "Helligkeit", "Top screen": "Oberer Bildschirm", "Bottom screen": "Unterer Bildschirm",
        "Volume": "Lautstärke", "Output": "Ausgabe",
        "This game has no manual.": "Für dieses Spiel gibt es kein Handbuch.",
        "This game has no cheats.": "Für dieses Spiel gibt es keine Cheats.",
        "App for slot": "App für Platz", "Remove": "Entfernen", "Cancel": "Abbrechen",
        "Edit profile": "Profil bearbeiten", "CPU governor": "CPU-Governor", "Underclock": "Underclock",
        "Off": "Aus", "On": "An", "Small": "Klein", "Medium": "Mittel", "Large": "Groß",
        "GPU clock max": "GPU-Takt max", "GPU clock min": "GPU-Takt min",
        "Fan curve (drag the points, releasing saves)": "Lüfterkurve (Punkte ziehen, Loslassen speichert)",
        "Stick LED colour": "Farbe der Stick-LEDs",
        "Changing this needs the root helper. Install it under Settings > Setup.": "Zum Ändern wird der Root-Helfer benötigt. Installation unter Einstellungen > Einrichtung.",
        "Language": "Sprache", "Logo animation": "Logo-Animation", "Dim after 10 s": "Nach 10 s abdunkeln", "Appearance": "Darstellung", "Updates": "Updates", "Version": "Version",
        "Check for updates": "Nach Updates suchen", "Checking…": "Suche …", "Up to date": "Aktuell",
        "Update available": "Update verfügbar", "Install update": "Update installieren", "Installing…": "Installiere …",
        "Installed. The app restarts in a moment.": "Installiert. Die App startet gleich neu.",
        "Updates need the GitHub repository, which does not exist yet.": "Updates brauchen das GitHub-Repository, das es noch nicht gibt.",
        "Repository coming soon": "Repository folgt", "Source code": "Quellcode", "About": "Über",
        "Graphs": "Graphen", "Temperature": "Temperatur", "Power": "Leistung", "Battery": "Akku", "last 2 minutes": "letzte 2 Minuten",
        "Screen off": "Bildschirm aus", "Tap two tiles to swap": "Zwei Kacheln antippen zum Tauschen", "Done": "Fertig", "Reset": "Zurücksetzen", "Game rule": "Spielregel", "System rule": "Systemregel",
        "Health check": "Einrichtungs-Check", "ES-DE hooks": "ES-DE-Hooks", "ES-DE event scripts": "ES-DE-Ereignisskripte", "ES-DE media": "ES-DE-Medien",
        "Steam Big Picture link": "Steam-Big-Picture-Verbindung", "FPS source": "FPS-Quelle",
        "Run install.sh again: the ES-DE hooks are missing": "install.sh erneut ausführen: die ES-DE-Hooks fehlen",
        "ES-DE: START > Other Settings > Custom Event Scripts and Browsing Custom Event Scripts": "ES-DE: START > Other Settings > Custom Event Scripts und Browsing Custom Event Scripts",
        "Scrape media in ES-DE (logos and backgrounds)": "In ES-DE Medien scrapen (Logos und Hintergründe)",
        "Steam Big Picture selection needs ~/.steam/steam/.cef-enable-remote-debugging (Decky Loader) and a Steam restart": "Die Big-Picture-Auswahl braucht ~/.steam/steam/.cef-enable-remote-debugging (Decky Loader) und einen Steam-Neustart",
        "gamescope's stats pipe is missing: FPS cannot be read": "Die Stats-Pipe von gamescope fehlt: FPS lassen sich nicht lesen",
        "Screens": "Bildschirme", "General": "Allgemein", "Close game": "Spiel beenden", "Hold Start + Select for 2 s": "Start + Select 2 s halten", "Theme": "Theme", "Changing the LEDs needs the root helper (Settings → Setup).": "Zum Ändern der LEDs braucht es den Root-Helper (Einstellungen → Setup).",
        "Add to Steam": "Zu Steam", "In Steam": "In Steam", "Shortcut created": "Shortcut erstellt", "Already in Steam": "Schon in Steam",
        "Launch the game from ES-DE once first": "Spiel erst einmal aus ES-DE starten", "Steam is not reachable": "Steam nicht erreichbar",
        "Hot": "Heiß", "Battery and heat": "Akku und Hitze", "Warn when it gets hot": "Warnen, wenn es heiß wird",
        "Tailscale connected": "Tailscale verbunden", "Tailscale off": "Tailscale aus", "Tailscale needs a login": "Tailscale braucht eine Anmeldung",
        "Tailscale is not running": "Tailscale läuft nicht", "Tailscale did not switch": "Tailscale hat nicht umgeschaltet",
        "Run once: sudo tailscale set --operator=armada": "Einmalig: sudo tailscale set --operator=armada",
        "Wi-Fi saver": "WLAN sparen", "Resolution": "Auflösung", "render": "Render", "Battery low": "Akku niedrig", "Battery": "Akku",
        "Warn when the battery drops to": "Warnen, wenn der Akku fällt auf", "Charge only up to (needs the root helper)": "Nur laden bis (braucht den Root-Helper)",
        "Backup": "Sicherung", "Settings, game rules and tile order in one file:": "Einstellungen, Spielregeln und Kachelreihenfolge in einer Datei:",
        "Save backup": "Sicherung speichern", "Restore": "Wiederherstellen", "Saved.": "Gespeichert.", "Restored. The app restarts.": "Wiederhergestellt. Die App startet neu.",
        "Close game: hold Start + Select for 2 s": "Spiel beenden: Start + Select 2 s halten", "Keep holding Start + Select to close": "Start + Select weiter halten zum Beenden",
        "Closed": "Beendet", "Follow game": "Folgt dem Spiel",
        "Game rules": "Spielregeln", "Apply automatically": "Automatisch anwenden",
        "While a game is in front, tap Game rule or System rule on the System page to save its power profile and FPS limit here.": "Tippe bei laufendem Spiel auf Spielregel oder Systemregel auf der System-Seite, um Energieprofil und FPS-Limit hier zu speichern.",
        "Setup": "Einrichtung", "Root helper": "Root-Helfer", "AYN button": "AYN-Taste",
        "Fan curves, profile tuning, stick LEDs, Clear RAM": "Lüfterkurven, Profil-Tuning, Stick-LEDs, RAM leeren",
        "Opens ArmadaLive. Restarts InputPlumber, controllers reconnect briefly.": "Öffnet ArmadaLive. Startet InputPlumber neu, die Controller verbinden sich kurz neu.",
        "Installed": "Installiert", "Needs update": "Update nötig", "Not installed": "Nicht installiert", "Active": "Aktiv", "Not set up": "Nicht eingerichtet",
        "Install": "Installieren", "Update": "Aktualisieren", "Set up": "Einrichten", "Working…": "Arbeite …",
        "Wrong password.": "Falsches Passwort.", "Confirm": "Bestätigen",
        "Install the root helper": "Root-Helfer installieren", "Route the AYN button to ArmadaLive": "AYN-Taste auf ArmadaLive legen",
        "Enter your password to confirm. It is passed to sudo and not stored.": "Zur Bestätigung dein Passwort eingeben. Es geht nur an sudo und wird nicht gespeichert.",
        "AI disclosure": "KI-Hinweis",
        "ArmadaLive was developed with the help of AI (Claude Code by Anthropic). A large part of the code and the texts was written by the AI. Mistakes are possible; use at your own risk.":
            "ArmadaLive wurde mit Hilfe von KI entwickelt (Claude Code von Anthropic). Ein großer Teil des Codes und der Texte stammt von der KI. Fehler sind möglich; Nutzung auf eigene Gefahr."
    })
}
