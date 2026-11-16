import QtQuick
import QtQuick.Window
import "Artwork.js" as Artwork

// The game in front: background and logo. Two layers cross-fade when the game changes, so scrolling through ES-DE or
// Steam is soft instead of a hard cut.
Item {
    id: root
    readonly property var s: nowPlaying.state
    readonly property bool idle: s.kind === "idle"
    property bool presentationActive: !Window.window || Window.window.presentationActive !== false
    readonly property bool animate: ui.state.animate !== false     // Settings > Logo animation
    // only a real change of game, logo or background starts a transition, not every refresh of the state
    readonly property string sig: [s.kind, s.title, s.logo, s.fanart].join("|")

    // slow 0..1..0 swell that drives the idle motion of the logo
    property real breathe: 0
    SequentialAnimation on breathe {
        running: !root.idle && root.animate && root.presentationActive && root.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 3600; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 3600; easing.type: Easing.InOutSine }
    }

    // -1..1..-1 swing for the tilt; its period differs from the float above, so the two never line up
    property real sway: -1
    SequentialAnimation on sway {
        running: !root.idle && root.animate && root.presentationActive && root.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2600; easing.type: Easing.InOutSine }
        NumberAnimation { to: -1; duration: 2600; easing.type: Easing.InOutSine }
    }

    component Layer: Item {
        id: l
        property var st: ({ kind: "idle", title: "", logo: "", fanart: "" })
        property bool presentationActive: true
        property real v: 0              // 0 hidden .. 1 shown
        property real breathe: 0
        property real sway: 0
        property real k: 1              // 0 turns the idle motion off
        anchors.fill: parent
        opacity: v
        visible: v > 0.01
        Behavior on v { enabled: l.presentationActive; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        Item {
            anchors.fill: parent
            clip: true
            Image {
                anchors.centerIn: parent
                readonly property real fit: implicitWidth > 0 && implicitHeight > 0
                                            ? Math.max(parent.width / implicitWidth, parent.height / implicitHeight) : 0
                width: implicitWidth * fit
                height: implicitHeight * fit
                source: l.visible ? Artwork.source(l.st.fanart) : ""
                sourceSize: Qt.size(1280, 1080)
                asynchronous: true
                opacity: 0.45
            }
        }
        Rectangle { anchors.fill: parent; color: Theme.bg; opacity: 0.35 }

        Item {
            anchors.fill: parent
            scale: 0.96 + 0.04 * l.v    // the logo grows a little while it fades in
            // ES-DE's system logos are white: on a light theme they get a dark plate to stay readable
            Rectangle {
                visible: Theme.light && l.st.kind !== "game" && logoImg.visible
                anchors.centerIn: logoImg
                anchors.verticalCenterOffset: logoImg.anchors.verticalCenterOffset
                width: Math.min(l.width * 0.8, logoImg.paintedWidth + 60)
                height: logoImg.paintedHeight + 40
                radius: 24
                color: "#2b2b36"
                opacity: 0.9
            }
            Image {
                id: logoImg
                visible: source != ""
                anchors.centerIn: parent
                anchors.verticalCenterOffset: (0.5 - l.breathe) * 10 * l.k   // floats up and down, gently
                scale: 1 + 0.01 * l.breathe * l.k
                opacity: 1 - 0.06 * (1 - l.breathe) * l.k
                rotation: 1.5 * l.sway * l.k                            // leans a little left and right
                transform: Rotation {                                   // and turns a little around its vertical axis
                    origin.x: logoImg.width / 2; origin.y: logoImg.height / 2
                    axis { x: 0; y: 1; z: 0 }
                    angle: 3 * l.sway * l.k
                }
                // Loading a source can update sourceSize, so use the decode request to select it.
                readonly property size logoDecodeSize: Qt.size(1024, 768)
                source: l.visible ? Artwork.source(l.st.logo, l.st.kind === "game" ? logoDecodeSize : null) : ""
                sourceSize: logoDecodeSize
                asynchronous: true
                // Stretch keeps the decode bounded. Fit the item itself to keep the artwork's proportions.
                readonly property real maxWidth: l.st.kind === "game" ? Math.min(implicitWidth * 1.5, l.width * 0.72) : l.width * 0.6
                readonly property real fit: implicitWidth > 0 && implicitHeight > 0
                                            ? Math.min(maxWidth / implicitWidth, l.height * 0.64 / implicitHeight) : 0
                width: implicitWidth * fit
                height: implicitHeight * fit
            }
            Text {
                id: titleText
                visible: l.st.logo === ""
                anchors.centerIn: parent
                anchors.verticalCenterOffset: (0.5 - l.breathe) * 10 * l.k
                scale: 1 + 0.01 * l.breathe * l.k
                opacity: 1 - 0.06 * (1 - l.breathe) * l.k
                rotation: 1.5 * l.sway * l.k
                transform: Rotation {
                    origin.x: titleText.width / 2; origin.y: titleText.height / 2
                    axis { x: 0; y: 1; z: 0 }
                    angle: 3 * l.sway * l.k
                }
                width: l.width * 0.7
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: Theme.text
                font.pixelSize: 33
                font.weight: Font.DemiBold
                text: l.st.title
            }
        }
    }

    Layer { id: la; presentationActive: root.presentationActive; breathe: root.breathe; sway: root.sway; k: root.animate ? 1 : 0 }
    Layer { id: lb; presentationActive: root.presentationActive; breathe: root.breathe; sway: root.sway; k: root.animate ? 1 : 0 }
    property var cur: la

    property string shownSig: ""
    Component.onCompleted: if (presentationActive) {
        la.st = s
        la.v = idle ? 0 : 1
        shownSig = sig
    }
    onSigChanged: {
        extras = false
        if (presentationActive) syncArtwork()
    }
    onPresentationActiveChanged: if (presentationActive && shownSig !== sig) syncArtwork()
    function syncArtwork() {
        shownSig = sig
        if (idle) { cur.v = 0; return }
        const next = cur === la ? lb : la
        next.st = s
        next.v = 1
        cur.v = 0
        cur = next
    }

    // a tap on the artwork shows Info, Manual and Cheats and the play time for a few seconds
    property bool extras: false
    property bool showPlaytime: false
    function formatPlaytime(seconds) {
        if (seconds < 60) return seconds + " min"
        if (seconds < 3600) return Math.round(seconds / 60) + " min"
        const hours = Math.floor(seconds / 3600)
        const mins = Math.round((seconds % 3600) / 60)
        return mins > 0 ? hours + "h " + mins + "m" : hours + "h"
    }
    TapHandler { enabled: !root.idle; onTapped: {
        root.extras = !root.extras
        root.showPlaytime = root.extras
        hideExtras.restart()
    } }
    Timer { id: hideExtras; interval: 4000; onTriggered: { root.extras = false; root.showPlaytime = false } }
    Row {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 130 }
        spacing: 12
        opacity: root.extras ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { enabled: root.presentationActive; NumberAnimation { duration: 180 } }
        PillButton { visible: root.s.manual !== ""; label: Tr.t("Manual"); onClicked: { root.extras = false; Nav.go = "manual" } }
        PillButton { visible: root.s.hasCheats === true; label: Tr.t("Cheats"); onClicked: { root.extras = false; Nav.go = "cheats" } }
        PillButton { visible: root.s.kind === "game"; label: Tr.t("Info"); onClicked: { root.extras = false; Nav.go = "info" } }
    }

    Text {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 190 }
        opacity: root.showPlaytime && root.s.playtime !== undefined ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { enabled: root.presentationActive; NumberAnimation { duration: 180 } }
        color: Theme.accent
        font.pixelSize: 28
        font.weight: Font.DemiBold
        text: "▶ " + root.formatPlaytime(root.s.playtime || 0)
    }

    AppGrid {
        anchors.fill: parent
        opacity: idle ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { enabled: root.presentationActive; NumberAnimation { duration: 220 } }
    }
}
