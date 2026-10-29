import QtQuick

// Horizontal fill bar with an icon and a caption, as used for brightness and volume.
Item {
    id: s
    property string icon
    property string label
    property real value: 0          // 0..1
    property real minimum: 0
    signal committed(real value)

    implicitHeight: 46
    property real shown: value
    onValueChanged: if (!area.pressed) shown = value

    Text {
        id: cap
        width: 74
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.muted
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        text: s.label
    }
    Rectangle {
        id: track
        anchors { left: cap.right; right: parent.right; rightMargin: 26; verticalCenter: parent.verticalCenter }   // short of the edge, so 100 % is easy to reach
        height: 32
        radius: 16
        color: Theme.circle
        clip: true
        Rectangle { width: Math.max(parent.height, parent.width * s.shown); height: parent.height; radius: 16; color: Theme.muted }
        Icon {
            x: 8; anchors.verticalCenter: parent.verticalCenter
            width: 18; height: 18
            name: s.icon
            color: Theme.bg
        }
    }
    // the touch area is the whole row, margin included: dragging past the end of the bar means 100 %
    MouseArea {
        id: area
        anchors { left: cap.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        function set(mx) {
            const v = mx / track.width
            s.shown = Math.max(s.minimum, Math.min(1, v > 0.97 ? 1 : v))
        }
        onPressed: mouse => { Gesture.hold(true); set(mouse.x) }
        onPositionChanged: mouse => set(mouse.x)
        onReleased: { Gesture.hold(false); s.committed(s.shown) }
        onCanceled: Gesture.hold(false)
    }
}
