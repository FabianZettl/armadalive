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
    // Style: what a theme changes besides its colours. shape: how round the buttons, cards and discs are; pattern: a faint backdrop (Backdrop.qml);
    // motion: how animations feel; font: a family for all text ("" = the system's); border: the outline width. Set by apply() from `styles`.
    property string shape: "round"
    property string pattern: "none"
    property string fontKey: ""
    property int borderW: 1
    property int radius: 14
    property real speed: 1
    property int ease: Easing.OutCubic
    property int popEase: Easing.OutBack
    property real overshoot: 1.0
    property string iconKey: "normal"
    property real iconW: 1.8
    property string iconCap: "round"
    property string iconJoin: "round"
    property real iconFill: 0
    // fonts: the system's (Hack, Nimbus Roman) and the ones in armadalive/fonts (SIL Open Font License, see CREDITS.md)
    readonly property string fontFamily: ({ mono: "Hack", serif: "Nimbus Roman", pixel: "Silkscreen", term: "VT323", tech: "Rajdhani", round: "Fredoka", fantasy: "Cinzel", hand: "Patrick Hand" })[fontKey] || ""
    readonly property var iconStyles: ({
        thin:   { w: 1.3, cap: "round",  join: "round", fill: 0 },
        normal: { w: 1.8, cap: "round",  join: "round", fill: 0 },
        bold:   { w: 2.6, cap: "round",  join: "round", fill: 0 },
        block:  { w: 2.4, cap: "square", join: "miter", fill: 0 },
        line:   { w: 1.5, cap: "butt",   join: "miter", fill: 0 },
        duo:    { w: 1.8, cap: "round",  join: "round", fill: 0.22 }
    })
    function dur(ms) { return Math.max(1, Math.round(ms * speed)) }
    // a pill-shaped control (a button, a chip) and a round one (an icon disc), in the theme's shape
    function pill(h) { return shape === "round" || shape === "pill" ? h / 2 : shape === "soft" ? h * 0.3 : shape === "cut" ? 5 : 3 }
    function disc(w) { return shape === "round" || shape === "pill" ? w / 2 : shape === "soft" ? w * 0.3 : shape === "cut" ? 6 : 3 }
    // the corner of an app tile, as a share of its side
    readonly property real tileCorner: shape === "pill" ? 0.18 : shape === "soft" ? 0.12 : shape === "cut" ? 0.04 : shape === "square" ? 0.02 : 0.1
    function radiusFor(shp) { return shp === "pill" ? 18 : shp === "soft" ? 10 : shp === "cut" ? 5 : shp === "square" ? 3 : 14 }
    readonly property var motions: ({
        smooth: { speed: 1.0, ease: Easing.OutCubic,  pop: Easing.OutBack,  over: 1.0 },
        snappy: { speed: 0.6, ease: Easing.OutQuad,   pop: Easing.OutCubic, over: 0.0 },
        bouncy: { speed: 1.1, ease: Easing.OutBack,   pop: Easing.OutBack,  over: 2.6 },
        gentle: { speed: 1.7, ease: Easing.InOutSine, pop: Easing.OutCubic, over: 0.0 },
        steps:  { speed: 0.5, ease: Easing.Linear,    pop: Easing.Linear,   over: 0.0 }
    })
    readonly property var styles: ({
        stock:        { icons: "normal" },
        thorblue:     { icons: "normal" },
        obsidian:     { shape: "soft", motion: "gentle", font: "serif", icons: "thin" },
        emerald:      { shape: "square", pattern: "scan", motion: "steps", font: "term", icons: "line" },
        neon:         { shape: "cut", pattern: "grid", motion: "snappy", font: "tech", icons: "thin" },
        follow:       { icons: "normal" },
        dracula:      { shape: "soft", icons: "duo" },
        nord:         { shape: "soft", motion: "gentle", icons: "thin" },
        gruvbox:      { shape: "soft", font: "mono", icons: "bold" },
        solarized:    { shape: "soft", font: "mono", icons: "thin" },
        amber:        { shape: "square", pattern: "scan", motion: "steps", font: "term", icons: "line" },
        snes:         { shape: "pill", motion: "bouncy", font: "round", icons: "bold" },
        gameboy:      { shape: "square", pattern: "grid", motion: "steps", font: "pixel", icons: "block", border: 2 },
        ps2:          { pattern: "grid", motion: "gentle", font: "tech", icons: "thin" },
        famicom:      { shape: "square", motion: "snappy", font: "pixel", icons: "block", border: 2 },
        ds:           { shape: "pill", pattern: "dots", motion: "bouncy", font: "round", icons: "bold" },
        n3ds:         { shape: "soft", pattern: "checker", motion: "bouncy", font: "round", icons: "duo" },
        dreamcast:    { shape: "pill", pattern: "dots", font: "round", icons: "bold" },
        saturn:       { shape: "cut", pattern: "grid", font: "tech", icons: "line" },
        megadrive:    { shape: "square", pattern: "scan", motion: "snappy", font: "tech", icons: "block" },
        n64:          { shape: "soft", motion: "bouncy", font: "round", icons: "bold", border: 2 },
        gamecube:     { shape: "soft", pattern: "dots", motion: "gentle", font: "round", icons: "duo" },
        wii:          { shape: "pill", pattern: "grid", font: "round", icons: "thin" },
        switch:       { shape: "soft", motion: "snappy", icons: "bold", border: 2 },
        xbox:         { shape: "soft", pattern: "diag", motion: "gentle", icons: "duo" },
        vita:         { shape: "pill", pattern: "dots", icons: "thin" },
        atari:        { shape: "square", pattern: "diag", motion: "steps", font: "term", icons: "block", border: 2 },
        iisu:         { shape: "pill", pattern: "dots", motion: "bouncy", font: "round", icons: "duo" },
        iisunight:    { shape: "pill", pattern: "stars", motion: "bouncy", font: "round", icons: "duo" },
        steamos:      { shape: "soft", motion: "snappy", icons: "normal" },
        winxp:        { shape: "soft", motion: "smooth", icons: "bold", border: 2 },
        win11:        { shape: "soft", motion: "snappy", icons: "thin" },
        macos:        { shape: "pill", icons: "normal" },
        android:      { shape: "pill", pattern: "dots", font: "round", icons: "duo" },
        ubuntu:       { shape: "soft", icons: "bold" },
        plasma:       { shape: "soft", motion: "snappy", icons: "normal" },
        ootime:       { shape: "soft", pattern: "diag", motion: "gentle", font: "fantasy", icons: "thin" },
        botw:         { shape: "soft", pattern: "grid", motion: "gentle", font: "serif", icons: "thin" },
        totk:         { shape: "soft", pattern: "grid", motion: "gentle", icons: "line" },
        gow:          { shape: "cut", motion: "gentle", font: "fantasy", icons: "bold" },
        ff7:          { shape: "cut", pattern: "scan", motion: "snappy", font: "tech", icons: "line" },
        mario:        { shape: "pill", pattern: "checker", motion: "bouncy", font: "round", icons: "bold", border: 3 },
        pokemon:      { shape: "pill", pattern: "dots", motion: "bouncy", font: "round", icons: "bold" },
        sonic:        { shape: "pill", pattern: "diag", motion: "snappy", font: "tech", icons: "bold" },
        metroid:      { shape: "cut", pattern: "grid", motion: "snappy", font: "tech", icons: "line" },
        cyberpunk:    { shape: "cut", pattern: "scan", motion: "snappy", font: "tech", icons: "line" },
        hollowknight: { shape: "soft", pattern: "stars", motion: "gentle", font: "serif", icons: "thin" },
        celeste:      { shape: "square", pattern: "stars", motion: "steps", font: "pixel", icons: "block" },
        halo:         { shape: "cut", pattern: "grid", motion: "snappy", font: "tech", icons: "line" },
        minecraft:    { shape: "square", pattern: "checker", motion: "steps", font: "pixel", icons: "block", border: 3 },
        acnh:         { shape: "pill", pattern: "dots", motion: "bouncy", font: "round", icons: "duo" },
        splatoon:     { shape: "soft", pattern: "diag", motion: "bouncy", font: "round", icons: "bold", border: 3 },
        kirby:        { shape: "pill", pattern: "dots", motion: "bouncy", font: "round", icons: "bold" },
        skyrim:       { shape: "soft", motion: "gentle", font: "fantasy", icons: "thin" },
        stardew:      { shape: "square", pattern: "checker", motion: "steps", font: "hand", icons: "bold", border: 2 }
    })

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
        ff7:      { name: "Final Fantasy VII",       group: "games", bg: "#050817", card: "#0e1431", circle: "#18214b", border: "#243167", text: "#e3f5f2", muted: "#8196bf", accent: "#4df0b8" },
        dracula:    { name: "Dracula", group: "general", bg: "#1e1f29", card: "#282a36", circle: "#383a4a", border: "#44475a", text: "#f8f8f2", muted: "#a3a8c3", accent: "#bd93f9" },
        nord:       { name: "Nord", group: "general", bg: "#242933", card: "#2e3440", circle: "#3b4252", border: "#4c566a", text: "#eceff4", muted: "#a3adc2", accent: "#88c0d0" },
        gruvbox:    { name: "Gruvbox", group: "general", bg: "#1d2021", card: "#282828", circle: "#3c3836", border: "#504945", text: "#ebdbb2", muted: "#a89984", accent: "#fabd2f" },
        solarized:  { name: "Solarized Dark", group: "general", bg: "#00212b", card: "#073642", circle: "#0d4655", border: "#1a5766", text: "#eee8d5", muted: "#93a1a1", accent: "#2aa198" },
        amber:      { name: "Amber Terminal", group: "general", bg: "#0a0600", card: "#161007", circle: "#241a0a", border: "#33250d", text: "#ffcf66", muted: "#b08a3c", accent: "#ffb000" },
        dreamcast:  { name: "Dreamcast", group: "consoles", bg: "#f3f1ee", card: "#ffffff", circle: "#e4e0da", border: "#d1ccc4", text: "#2b2622", muted: "#6f6760", accent: "#d9560f" },
        saturn:     { name: "Sega Saturn", group: "consoles", bg: "#12151c", card: "#1c212b", circle: "#2a313f", border: "#38414f", text: "#e8ecf3", muted: "#8e99ab", accent: "#4fa3d9" },
        megadrive:  { name: "Mega Drive", group: "consoles", bg: "#060608", card: "#121218", circle: "#1f1f29", border: "#2d2d3a", text: "#f1f1f5", muted: "#8c8c9c", accent: "#e63946" },
        n64:        { name: "Nintendo 64", group: "consoles", bg: "#16171a", card: "#212327", circle: "#30333a", border: "#40444d", text: "#f2f2f4", muted: "#9a9ea8", accent: "#f2b01e" },
        gamecube:   { name: "GameCube", group: "consoles", bg: "#0d0a1f", card: "#181331", circle: "#262049", border: "#342c60", text: "#ece9ff", muted: "#9a92c9", accent: "#7b5cff" },
        wii:        { name: "Wii", group: "consoles", bg: "#eef2f6", card: "#ffffff", circle: "#dfe6ed", border: "#c9d3dc", text: "#26323c", muted: "#69798a", accent: "#0e8fc4" },
        switch:     { name: "Nintendo Switch", group: "consoles", bg: "#16171b", card: "#222329", circle: "#33353d", border: "#43464f", text: "#f4f4f6", muted: "#9b9da8", accent: "#e60012" },
        xbox:       { name: "Xbox", group: "consoles", bg: "#080d08", card: "#121b12", circle: "#1e2d1e", border: "#2a402a", text: "#e9f5e9", muted: "#86a286", accent: "#3dbd3d" },
        vita:       { name: "PlayStation Vita", group: "consoles", bg: "#07090f", card: "#10151f", circle: "#1b2433", border: "#273348", text: "#e7eefb", muted: "#8296b8", accent: "#2f8cff" },
        atari:      { name: "Atari 2600", group: "consoles", bg: "#1a120b", card: "#2a1d12", circle: "#3b2a19", border: "#4d3720", text: "#f3e3cc", muted: "#b39b7c", accent: "#e2832b" },
        winxp:      { name: "Windows XP", group: "os", bg: "#ece9d8", card: "#ffffff", circle: "#dcd8c5", border: "#c5c0a8", text: "#1c2433", muted: "#5c6676", accent: "#2457d6" },
        win11:      { name: "Windows 11", group: "os", bg: "#1b1b1b", card: "#262626", circle: "#343434", border: "#454545", text: "#f3f3f3", muted: "#a0a0a0", accent: "#4cc2ff" },
        macos:      { name: "macOS", group: "os", bg: "#ececf0", card: "#ffffff", circle: "#dcdce2", border: "#c8c8d0", text: "#1d1d1f", muted: "#6e6e73", accent: "#0a6cdb" },
        android:    { name: "Android", group: "os", bg: "#0c1410", card: "#162119", circle: "#223226", border: "#2e4333", text: "#e5f2e8", muted: "#8aa591", accent: "#3ddc84" },
        ubuntu:     { name: "Ubuntu", group: "os", bg: "#2a0a1f", card: "#3a1230", circle: "#4d1b40", border: "#612750", text: "#f6ecf2", muted: "#b793aa", accent: "#e95420" },
        plasma:     { name: "KDE Plasma", group: "os", bg: "#1b1e20", card: "#232629", circle: "#31363b", border: "#3d444a", text: "#fcfcfc", muted: "#a1a9b1", accent: "#3daee9" },
        mario:      { name: "Super Mario", group: "games", bg: "#0b1330", card: "#14214a", circle: "#1f3270", border: "#2b4296", text: "#f6f2e8", muted: "#97a6d6", accent: "#ee2b25" },
        pokemon:    { name: "Pokémon", group: "games", bg: "#f2f2f2", card: "#ffffff", circle: "#e2e2e2", border: "#cfcfcf", text: "#212121", muted: "#707070", accent: "#d91414" },
        sonic:      { name: "Sonic the Hedgehog", group: "games", bg: "#060d33", card: "#0c1850", circle: "#142470", border: "#1e3394", text: "#eef2ff", muted: "#8f9dd8", accent: "#ffd21f" },
        metroid:    { name: "Metroid", group: "games", bg: "#120a05", card: "#201208", circle: "#331d0c", border: "#4a2a12", text: "#f6e9d8", muted: "#b3987a", accent: "#f28c1c" },
        cyberpunk:  { name: "Cyberpunk 2077", group: "games", bg: "#050505", card: "#111111", circle: "#1d1d1d", border: "#2c2c2c", text: "#f4f4f4", muted: "#9a9a9a", accent: "#fcee0a" },
        hollowknight:{ name: "Hollow Knight", group: "games", bg: "#06080c", card: "#10151c", circle: "#1b232d", border: "#273241", text: "#e4eef5", muted: "#8499aa", accent: "#b9d8ea" },
        celeste:    { name: "Celeste", group: "games", bg: "#190f2e", card: "#251845", circle: "#34245f", border: "#44307a", text: "#f6edff", muted: "#a994cf", accent: "#ff7ab9" },
        halo:       { name: "Halo", group: "games", bg: "#0a0f0b", card: "#141c15", circle: "#202c22", border: "#2d3d30", text: "#e6efe3", muted: "#8da08c", accent: "#9ac43c" },
        minecraft:  { name: "Minecraft", group: "games", bg: "#17110b", card: "#261c12", circle: "#38291a", border: "#4b3822", text: "#f0e6d6", muted: "#a8957c", accent: "#5fb73c" },
        acnh:       { name: "Animal Crossing", group: "games", bg: "#f3efdb", card: "#fffdf2", circle: "#e6e1c7", border: "#d3ccac", text: "#33422f", muted: "#76805f", accent: "#2d9a73" },
        splatoon:   { name: "Splatoon", group: "games", bg: "#0b0b14", card: "#171726", circle: "#242439", border: "#33334f", text: "#f3f3fb", muted: "#9c9cc0", accent: "#c6f000" },
        kirby:      { name: "Kirby", group: "games", bg: "#fdeef4", card: "#ffffff", circle: "#f6dbe6", border: "#ebc3d4", text: "#43212f", muted: "#8f6475", accent: "#d6457f" },
        skyrim:     { name: "Skyrim", group: "games", bg: "#0e1114", card: "#181d22", circle: "#252c33", border: "#333c45", text: "#e8edf1", muted: "#8d99a4", accent: "#c3d0da" },
        stardew:    { name: "Stardew Valley", group: "games", bg: "#f2ead2", card: "#fff9e8", circle: "#e4d9b7", border: "#cfc29a", text: "#3b3322", muted: "#7f7556", accent: "#4e8826" }
    })

    // the picker lists the themes under these headings, in this order (Preferences.qml); a theme without a group goes under the first
    readonly property var themeGroups: [
        { id: "general", name: "General" }, { id: "consoles", name: "Consoles" },
        { id: "os", name: "Operating systems and launchers", short: "Systems" }, { id: "games", name: "Games" }
    ]
    // "Follow game": the whole palette is built from one colour taken from what the top screen shows
    function tinted(a, f) {
        return Qt.rgba(0.03 + (a.r - 0.03) * f, 0.03 + (a.g - 0.03) * f, 0.03 + (a.b - 0.03) * f, 1)
    }
    function setStyle(name) {
        const st = styles[name] || ({}), m = motions[st.motion || "smooth"]
        shape = st.shape || "round"; pattern = st.pattern || "none"; fontKey = st.font || ""; borderW = st.border || 1
        radius = radiusFor(shape)
        iconKey = st.icons || "normal"
        const ic = iconStyles[iconKey]
        iconW = ic.w; iconCap = ic.cap; iconJoin = ic.join; iconFill = ic.fill
        speed = m.speed; ease = m.ease; popEase = m.pop; overshoot = m.over
    }
    function apply(name, accentRgb) {
        setStyle(name)
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
