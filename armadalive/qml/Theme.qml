pragma Singleton
import QtQuick

QtObject {
    id: t
    property color bg: "#000000"
    property color card: "#161616"
    property color circle: "#282828"
    property color border: "#262626"
    property color text: "#ffffff"
    property color muted: "#9a9a9a"
    property color accent: "#a97be0"
    Behavior on bg { ColorAnimation { duration: 600 } }
    Behavior on card { ColorAnimation { duration: 600 } }
    Behavior on circle { ColorAnimation { duration: 600 } }
    Behavior on border { ColorAnimation { duration: 600 } }
    Behavior on accent { ColorAnimation { duration: 600 } }
    // accent washed into the card colour: the lit disc behind an active icon
    readonly property color accentSoft: Qt.rgba(accent.r * 0.24 + card.r * 0.76, accent.g * 0.24 + card.g * 0.76, accent.b * 0.24 + card.b * 0.76, 1)
    // light themes: a dark text on a light accent, white on a dark one; dark themes keep the old dark-on-accent look
    readonly property bool light: 0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b > 0.5
    readonly property color onAccent: !light ? bg : (0.299 * accent.r + 0.587 * accent.g + 0.114 * accent.b < 0.5 ? "#ffffff" : "#101828")
    readonly property color warm: "#f0a43a"
    readonly property color hot: "#ef5b5b"
    readonly property int radius: 14

    // palettes: stock and Thor Blue follow the colours measured from the stock dual-screen app's screenshot; the console themes
    // are inspired by the machines' own colours; Nintendo DS, 3DS and iiSU are light, and a system logo (white) then gets a dark plate
    readonly property var themes: ({
        stock:    { name: "Stock Console", group: "general",  bg: "#000000", card: "#161616", circle: "#282828", border: "#262626", text: "#ffffff", muted: "#9a9a9a", accent: "#a97be0" },
        steamos:  { name: "SteamOS", group: "os",        bg: "#0b0f14", card: "#1b2838", circle: "#2a475e", border: "#34536b", text: "#dfe3e8", muted: "#8f98a0", accent: "#1a9fff" },
        snes:     { name: "SNES", group: "consoles",           bg: "#121115", card: "#1f1d26", circle: "#302d3c", border: "#3a3648", text: "#e9e7ee", muted: "#97939f", accent: "#7a69e0" },
        gameboy:  { name: "Game Boy", group: "consoles",       bg: "#0a220a", card: "#0f380f", circle: "#1e4d1e", border: "#306230", text: "#9bbc0f", muted: "#6a8f1f", accent: "#c4de3a" },
        ps2:      { name: "PS2", group: "consoles",            bg: "#04060c", card: "#0a1122", circle: "#16223d", border: "#1f3159", text: "#e6ecff", muted: "#7f90ba", accent: "#3d6bff" },
        famicom:  { name: "Famicom", group: "consoles",        bg: "#150e0c", card: "#2a1c18", circle: "#3b2a24", border: "#4a352d", text: "#f3ead8", muted: "#ab9885", accent: "#d6322c" },
        thorblue: { name: "Thor Blue", group: "general",      bg: "#0f1318", card: "#181e25", circle: "#232b35", border: "#26303b", text: "#e3eaf1", muted: "#8a97a6", accent: "#68e1fb" },
        obsidian: { name: "Obsidian Gold", group: "general",  bg: "#080705", card: "#16130e", circle: "#26211a", border: "#2a241b", text: "#f0ead9", muted: "#968d78", accent: "#d4af37" },
        emerald:  { name: "Emerald Matrix", group: "general", bg: "#040a07", card: "#0c1812", circle: "#16281f", border: "#1a3326", text: "#dcf7e8", muted: "#74a08a", accent: "#2ee59d" },
        follow:   { name: "Follow game", group: "general",   bg: "#000000", card: "#161616", circle: "#282828", border: "#262626", text: "#ffffff", muted: "#9a9a9a", accent: "#a97be0" },
        ds:       { name: "Nintendo DS", group: "consoles",    bg: "#e6e9f0", card: "#ffffff", circle: "#d9deea", border: "#c6cddd", text: "#1b2233", muted: "#667089", accent: "#2f6fe4" },
        n3ds:     { name: "Nintendo 3DS", group: "consoles",   bg: "#efeff2", card: "#ffffff", circle: "#e0e0e6", border: "#cdcdd6", text: "#222228", muted: "#707078", accent: "#d81e2c" },
        iisu:     { name: "iiSU", group: "os",           bg: "#e4e9fb", card: "#ffffff", circle: "#d6ddf6", border: "#c3ccf0", text: "#232849", muted: "#6a729f", accent: "#3a86ff" },
        iisunight:{ name: "iiSU Night", group: "os",     bg: "#120e26", card: "#211a42", circle: "#31285c", border: "#413776", text: "#eeeaff", muted: "#9b93c9", accent: "#4fd2ff" },
        neon:     { name: "Neon Cyber", group: "general", group: "general",     bg: "#09050f", card: "#150d26", circle: "#241740", border: "#2b1c4d", text: "#f1e8ff", muted: "#9d89c8", accent: "#ff3df2" },
        ootime:   { name: "Ocarina of Time",        group: "games", bg: "#0a130c", card: "#15251a", circle: "#213a28", border: "#2b4a33", text: "#f1edd3", muted: "#9aa88b", accent: "#dcb44a" },
        botw:     { name: "Breath of the Wild",      group: "games", bg: "#e9ece6", card: "#f8f9f5", circle: "#d8ded6", border: "#c4ccc2", text: "#233038", muted: "#66767c", accent: "#1f8fb3" },
        totk:     { name: "Tears of the Kingdom",    group: "games", bg: "#0b1210", card: "#16221f", circle: "#233530", border: "#2e4640", text: "#e8f2ec", muted: "#8ea69b", accent: "#3fe0b4" },
        gow:      { name: "God of War",              group: "games", bg: "#0e0a0a", card: "#1c1413", circle: "#2c2120", border: "#3b2c29", text: "#eee5dc", muted: "#a2948a", accent: "#cf3b2e" },
        ff7:      { name: "Final Fantasy VII",       group: "games", bg: "#050817", card: "#0e1431", circle: "#18214b", border: "#243167", text: "#e3f5f2", muted: "#8196bf", accent: "#4df0b8" }
    })

    // the picker lists the themes under these headings, in this order (Preferences.qml); a theme without a group goes under the first
    readonly property var themeGroups: [
        { id: "general", name: "General" }, { id: "consoles", name: "Consoles" },
        { id: "os", name: "Operating systems and launchers" }, { id: "games", name: "Games" }
    ]
    // "Follow game": the whole palette is built from one colour taken from what the top screen shows
    function tinted(a, f) {
        return Qt.rgba(0.03 + (a.r - 0.03) * f, 0.03 + (a.g - 0.03) * f, 0.03 + (a.b - 0.03) * f, 1)
    }
    function apply(name, accentRgb) {
        if (name === "follow" && accentRgb) {
            const a = Qt.color("#" + accentRgb)
            bg = tinted(a, 0.07); card = tinted(a, 0.14); circle = tinted(a, 0.24); border = tinted(a, 0.32)
            text = "#ffffff"; muted = Qt.rgba(0.62 + a.r * 0.1, 0.62 + a.g * 0.1, 0.62 + a.b * 0.1, 1); accent = a
            return
        }
        const th = themes[name] || themes.stock
        bg = th.bg; card = th.card; circle = th.circle; border = th.border
        text = th.text; muted = th.muted
        accent = accentRgb ? "#" + accentRgb : th.accent
    }

    // accent -> amber -> red as a value climbs from `lo` to `hi`
    function heat(value, lo, hi) {
        const x = Math.max(0, Math.min(1, (value - lo) / (hi - lo)))
        return x < 0.5 ? Qt.tint(accent, Qt.rgba(warm.r, warm.g, warm.b, x * 2))
                       : Qt.tint(warm, Qt.rgba(hot.r, hot.g, hot.b, (x - 0.5) * 2))
    }
}
