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
    // accent washed into the card colour: the lit disc behind an active icon
    readonly property color accentSoft: Qt.rgba(accent.r * 0.24 + card.r * 0.76, accent.g * 0.24 + card.g * 0.76, accent.b * 0.24 + card.b * 0.76, 1)
    readonly property color warm: "#f0a43a"
    readonly property color hot: "#ef5b5b"
    readonly property int radius: 14

    // palettes: stock and cyan follow the colours measured from the stock dual-screen app's screenshot
    readonly property var themes: ({
        stock:    { name: "Stock Console",  bg: "#000000", card: "#161616", circle: "#282828", border: "#262626", text: "#ffffff", muted: "#9a9a9a", accent: "#a97be0" },
        thorblue: { name: "Thor Blue",      bg: "#0f1318", card: "#181e25", circle: "#232b35", border: "#26303b", text: "#e3eaf1", muted: "#8a97a6", accent: "#68e1fb" },
        obsidian: { name: "Obsidian Gold",  bg: "#080705", card: "#16130e", circle: "#26211a", border: "#2a241b", text: "#f0ead9", muted: "#968d78", accent: "#d4af37" },
        emerald:  { name: "Emerald Matrix", bg: "#040a07", card: "#0c1812", circle: "#16281f", border: "#1a3326", text: "#dcf7e8", muted: "#74a08a", accent: "#2ee59d" },
        neon:     { name: "Neon Cyber",     bg: "#09050f", card: "#150d26", circle: "#241740", border: "#2b1c4d", text: "#f1e8ff", muted: "#9d89c8", accent: "#ff3df2" }
    })

    function apply(name, accentRgb) {
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
