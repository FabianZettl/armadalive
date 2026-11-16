import QtQuick

// Round icon button with a caption, the building block of the quick-setting grid and the navigation bar.
// Disc and caption are centred together in whatever space the button is given.
Item {
    id: b
    property string icon
    property string label
    property bool on: false
    property bool marked: false     // picked for moving
    property real size: 52
    property int pressedKey: 0
    signal clicked()
    signal held()

    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: if (enabled) clicked()

    Keys.onPressed: event => {
        if (event.key !== Qt.Key_Return && event.key !== Qt.Key_Enter && event.key !== Qt.Key_Space) return
        if (!event.isAutoRepeat && b.pressedKey === 0) b.pressedKey = event.key
        event.accepted = true
    }
    Keys.onReleased: event => {
        if (event.key !== Qt.Key_Return && event.key !== Qt.Key_Enter && event.key !== Qt.Key_Space) return
        event.accepted = true
        if (event.isAutoRepeat || event.key !== b.pressedKey) return
        b.pressedKey = 0
        b.clicked()
    }
    onActiveFocusChanged: if (!activeFocus) pressedKey = 0
    onEnabledChanged: if (!enabled) pressedKey = 0

    implicitWidth: 72
    implicitHeight: 96

    Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: 6
        Rectangle {
            id: disc
            width: b.size; height: b.size; radius: Theme.disc(width)
            anchors.horizontalCenter: parent.horizontalCenter
            color: b.on ? Theme.accentSoft : Theme.circle
            border.width: b.activeFocus ? 2 : 0
            border.color: Theme.accent
            scale: area.pressed || b.pressedKey ? 0.92 : 1
            Behavior on scale { NumberAnimation { duration: Theme.dur(80); easing.type: Theme.ease; easing.overshoot: Theme.overshoot } }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width + 8; height: width; radius: Theme.disc(width)
                color: "transparent"
                border.width: 2
                border.color: Theme.accent
                visible: b.marked
            }
            Icon {
                anchors.centerIn: parent
                width: b.size * 0.5; height: width
                name: b.icon
                color: b.on ? Theme.accent : Theme.text
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 6
            horizontalAlignment: Text.AlignHCenter
            maximumLineCount: 1
            elide: Text.ElideRight
            color: b.on ? Theme.text : Theme.muted
            font.pixelSize: Math.max(10, b.size * 0.24)
            text: b.label
        }
    }
    MouseArea { id: area; anchors.fill: parent; onClicked: b.clicked(); onPressAndHold: b.held() }
}
