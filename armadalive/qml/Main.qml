import QtQuick
import QtQuick.Window

Window {
    id: win
    visible: true
    width: 620
    height: 540
    color: Theme.bg
    title: "ArmadaLive"

    readonly property var now: nowPlaying.state
    // Handbuch and Cheats are only listed while the current game has them; "under" pages are reached from another page
    readonly property var all: [
        { id: "now", label: Tr.t("Game"), icon: "play", file: "NowPlaying.qml", has: true },
        { id: "manual", label: Tr.t("Manual"), icon: "book", file: "Manual.qml", has: now.manual !== "" },
        { id: "cheats", label: Tr.t("Cheats"), icon: "cheats", file: "Cheats.qml", has: now.hasCheats },
        { id: "apps", label: Tr.t("Apps"), icon: "apps", file: "Apps.qml", has: true },
        { id: "mode", label: Tr.t("Mode"), icon: "mode", file: "Mode.qml", has: true },
        { id: "system", label: Tr.t("System"), icon: "gear", file: "System.qml", has: true },
        { id: "prefs", label: Tr.t("Settings"), icon: "info", file: "Preferences.qml", has: true },
        { id: "tuning", label: Tr.t("Tuning"), icon: "perf", file: "Tuning.qml", has: true, under: "system" }
    ]
    readonly property var pages: all.filter(p => p.has && !p.under)
    property string page: "now"
    readonly property var current: all.find(p => p.id === page && p.has) || all[0]
    readonly property string section: current.under || current.id
    readonly property bool home: current.id === "now"
    readonly property real u: Math.min(width / 620, height / 540)
    // status line and bar slide in on the game page only when the user swipes up
    property bool peek: false
    readonly property bool chrome: !home || peek

    // the screen dims a little after 10 s without a touch; the next touch wakes it (and does nothing else)
    property bool dimmed: false
    readonly property bool dimEnabled: ui.state.dim !== false     // Settings > Dim after 10 s
    function wake() { dimmed = false; idle.restart() }
    onDimEnabledChanged: { if (dimEnabled) idle.restart(); else { idle.stop(); dimmed = false } }
    Timer {
        id: idle
        interval: 10000
        onTriggered: { if (Auth.ask === "") win.dimmed = true; else idle.restart() }   // not while the password prompt is open
    }
    PointHandler { target: null; onActiveChanged: if (active) win.wake() }  // sees every touch, takes none
    // a new game, logo or background (scrolling in ES-DE or Steam, a game starting) brightens it too
    readonly property string shown: [now.kind, now.title, now.logo, now.fanart].join("|")
    onShownChanged: wake()

    // always full screen: Plasma's own panels only come back with its swipe-up gesture
    function applyVisibility() { visibility = Window.FullScreen }
    function go(id) { page = id; if (home) hideChrome.restart() }
    function step(delta) {
        const i = pages.findIndex(p => p.id === section), j = i + delta
        if (i >= 0 && j >= 0 && j < pages.length) go(pages[j].id)
    }
    onCurrentChanged: if (current.id !== page) page = current.id
    onHomeChanged: if (home) { peek = true; hideChrome.restart() }
    Component.onCompleted: { idle.start(); applyVisibility(); Theme.apply(ui.state.theme, ui.state.accent); Tr.lang = ui.state.lang }
    Connections {
        target: ui
        function onChanged() { Theme.apply(ui.state.theme, ui.state.accent); Tr.lang = ui.state.lang }
    }
    Connections {
        target: nowPlaying
        function onSelection() { win.go("now") }
    }
    Connections {
        target: Nav
        function onGoChanged() { if (Nav.go) { win.go(Nav.go); Nav.go = "" } }
    }
    // the AYN button (see scripts/ayn-button.sh) always brings the app up, whatever is in front on this screen
    Connections {
        target: ayn
        function onPressed() {
            win.wake()
            win.show()
            win.applyVisibility()
            win.raise()
            win.requestActivate()
            shell.activate()
            check.restart()
        }
    }
    Timer {
        id: check
        interval: 900
        onTriggered: console.info("AYN: window visible=" + win.visible + " active=" + win.active)
    }
    Timer { id: hideChrome; interval: 3000; onTriggered: win.peek = false }

    Item {
        id: body
        anchors { left: parent.left; right: parent.right; top: win.home ? parent.top : status.bottom; bottom: win.home ? parent.bottom : nav.top }
        clip: true
        Loader { anchors.fill: parent; source: win.current.file }
        // swipe sideways between pages; the PDF view keeps its own panning
        DragHandler {
            target: null
            yAxis.enabled: false
            enabled: win.current.id !== "manual" && !Gesture.locked
            onActiveChanged: {
                if (active || Gesture.locked) return
                const dx = centroid.position.x - centroid.pressPosition.x
                if (dx < -90) win.step(1)
                else if (dx > 90) win.step(-1)
            }
        }
        // swipe up shows status line and bar on the game page, swipe down puts them away again
        DragHandler {
            target: null
            xAxis.enabled: false
            enabled: win.home && !Gesture.locked
            onActiveChanged: {
                if (active || Gesture.locked) return
                const dy = centroid.position.y - centroid.pressPosition.y
                if (dy < -70) { win.peek = true; hideChrome.restart() }
                else if (dy > 70) win.peek = false
            }
        }
    }

    Rectangle {
        id: status
        x: 0
        width: parent.width
        height: 34 * win.u
        y: win.chrome ? 0 : -height - 4
        Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        color: win.home ? Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.7) : "transparent"
        Text {
            id: clock
            x: 16 * win.u
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.text
            font.pixelSize: 15 * win.u
            text: Qt.formatTime(new Date(), "hh:mm")
            Timer { interval: 10000; running: true; repeat: true; onTriggered: clock.text = Qt.formatTime(new Date(), "hh:mm") }
        }
        Row {
            anchors { right: parent.right; rightMargin: 16 * win.u; verticalCenter: parent.verticalCenter }
            spacing: 12 * win.u
            Icon { width: 18 * win.u; height: width; anchors.verticalCenter: parent.verticalCenter; name: "wifi"; color: controls.state.wifi ? Theme.text : Theme.circle }
            Icon { width: 18 * win.u; height: width; anchors.verticalCenter: parent.verticalCenter; name: "bluetooth"; color: controls.state.bluetooth ? Theme.text : Theme.circle }
            Row {
                spacing: 6 * win.u
                anchors.verticalCenter: parent.verticalCenter
                Item {
                    width: 26 * win.u; height: 13 * win.u
                    anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: parent.width - 3 * win.u; height: parent.height; radius: 3 * win.u; color: "transparent"; border.width: 1.5; border.color: Theme.muted
                        Rectangle { x: 2; y: 2; height: parent.height - 4; radius: 1.5
                            width: Math.max(2, (parent.width - 4) * system.stats.battery / 100)
                            color: system.stats.charging ? Theme.accent : (system.stats.battery < 20 ? Theme.hot : Theme.text) } }
                    Rectangle { x: parent.width - 3 * win.u; anchors.verticalCenter: parent.verticalCenter; width: 3 * win.u; height: parent.height * 0.4; radius: 1; color: Theme.muted }
                }
                Text { anchors.verticalCenter: parent.verticalCenter; color: Theme.text; font.pixelSize: 14 * win.u; text: system.stats.battery + "%" }
            }
        }
    }

    Rectangle {
        id: nav
        x: 10 * win.u
        width: parent.width - 20 * win.u
        height: 92 * win.u
        y: win.chrome ? parent.height - height - 10 * win.u : parent.height + 4
        Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        radius: Theme.radius * win.u
        color: Theme.card
        Row {
            anchors.fill: parent
            Repeater {
                model: win.pages
                delegate: CircleButton {
                    width: nav.width / win.pages.length
                    height: nav.height
                    size: 44 * win.u
                    icon: modelData.icon
                    label: modelData.label
                    on: win.section === modelData.id
                    onClicked: win.go(modelData.id)
                }
            }
        }
    }

    PasswordDialog {
        anchors.fill: parent
        visible: Auth.ask !== ""
        action: Auth.ask
        onCancelled: Auth.ask = ""
        onAccepted: password => { admin.run(Auth.ask, password); Auth.ask = "" }
    }

    // dimming: a black veil; its own touch handler swallows the wake-up tap
    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: win.dimmed ? 0.6 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 500 } }
        MouseArea { anchors.fill: parent; enabled: win.dimmed; onPressed: win.wake() }
    }
}
