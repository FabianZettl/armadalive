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
    readonly property color warm: "#f0a43a"
    readonly property color hot: "#ef5b5b"
    readonly property int radius: 14

    // palettes: stock and Thor Blue follow the colours measured from the stock dual-screen app's screenshot; the console themes
    // are inspired by the machines' own colours and stay dark, because the system logos are white
    readonly property var themes: ({
        stock:    { name: "Stock Console",  bg: "#000000", card: "#161616", circle: "#282828", border: "#262626", text: "#ffffff", muted: "#9a9a9a", accent: "#a97be0" },
        steamos:  { name: "SteamOS",        bg: "#0b0f14", card: "#1b2838", circle: "#2a475e", border: "#34536b", text: "#dfe3e8", muted: "#8f98a0", accent: "#1a9fff" },
        snes:     { name: "SNES",           bg: "#121115", card: "#1f1d26", circle: "#302d3c", border: "#3a3648", text: "#e9e7ee", muted: "#97939f", accent: "#7a69e0" },
        gameboy:  { name: "Game Boy",       bg: "#0a220a", card: "#0f380f", circle: "#1e4d1e", border: "#306230", text: "#9bbc0f", muted: "#6a8f1f", accent: "#c4de3a" },
        ps2:      { name: "PS2",            bg: "#04060c", card: "#0a1122", circle: "#16223d", border: "#1f3159", text: "#e6ecff", muted: "#7f90ba", accent: "#3d6bff" },
        famicom:  { name: "Famicom",        bg: "#150e0c", card: "#2a1c18", circle: "#3b2a24", border: "#4a352d", text: "#f3ead8", muted: "#ab9885", accent: "#d6322c" },
        thorblue: { name: "Thor Blue",      bg: "#0f1318", card: "#181e25", circle: "#232b35", border: "#26303b", text: "#e3eaf1", muted: "#8a97a6", accent: "#68e1fb" },
        obsidian: { name: "Obsidian Gold",  bg: "#080705", card: "#16130e", circle: "#26211a", border: "#2a241b", text: "#f0ead9", muted: "#968d78", accent: "#d4af37" },
        emerald:  { name: "Emerald Matrix", bg: "#040a07", card: "#0c1812", circle: "#16281f", border: "#1a3326", text: "#dcf7e8", muted: "#74a08a", accent: "#2ee59d" },
        follow:   { name: "Follow game",   bg: "#000000", card: "#161616", circle: "#282828", border: "#262626", text: "#ffffff", muted: "#9a9a9a", accent: "#a97be0" },
        neon:     { name: "Neon Cyber",     bg: "#09050f", card: "#150d26", circle: "#241740", border: "#2b1c4d", text: "#f1e8ff", muted: "#9d89c8", accent: "#ff3df2" }
    })

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
