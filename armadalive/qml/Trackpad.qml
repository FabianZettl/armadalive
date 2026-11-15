import QtQuick

// A Steam Deck's trackpads and back buttons. The right pad moves the pointer, the left one scrolls; a tap clicks (left pad:
// right click) and holding a moment before moving drags. L4 L5 R4 R5 are buttons of a virtual pad; each touch buzzes the haptic motor.
// Also shows emulator-specific hotkey buttons at the top when available.
Item {
    id: page
    readonly property real gap: 14
    readonly property string system: nowPlaying.state.system || ""
    property string actionStatus: ""
    property bool actionWarning: false

    Connections {
        target: emulatorControl
        function onNotice(message, kind) {
            page.actionStatus = message
            page.actionWarning = kind === "warn"
            statusTimer.restart()
        }
    }
    Timer {
        id: statusTimer
        interval: 3500
        onTriggered: page.actionStatus = ""
    }

    component Pad: Rectangle {
        id: pad
        property bool scroller: false
        property real sx: 0
        property real sy: 0
        property real lx: 0
        property real ly: 0
        property real travel: 0
        property real wheel: 0
        property bool moved: false
        property bool dragging: false
        property real vx: 0
        property real vy: 0
        property real lastT: 0
        color: Theme.card
        radius: Theme.radius * 1.5
        border.width: 1
        border.color: tp.pressed ? Theme.accent : Theme.border
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height) * 0.72
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 1
            border.color: Theme.border
        }
        Timer {
            id: hold
            interval: 350
            onTriggered: if (!pad.moved && !pad.scroller) { pad.dragging = true; trackpad.button("left", true); trackpad.tick() }
        }
        MultiPointTouchArea {
            id: touch
            anchors.fill: parent
            maximumTouchPoints: 1
            touchPoints: [ TouchPoint { id: tp } ]
            onPressed: {
                Gesture.hold(true)
                pad.sx = pad.lx = tp.x; pad.sy = pad.ly = tp.y; pad.travel = pad.wheel = 0
                pad.moved = pad.dragging = false
                pad.vx = pad.vy = 0; pad.lastT = Date.now()
                trackpad.stopGlide()
                hold.restart()
            }
            onUpdated: {
                const dx = tp.x - pad.lx, dy = tp.y - pad.ly
                pad.lx = tp.x; pad.ly = tp.y
                const now = Date.now(), dt = Math.max(1, now - pad.lastT)
                pad.lastT = now
                pad.vx = 0.6 * pad.vx + 0.4 * dx / dt * 1000; pad.vy = 0.6 * pad.vy + 0.4 * dy / dt * 1000
                if (!pad.moved && Math.hypot(tp.x - pad.sx, tp.y - pad.sy) > 8) { pad.moved = true; hold.stop() }
                if (!pad.moved && !pad.dragging) return
                if (pad.scroller) {
                    pad.wheel += dy
                    while (Math.abs(pad.wheel) > 26) { trackpad.scroll(pad.wheel); trackpad.nudge(); pad.wheel -= Math.sign(pad.wheel) * 26 }
                } else {
                    trackpad.move(dx, dy)
                    pad.travel += Math.hypot(dx, dy)   // a light tick every 40 px, like the detents of the Deck's pad
                    if (pad.travel > 40) { pad.travel = 0; trackpad.nudge() }
                }
            }
            onReleased: {
                hold.stop()
                if (pad.dragging) trackpad.button("left", false)
                else if (pad.moved) { if (!pad.scroller && Date.now() - pad.lastT < 80) trackpad.fling(pad.vx, pad.vy) }
                else {   // a tap
                    const which = pad.scroller ? "right" : "left"
                    trackpad.button(which, true); trackpad.button(which, false); trackpad.tick()
                }
                pad.dragging = false
                Gesture.hold(false)
            }
            onCanceled: { hold.stop(); if (pad.dragging) trackpad.button("left", false); pad.dragging = false; Gesture.hold(false) }
        }
    }

    component Key: Rectangle {
        id: key
        property string label
        property string name: ""     // set for a keyboard key; without it the key is one of the back buttons
        color: kp.pressed ? Theme.accent : Theme.circle
        radius: height / 2
        Text {
            anchors.centerIn: parent
            color: kp.pressed ? Theme.onAccent : Theme.text
            font.pixelSize: 18
            font.weight: Font.Medium
            text: key.label
        }
        MultiPointTouchArea {
            id: touch
            anchors.fill: parent
            maximumTouchPoints: 1
            touchPoints: [ TouchPoint { id: kp } ]
            onPressed: { Gesture.hold(true); trackpad.tick(); if (key.name) trackpad.press(key.name); else trackpad.button(key.label, true) }
            onReleased: { if (!key.name) trackpad.button(key.label, false); Gesture.hold(false) }
            onCanceled: { if (!key.name) trackpad.button(key.label, false); Gesture.hold(false) }
        }
    }

    Row {
        id: keys
        x: page.gap; y: page.gap
        width: parent.width - 2 * page.gap
        height: 56
        spacing: page.gap
        Repeater {
            model: ["L4", "L5", "R4", "R5"]
            Key { required property string modelData; label: modelData; width: (keys.width - 3 * page.gap) / 4; height: keys.height }
        }
    }
    readonly property var emulatorButtons: layout.layout_for(system).hotkeys.concat([{label: "🔄 Glide", id: "glide"}])

    Row {
        id: shortcuts
        x: page.gap; y: keys.y + keys.height + page.gap
        width: parent.width - 2 * page.gap
        height: 48
        spacing: page.gap
        // Esc is always here, whatever the emulator buttons are: it opens the menu of recompiled PC ports (Savage Wind, TotK)
        Key { label: "Esc"; name: "esc"; width: 72; height: shortcuts.height }
        Repeater {
            model: page.emulatorButtons
            Rectangle {
                width: (shortcuts.width - 72 - page.emulatorButtons.length * page.gap) / page.emulatorButtons.length
                height: shortcuts.height
                radius: Theme.radius
                color: modelData.id === "glide" && trackpad.trackball ? Theme.accent : Theme.card
                border.color: Theme.border
                border.width: 1
                Text {
                    anchors.centerIn: parent
                    color: modelData.id === "glide" && trackpad.trackball ? Theme.onAccent : Theme.text
                    font.pixelSize: 12
                    font.weight: Font.Medium
                    text: modelData.label
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (modelData.id === "glide") trackpad.setTrackball(!trackpad.trackball)
                        else emulatorControl.execute(page.system, modelData.id, nowPlaying.state.path)
                    }
                }
            }
        }
    }
    // Trackpads (always show)
    Row {
        x: page.gap
        y: shortcuts.y + shortcuts.height + page.gap
        width: parent.width - 2 * page.gap
        height: parent.height - y - page.gap
        spacing: page.gap
        Pad { width: (parent.width - page.gap) / 2; height: parent.height; scroller: true }
        Pad { width: (parent.width - page.gap) / 2; height: parent.height }
    }
    Text {
        visible: text !== ""
        width: parent.width - 2 * page.gap
        anchors.centerIn: parent
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        color: page.actionStatus !== "" && !page.actionWarning ? Theme.text : Theme.hot
        font.pixelSize: 16
        text: page.actionStatus || trackpad.error
    }
}
