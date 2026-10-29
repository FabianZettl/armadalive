import QtQuick

// The game in front: background and logo. Two layers cross-fade when the game changes, so scrolling through ES-DE or
// Steam is soft instead of a hard cut.
Item {
    id: root
    readonly property var s: nowPlaying.state
    readonly property bool idle: s.kind === "idle"
    readonly property bool animate: ui.state.animate !== false     // Settings > Logo animation
    // only a real change of game, logo or background starts a transition, not every refresh of the state
    readonly property string sig: [s.kind, s.title, s.logo, s.fanart].join("|")

    // slow 0..1..0 swell that drives the idle motion of the logo
    property real breathe: 0
    SequentialAnimation on breathe {
        running: !idle && root.animate
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 3600; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 3600; easing.type: Easing.InOutSine }
    }

    // -1..1..-1 swing for the tilt; its period differs from the float above, so the two never line up
    property real sway: -1
    SequentialAnimation on sway {
        running: !idle && root.animate
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2600; easing.type: Easing.InOutSine }
        NumberAnimation { to: -1; duration: 2600; easing.type: Easing.InOutSine }
    }

    component Layer: Item {
        id: l
        property var st: ({ kind: "idle", title: "", logo: "", fanart: "" })
        property real v: 0              // 0 hidden .. 1 shown
        property real breathe: 0
        property real sway: 0
        property real k: 1              // 0 turns the idle motion off
        anchors.fill: parent
        opacity: v
        visible: v > 0.01
        Behavior on v { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        Image { anchors.fill: parent; source: l.st.fanart; fillMode: Image.PreserveAspectCrop; asynchronous: true; opacity: 0.45 }
        Rectangle { anchors.fill: parent; color: Theme.bg; opacity: 0.35 }

        Item {
            anchors.fill: parent
            scale: 0.96 + 0.04 * l.v    // the logo grows a little while it fades in
            // natural size of the logo, measured on an image that has no size of its own (the visible one would loop)
            Image { id: natural; visible: false; source: l.st.logo }
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
                source: l.st.logo
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                // 75 % of the former size: game marquees are small PNGs (1.5x their size), system logos are SVGs
                width: l.st.kind === "game" ? Math.min(natural.implicitWidth * 1.5, l.width * 0.72) : l.width * 0.6
                height: l.height * 0.64
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

    Layer { id: la; breathe: root.breathe; sway: root.sway; k: root.animate ? 1 : 0 }
    Layer { id: lb; breathe: root.breathe; sway: root.sway; k: root.animate ? 1 : 0 }
    property var cur: la

    Component.onCompleted: { la.st = s; la.v = idle ? 0 : 1 }
    onSigChanged: {
        extras = false
        if (idle) { cur.v = 0; return }
        const next = cur === la ? lb : la
        next.st = s
        next.v = 1
        cur.v = 0
        cur = next
    }

    // a tap on the artwork shows Manual and Cheats for a few seconds, if this game has them
    property bool extras: false
    TapHandler { enabled: !root.idle; onTapped: { root.extras = !root.extras; hideExtras.restart() } }
    Timer { id: hideExtras; interval: 4000; onTriggered: root.extras = false }
    Row {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 130 }
        spacing: 12
        opacity: root.extras ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 180 } }
        PillButton { visible: root.s.manual !== ""; label: Tr.t("Manual"); onClicked: { root.extras = false; Nav.go = "manual" } }
        PillButton { visible: root.s.hasCheats === true; label: Tr.t("Cheats"); onClicked: { root.extras = false; Nav.go = "cheats" } }
    }

    AppGrid {
        anchors.fill: parent
        opacity: idle ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 220 } }
    }
}
