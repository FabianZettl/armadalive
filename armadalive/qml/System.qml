import QtQuick

// The dashboard: frame-rate mode and FPS, quick settings in pages of eight, temperature, fan and four telemetry rings.
Item {
    id: page
    readonly property var st: system.stats
    readonly property var gs: gamescope.state
    readonly property var cc: controls.state
    readonly property var cfg: settings.data
    readonly property var rgb: cfg.rgb || ({})
    readonly property var rl: rules.state
    readonly property real u: Math.min(width / 620, height / 488)
    readonly property real m: 10 * u
    readonly property var prof: (cfg.profiles || []).find(p => p.id === (st.profile || "").toLowerCase())
    readonly property var curves: cfg.curves || []
    readonly property var curve: prof ? curves.find(c => c.id === prof.fanCurve) : undefined
    property int qsPage: 0

    readonly property var rawTiles: [
        { id: "perf", icon: "perf", label: st.profile, on: st.profile === "Performance",
          act: () => { const p = st.profiles; system.setProfile(p[(p.indexOf(st.profile) + 1) % p.length]) } },
        { id: "fan", icon: "fan", label: curve ? curve.label : "–", on: curve !== undefined && curve.id === "aggressive",
          act: () => { if (cfg.helper && prof && curves.length) settings.setProfileOption(prof.id, "fan_curve", curves[(curves.indexOf(curve) + 1) % curves.length].id) } },
        { id: "clean", icon: "clean", label: Tr.t("Clear RAM"), on: false, act: () => { if (cfg.helper) settings.dropCaches() } },
        { id: "led", icon: "led", label: Tr.t("Stick LEDs"), on: rgb.enabled === true,
          act: () => { if (cfg.helper) settings.setRgb(!rgb.enabled, rgb.color || "FFFFFF", rgb.brightness === undefined ? 25 : rgb.brightness) } },
        { id: "wifi", icon: "wifi", label: Tr.t("Wi-Fi"), on: cc.wifi === true, act: () => controls.toggleWifi() },
        { id: "wifips", icon: "wifi", label: Tr.t("Wi-Fi saver"), on: cc.wifips === true, act: () => controls.toggleWifiSaver() },
        { id: "bluetooth", icon: "bluetooth", label: "Bluetooth", on: cc.bluetooth === true, act: () => controls.toggleBluetooth() },
        { id: "plane", icon: "plane", label: Tr.t("Airplane"), on: cc.airplane === true, act: () => controls.toggleAirplane() },
        { id: "sound", icon: cc.muted ? "mute" : "sound", label: cc.muted ? Tr.t("Muted") : Tr.t("Sound"), on: cc.muted !== true, act: () => controls.toggleMute() },
        { id: "shot", icon: "shot", label: "Screenshot", on: false, act: () => controls.screenshot() },
        { id: "tuning", icon: "edit", label: Tr.t("Tuning"), on: false, act: () => { Nav.go = "tuning" } },
        { id: "graphs", icon: "graph", label: Tr.t("Graphs"), on: false, act: () => { Nav.go = "graphs" } },
        { id: "screenoff", icon: "power", label: Tr.t("Screen off"), on: false, act: () => { Nav.go = "blank" } },
        { id: "gamerule", icon: "star", label: Tr.t("Game rule"), on: rl.gameKey !== "" && rl.rules.some(r => r.key === rl.gameKey), act: () => rules.toggle("game") },
        { id: "systemrule", icon: "star", label: Tr.t("System rule"), on: rl.systemKey !== "" && rl.rules.some(r => r.key === rl.systemKey), act: () => rules.toggle("system") },
        { id: "res", icon: "gauge", label: rl.resOk ? ((rl.rules.find(r => r.key === rl.gameKey) || {}).res ? (rl.rules.find(r => r.key === rl.gameKey)).res + "× " + Tr.t("render") : Tr.t("Resolution")) : Tr.t("Resolution"),
          on: rl.resOk && (rl.rules.find(r => r.key === rl.gameKey) || {}).res > 0, act: () => rules.cycleRes() },
        { id: "gpu", icon: "gauge", label: st.gpuLevel === "auto" ? Tr.t("Auto") : st.gpuManual + " MHz", on: st.gpuLevel !== "auto",
          act: () => st.gpuLevel === "auto" ? system.setGpuManual(st.gpuManual) : system.setGpuAuto() }
    ]
    // the tiles in the order the user chose (Tiles keeps it); a long press on a tile starts moving, a tap on a second one swaps
    readonly property var tiles: { tileStore.order; return tileStore.arrange(rawTiles.map(t => t.id)).map(id => rawTiles.find(t => t.id === id)) }
    readonly property int pageCount: Math.ceil(tiles.length / 8)
    property bool editing: false
    property string picked: ""
    function tap(id) {
        if (picked === "" || picked === id) { picked = picked === id ? "" : id; return }
        tileStore.swap(picked, id, tiles.map(t => t.id))
        picked = ""
    }

    // --- row 1: FPS card and quick settings
    Rectangle {
        id: fps
        x: page.m; y: page.m
        width: (page.width - 3 * page.m) * 0.31
        height: (page.height - 3 * page.m) * 0.64
        radius: Theme.radius * page.u
        color: Theme.card

        Rectangle {
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 14 * page.u }
            width: modeText.width + 30 * page.u
            height: 30 * page.u
            radius: height / 2
            color: Theme.accentSoft
            border.color: Theme.accent
            Text {
                id: modeText
                anchors.centerIn: parent
                color: Theme.accent
                font.pixelSize: 13 * page.u
                font.letterSpacing: 0.6
                text: (page.gs.limit > 0 ? page.gs.limit : "–") + " FPS MODE"
            }
            MouseArea { anchors.fill: parent; onClicked: gamescope.setFpsLimit(page.gs.limit === 120 ? 60 : 120) }
        }
        Row {
            anchors.centerIn: parent
            spacing: 6 * page.u
            Text { color: page.gs.fps > 0 ? Theme.text : Theme.muted; font.pixelSize: 62 * page.u; font.weight: Font.Medium; text: page.gs.fps }
            Text { anchors.baseline: parent.children[0].baseline; color: Theme.text; font.pixelSize: 18 * page.u; text: "FPS" }
        }
        Text {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 16 * page.u }
            color: Theme.muted
            font.pixelSize: 13 * page.u
            text: Tr.t("CURRENT FPS")
        }
    }
    Rectangle {
        id: qs
        x: fps.x + fps.width + page.m; y: page.m
        width: page.width - x - page.m
        height: fps.height
        radius: Theme.radius * page.u
        color: Theme.card

        // swiping inside this card turns its pages and must not leave the dashboard: the lock is taken on touch-down
        PointHandler {
            target: null
            onActiveChanged: Gesture.hold(active)
        }
        DragHandler {
            target: null
            yAxis.enabled: false
            onActiveChanged: {
                if (active) return
                const dx = centroid.position.x - centroid.pressPosition.x
                if (dx < -40 && page.qsPage < page.pageCount - 1) page.qsPage++
                else if (dx > 40 && page.qsPage > 0) page.qsPage--
            }
        }
        Grid {
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 10 * page.u }
            columns: 4
            columnSpacing: 0
            rowSpacing: 4 * page.u
            Repeater {
                model: 8
                delegate: CircleButton {
                    readonly property var tile: page.tiles[page.qsPage * 8 + index]
                    width: (qs.width - 12 * page.u) / 4
                    height: (qs.height - 36 * page.u) / 2
                    size: Math.min(width * 0.62, height * 0.52)
                    visible: tile !== undefined
                    icon: tile ? tile.icon : ""
                    label: tile ? tile.label : ""
                    on: tile ? tile.on : false
                    marked: page.editing && page.picked === tile.id
                    onClicked: page.editing ? page.tap(tile.id) : tile.act()
                    onHeld: { page.editing = true; page.picked = tile.id }
                }
            }
        }
        Text {
            visible: page.editing
            anchors { left: parent.left; leftMargin: 14 * page.u; bottom: parent.bottom; bottomMargin: 10 * page.u }
            color: Theme.muted
            font.pixelSize: 12 * page.u
            text: Tr.t("Tap two tiles to swap")
        }
        Row {
            visible: page.editing
            anchors { right: parent.right; rightMargin: 12 * page.u; bottom: parent.bottom; bottomMargin: 6 * page.u }
            spacing: 6 * page.u
            PillButton { height: 28 * page.u; label: Tr.t("Reset"); onClicked: { tileStore.reset(); page.picked = "" } }
            PillButton { height: 28 * page.u; label: Tr.t("Done"); primary: true; onClicked: { page.editing = false; page.picked = "" } }
        }
        Row {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 * page.u }
            spacing: 8 * page.u
            visible: page.pageCount > 1
            Repeater {
                model: page.pageCount
                delegate: Rectangle {
                    width: 9 * page.u; height: width; radius: width / 2
                    color: index === page.qsPage ? Theme.text : Theme.circle
                    MouseArea { anchors.fill: parent; anchors.margins: -8; onClicked: page.qsPage = index }
                }
            }
        }
    }

    // --- row 2: temperature, fan, rings
    readonly property real row2y: fps.y + fps.height + m
    readonly property real row2h: height - row2y - m
    readonly property real row2w: width - 4 * m
    Rectangle {
        id: temp
        x: page.m; y: page.row2y
        width: page.row2w * 0.19; height: page.row2h
        radius: Theme.radius * page.u; color: Theme.card
        Row { x: 12 * page.u; y: 12 * page.u; spacing: 6 * page.u
            Icon { width: 18 * page.u; height: width; name: "temp"; color: Theme.muted }
            Text { color: Theme.muted; font.pixelSize: 12 * page.u; text: "TEMP" } }
        Text { x: 12 * page.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * page.u
            color: Theme.heat(page.st.temp, 45, 90); font.pixelSize: 30 * page.u; font.weight: Font.Medium; text: page.st.temp + "°C" }
    }
    Rectangle {
        id: fan
        x: temp.x + temp.width + page.m; y: page.row2y
        width: page.row2w * 0.19; height: page.row2h
        radius: Theme.radius * page.u; color: Theme.card
        Row { x: 12 * page.u; y: 12 * page.u; spacing: 6 * page.u
            Icon { width: 18 * page.u; height: width; name: "fan"; color: Theme.muted }
            Text { color: Theme.muted; font.pixelSize: 12 * page.u; text: Tr.t("FAN") } }
        Text { x: 12 * page.u; anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * page.u
            color: Theme.text; font.pixelSize: 30 * page.u; font.weight: Font.Medium; text: Math.round((page.st.fanPwm || 0) / 2.55) + "%" }
    }
    Rectangle {
        x: fan.x + fan.width + page.m; y: page.row2y
        width: page.width - x - page.m; height: page.row2h
        radius: Theme.radius * page.u; color: Theme.card
        Row {
            anchors.fill: parent
            anchors.margins: 6 * page.u
            property real cell: width / 4
            Ring { width: parent.cell; height: parent.height; value: page.st.cpuGhz / page.st.cpuMaxGhz; text: page.st.cpuGhz.toFixed(2); unit: "GHz"; label: "CPU"; tint: Theme.heat(page.st.cpu, 20, 95) }
            Ring { width: parent.cell; height: parent.height; value: page.st.gpuMhz / page.st.gpuMax; text: page.st.gpuMhz; unit: "MHz"; label: "GPU" }
            Ring { width: parent.cell; height: parent.height; value: page.st.watts / 20; text: Math.round(page.st.watts); unit: "W"; label: "PWR" }
            Ring { width: parent.cell; height: parent.height; value: page.st.ramUsed / page.st.ramTotal; text: page.st.ramUsed.toFixed(1); unit: "GB"; label: "RAM"; tint: Theme.heat(page.st.ramUsed / page.st.ramTotal * 100, 40, 95) }
        }
    }
}
