import QtQuick
import QtQuick.Window

Window {
    id: win
    visible: true
    width: 620
    height: 540
    color: Theme.bg
    Backdrop { anchors.fill: parent; z: -1 }
    title: "ArmadaLive"

    readonly property var now: nowPlaying.state
    // Manual and Cheats are reached by tapping the Game page, and only while the current game has them; "under" pages are not in the bar
    readonly property var all: [
        { id: "now", label: Tr.t("Game"), icon: "play", file: "NowPlaying.qml", has: true },
        { id: "manual", label: Tr.t("Manual"), icon: "book", file: "Manual.qml", has: now.manual !== "", under: "now" },
        { id: "cheats", label: Tr.t("Cheats"), icon: "cheats", file: "Cheats.qml", has: now.hasCheats, under: "now" },
        { id: "apps", label: Tr.t("Apps"), icon: "apps", file: "Apps.qml", has: ui.state.apps !== false },
        { id: "mode", label: Tr.t("Mode"), icon: "mode", file: "Mode.qml", has: true },
        { id: "controls", label: Tr.t("Controls"), icon: "pad", file: "Trackpad.qml", has: true },
        { id: "system", label: Tr.t("System"), icon: "gear", file: "System.qml", has: true },
        { id: "prefs", label: Tr.t("Settings"), icon: "info", file: "Preferences.qml", has: true, under: "system" },
        { id: "tuning", label: Tr.t("Tuning"), icon: "perf", file: "Tuning.qml", has: true, under: "system" },
        { id: "graphs", label: Tr.t("Graphs"), icon: "graph", file: "Graphs.qml", has: true, under: "system" },
        { id: "tasks", label: Tr.t("Tasks"), icon: "apps", file: "Tasks.qml", has: true, under: "system" }
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
    property bool blanked: false        // screen off: true black, ignores touches, a long press or the AYN button wakes it
    property bool pressWasBlanked: false
    property bool pressWasFront: false
    property string askDemo: ""     // snapshots only: open the password dialog
    onAskDemoChanged: Auth.ask = askDemo
    readonly property bool dimEnabled: ui.state.dim !== false     // Settings > Dim after 10 s
    function wake() { dimmed = false; if (dimEnabled) idle.restart() }
    onDimEnabledChanged: { if (dimEnabled) idle.restart(); else { idle.stop(); dimmed = false } }
    Timer {
        id: idle
        interval: 10000
        onTriggered: { if (!win.dimEnabled) return; if (Auth.ask === "" && !Gesture.locked && !touch.active) win.dimmed = true; else idle.restart() }   // not while the password prompt is open
    }
    // sees every touch, takes none; a finger that stays down and moves (a slider, a scroll, the trackpad) is not idle either
    // a finger that lies still on the glass is not idle either: the timer checks `touch.active` before it dims, and lifting the finger starts it again
    PointHandler { id: touch; target: null; onActiveChanged: win.wake(); onPointChanged: if (active && win.dimEnabled) idle.restart() }
    // every touch, click and key on the window, whichever item takes it (activity.py): the timer starts again for all of them, a finger going down or up included
    Connections { target: activity; function onSeen() { if (!win.dimmed && win.dimEnabled) idle.restart() } }
    // a new game, logo or background (scrolling in ES-DE or Steam, a game starting) brightens it too
    readonly property string shown: [now.kind, now.title, now.logo, now.fanart].join("|")
    onShownChanged: wake()

    // always full screen: Plasma's own panels only come back with its swipe-up gesture
    // --windowed (desktop mode, one Plasma session for both screens): an ordinary window, not the always-fullscreen bottom screen
    readonly property bool windowed: Qt.application.arguments.indexOf("--windowed") >= 0
    function applyVisibility() { if (!windowed && visibility !== Window.FullScreen) visibility = Window.FullScreen }
    // whatever un-fullscreens the window (another app, Plasma, a resize) is undone at once; Plasma's swipe-up panels draw over it
    onVisibilityChanged: if (win.visible && win.visibility !== Window.FullScreen && win.visibility !== Window.Hidden && win.visibility !== Window.Minimized) Qt.callLater(applyVisibility)
    onActiveChanged: if (active) applyVisibility()
    Timer { interval: 3000; running: win.visible; repeat: true; onTriggered: if (win.visibility === Window.Windowed || win.visibility === Window.Maximized) win.applyVisibility() }
    function go(id) { page = id; if (home) hideChrome.restart() }
    function step(delta) {
        const i = pages.findIndex(p => p.id === section), j = i + delta
        if (i >= 0 && j >= 0 && j < pages.length) go(pages[j].id)
    }
    onCurrentChanged: if (current.id !== page) page = current.id
    onHomeChanged: if (home) { peek = true; hideChrome.restart() }
    // "Follow game" takes its colour from the artwork the top screen is showing; without artwork it falls back to its plain palette
    readonly property string followColor: ui.state.theme === "follow" ? artwork.dominant(now.fanart || now.logo || "") : ""
    function applyTheme() {
        Theme.apply(ui.state.theme, ui.state.theme === "follow" ? followColor : ui.state.accent)
        ui.applyFont(Theme.fontFamily)
    }
    onFollowColorChanged: applyTheme()
    Component.onCompleted: { if (dimEnabled) idle.start(); applyVisibility(); applyTheme(); Tr.lang = ui.state.lang; ledSync.start(); activity.watch(win) }
    // The stick LEDs follow the theme's accent, until the user picks a colour of their own (Mode page). Only while the LEDs are on and the
    // root helper can set them; a moment after the last change, because the accent fades and "Follow game" changes it with every game.
    function accentHex() { const c = Theme.accent; return [c.r, c.g, c.b].map(x => ("0" + Math.round(x * 255).toString(16)).slice(-2)).join("").toUpperCase() }
    Timer {
        id: ledSync
        interval: 1500
        onTriggered: {
            const d = settings.data, rgb = d.rgb || ({})
            if (ui.state.ledFollow === false || d.helper !== true || rgb.enabled === false) return
            if ((rgb.color || "").toUpperCase() !== win.accentHex()) settings.setRgb(true, win.accentHex(), rgb.brightness === undefined ? 25 : rgb.brightness)
        }
    }
    Connections { target: Theme; function onAccentChanged() { ledSync.restart() } }
    Connections { target: ui; function onChanged() { ledSync.restart() } }
    Connections { target: settings; function onChanged() { if (!ledSync.running) ledSync.start() } }
    Connections {
        target: ui
        function onChanged() { win.applyTheme(); Tr.lang = ui.state.lang }
    }
    Connections {
        target: nowPlaying
        function onSelection() { win.go("now") }
    }
    Connections {
        target: Nav
        function onGoChanged() {
            if (Nav.go === "blank") win.blanked = true
            else if (Nav.go) win.go(Nav.go)
            Nav.go = ""
        }
    }
    // the AYN button (see scripts/ayn-button.sh) always brings the app up, whatever is in front on this screen
    Connections {
        target: ayn
        function onLongPressed() { if (!win.pressWasBlanked) win.blanked = true }   // hold the AYN button: screen off
        // a tap toggles: in front it goes to the background (so a dual-screen game on this screen shows), otherwise it comes up.
        // Going away waits for the release, because holding the button turns the screen off and must not hide the window first.
        function onPressed() {
            win.pressWasBlanked = win.blanked
            win.pressWasFront = win.active && win.visible && !win.blanked && win.visibility !== Window.Minimized
            if (!win.pressWasFront) win.bringUp()
            else win.wake()
            check.restart()
        }
        function onReleased() {
            if (!win.pressWasFront) return
            win.pressWasFront = false
            win.showMinimized()
        }
    }
    function bringUp() {
        blanked = false
        wake()
        show()
        applyVisibility()
        raise()
        requestActivate()
        shell.activate()
    }
    // holding Start + Select starts a countdown; the window comes up so it can be seen
    Connections {
        target: closer
        function onBegun() { win.bringUp() }
    }
    Connections {
        target: tasks
        function onSwitched() { win.showMinimized() }   // a window was picked in Tasks: step back so it shows
    }
    Connections {
        target: battery
        function onAlert(percent) { win.bringUp(); toast.show(Tr.t("Battery low") + ": " + percent + " %", true) }
    }
    Timer {
        id: check
        interval: 900
        onTriggered: console.info("AYN: window visible=" + win.visible + " active=" + win.active)
    }
    Timer { id: hideChrome; interval: 3000; onTriggered: win.peek = false }

    Item {
        id: body
        anchors { left: parent.left; right: parent.right; top: win.home ? parent.top : status.bottom; bottom: win.home ? parent.bottom : (mediaBar.visible ? mediaBar.top : nav.top) }
        clip: true
        Loader {
            anchors { fill: parent; leftMargin: win.home ? 0 : 12 * win.u; rightMargin: win.home ? 0 : 12 * win.u; topMargin: win.home ? 0 : 6 * win.u; bottomMargin: win.home ? 0 : 6 * win.u }
            source: win.current.file
        }
        // swipe sideways between pages; the PDF view keeps its own panning
        DragHandler {
            target: null
            yAxis.enabled: false
            // not over the app grid (Apps page, or the Game page while idle): a sideways drag there scrolls the grid, and this handler
            // would take it over (a lock set on touch-down came too late); the bar still switches pages
            enabled: win.current.id !== "manual" && !Gesture.locked && win.current.id !== "apps" && !(win.home && win.now.kind === "idle")
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
        Behavior on y { NumberAnimation { duration: Theme.dur(180); easing.type: Theme.ease } }
        color: win.home ? Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.7) : "transparent"
        Text {
            id: clock
            x: 24 * win.u
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.text
            font.pixelSize: 15 * win.u
            text: Qt.formatTime(new Date(), "hh:mm")
            Timer { interval: 10000; running: true; repeat: true; onTriggered: clock.text = Qt.formatTime(new Date(), "hh:mm") }
        }
        Row {
            anchors { right: parent.right; rightMargin: 24 * win.u; verticalCenter: parent.verticalCenter }
            spacing: 12 * win.u
            Icon { visible: (controls.state.tailscale || ({})).state === "on"; width: 18 * win.u; height: width; anchors.verticalCenter: parent.verticalCenter; name: "vpn"; color: Theme.accent }
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
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.text
                    font.pixelSize: 14 * win.u
                    // minutes left (or until full) when the current is steady enough to tell
                    text: system.stats.battery + "%" + (system.stats.eta > 0 ? "  ·  " + Math.floor(system.stats.eta / 60) + "h " + (system.stats.eta % 60) + "m" : "")
                }
            }
        }
    }

    Rectangle {
        id: nav
        x: 18 * win.u
        width: parent.width - 36 * win.u
        height: 92 * win.u
        y: win.chrome ? parent.height - height - 16 * win.u : parent.height + 4
        Behavior on y { NumberAnimation { duration: Theme.dur(180); easing.type: Theme.ease } }
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

    // what plays on the main screen (music, video): shown with the other bars, on the game page over the artwork
    Rectangle {
        id: mediaBar
        x: 18 * win.u
        width: parent.width - 36 * win.u
        height: 46 * win.u
        y: nav.y - height - 6 * win.u
        visible: media.state.active === true && win.chrome
        radius: Theme.radius * win.u
        color: Theme.card
        Column {
            anchors { left: parent.left; leftMargin: 14 * win.u; right: buttons.left; rightMargin: 10 * win.u; verticalCenter: parent.verticalCenter }
            Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 14 * win.u; text: media.state.title || "" }
            Text { width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 11 * win.u; visible: text !== ""; text: media.state.artist || "" }
        }
        Row {
            id: buttons
            anchors { right: parent.right; rightMargin: 8 * win.u; verticalCenter: parent.verticalCenter }
            spacing: 6 * win.u
            PillButton { label: "◀◀"; onClicked: media.previous() }
            PillButton { primary: true; label: media.state.status === "Playing" ? "❚❚" : "▶"; onClicked: media.playPause() }
            PillButton { label: "▶▶"; onClicked: media.next() }
        }
    }

    Connections {
        target: thermal
        function onAlert(temp, profile) { win.bringUp(); toast.show(Tr.t("Hot") + ": " + temp + " °C" + (profile ? " · " + profile : ""), true) }
    }
    Connections {
        target: controls
        function onNotice(code, detail) {
            const text = ({ tson: Tr.t("Tailscale connected"), tsoff: Tr.t("Tailscale off"), tslogin: Tr.t("Tailscale needs a login"),
                            tsmissing: Tr.t("Tailscale is not running"), tsfail: Tr.t("Tailscale did not switch"),
                            tsdenied: Tr.t("Run once: sudo tailscale set --operator=armada") })[code]
            toast.show(text, code !== "tson" && code !== "tsoff")
        }
    }
    // short messages from the app: something was done (accent colour) or went wrong (red)
    Connections {
        target: steamShortcuts
        function onNotice(code, title) {
            const text = ({ created: Tr.t("Shortcut created"), exists: Tr.t("Already in Steam"), unknown: Tr.t("Launch the game from ES-DE once first"),
                            unreachable: Tr.t("Steam is not reachable") })[code]
            toast.show(title && code !== "unknown" ? text + ": " + title : text, code !== "created")
        }
    }
    // saving, removing and loading a game rule
    Connections {
        target: rules
        function onNotice(code, detail) {
            const text = ({ saved: Tr.t("Rule saved"), removed: Tr.t("Rule removed"), loaded: Tr.t("Rule loaded") })[code]
            toast.show(text + ": " + detail, false)
        }
    }
    Rectangle {
        id: toast
        property string text
        property bool bad: false
        function show(message, isBad) { text = message; bad = isBad; opacity = 1; hideToast.restart() }
        anchors.horizontalCenter: parent.horizontalCenter
        y: 10 * win.u
        width: Math.min(toastText.implicitWidth + 40 * win.u, parent.width - 40 * win.u)
        height: 40 * win.u
        radius: Theme.pill(height)
        color: bad ? Theme.hot : Theme.accent
        opacity: 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 250 } }
        Text {
            id: toastText
            anchors.centerIn: parent
            width: parent.width - 24 * win.u
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            color: toast.bad ? "#ffffff" : Theme.onAccent
            font.pixelSize: 16 * win.u
            text: toast.text
        }
        Timer { id: hideToast; interval: 4000; onTriggered: toast.opacity = 0 }
    }

    // Ludo is syncing saves before a game starts: stays up until the game is running
    Connections {
        target: ludo
        function onChanged() { if (ludo.state.phase) win.bringUp() }
    }
    Rectangle {
        id: ludoBar
        readonly property string phase: ludo.state.phase
        readonly property string title: ludo.state.title
        anchors.horizontalCenter: parent.horizontalCenter
        y: 58 * win.u
        width: Math.min(ludoText.implicitWidth + 40 * win.u, parent.width - 40 * win.u)
        height: 40 * win.u
        radius: Theme.pill(height)
        color: Theme.accent
        opacity: phase ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 250 } }
        Text {
            id: ludoText
            anchors.centerIn: parent
            width: parent.width - 24 * win.u
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            color: Theme.onAccent
            font.pixelSize: 16 * win.u
            text: {
                const base = ({ check: Tr.t("Checking saves…"), sync: Tr.t("Syncing saves"), start: Tr.t("Starting"), upload: Tr.t("Uploading saves…") })[ludoBar.phase] || ""
                return ludoBar.title ? base + ": " + ludoBar.title : base
            }
        }
    }

    // a tuning change (fan curve, governor, GPU or CPU limit) is taken back unless it is kept, like a new screen resolution
    readonly property var tuning: settings.pending
    onTuningChanged: if (tuning.active) wake()
    Rectangle {
        id: keep
        anchors.horizontalCenter: parent.horizontalCenter
        y: 10 * win.u
        width: Math.min(parent.width - 30 * win.u, 520 * win.u)
        height: keepCol.height + 24 * win.u
        radius: Theme.radius * win.u
        color: Theme.card
        border.color: Theme.warm
        border.width: 2
        opacity: win.tuning.active ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 150 } }
        MouseArea { anchors.fill: parent }
        Column {
            id: keepCol
            x: 14 * win.u; y: 12 * win.u
            width: parent.width - 28 * win.u
            spacing: 8 * win.u
            Text { width: parent.width; color: Theme.text; font.pixelSize: 16 * win.u; wrapMode: Text.WordWrap
                   text: Tr.t("Keep this setting?") + "  ·  " + Tr.t("back to the old one in") + " " + win.tuning.seconds + " s" }
            Rectangle {
                width: parent.width; height: 6 * win.u; radius: height / 2; color: Theme.circle
                Rectangle { width: parent.width * win.tuning.seconds / Math.max(1, win.tuning.total); height: parent.height; radius: height / 2; color: Theme.warm
                            Behavior on width { NumberAnimation { duration: 900 } } }
            }
            Row {
                spacing: 10 * win.u
                PillButton { primary: true; label: Tr.t("Keep"); onClicked: settings.confirm() }
                PillButton { label: Tr.t("Undo"); onClicked: settings.revert() }
            }
        }
    }

    // Start + Select held: countdown until the game in front is closed
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.78)
        opacity: closer.state.phase !== "" ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 150 } }
        MouseArea { anchors.fill: parent }
        Column {
            anchors.centerIn: parent
            width: parent.width - 60 * win.u
            spacing: 14 * win.u
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; color: closer.state.phase === "closed" ? Theme.accent : Theme.muted; font.pixelSize: 16 * win.u
                   text: closer.state.phase === "closed" ? Tr.t("Closed") : Tr.t("Keep holding Start + Select to close") }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 26 * win.u; text: closer.state.title || "" }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, 360 * win.u); height: 12 * win.u; radius: height / 2; color: Theme.circle
                Rectangle { width: parent.width * closer.state.progress; height: parent.height; radius: height / 2; color: closer.state.phase === "closed" ? Theme.accent : Theme.hot }
            }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; color: Theme.text; font.pixelSize: 40 * win.u; font.weight: Font.Medium
                   visible: closer.state.phase === "holding"; text: Math.max(0, 2 - closer.state.progress * 2).toFixed(1) + " s" }
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

    // screen off: nothing but black, touches are swallowed, only holding a finger down or the AYN button brings it back
    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: win.blanked ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 250 } }
        MouseArea { anchors.fill: parent; enabled: win.blanked; onPressAndHold: win.blanked = false }
    }
}
