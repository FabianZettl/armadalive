import QtQuick

Rectangle {
    id: b
    property string label
    property bool primary: false
    property int pressedKey: 0
    signal clicked()
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

    implicitWidth: text.width + 36
    implicitHeight: 42
    radius: Theme.pill(height)
    opacity: enabled ? 1 : 0.4
    color: primary ? Theme.accent : Theme.circle
    border.width: activeFocus ? 2 : 0
    border.color: primary ? Theme.onAccent : Theme.accent
    scale: area.pressed || pressedKey ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: Theme.dur(90); easing.type: Theme.ease } }
    Text {
        id: text
        anchors.centerIn: parent
        color: b.primary ? Theme.onAccent : Theme.text
        font.pixelSize: 15
        text: b.label
    }
    MouseArea { id: area; anchors.fill: parent; onClicked: b.clicked() }
}
