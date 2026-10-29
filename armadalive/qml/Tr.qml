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
        "Language": "Sprache", "Logo animation": "Logo-Animation", "Appearance": "Darstellung", "Updates": "Updates", "Version": "Version",
        "Check for updates": "Nach Updates suchen", "Checking…": "Suche …", "Up to date": "Aktuell",
        "Update available": "Update verfügbar", "Install update": "Update installieren", "Installing…": "Installiere …",
        "Installed. The app restarts in a moment.": "Installiert. Die App startet gleich neu.",
        "Updates need the GitHub repository, which does not exist yet.": "Updates brauchen das GitHub-Repository, das es noch nicht gibt.",
        "Repository coming soon": "Repository folgt", "Source code": "Quellcode", "About": "Über",
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
