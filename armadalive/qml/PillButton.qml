import QtQuick

Rectangle {
    id: b
    property string label
    property bool primary: false
    signal clicked()
    implicitWidth: text.width + 36
    implicitHeight: 42
    radius: Theme.pill(height)
    opacity: enabled ? 1 : 0.4
    color: primary ? Theme.accent : Theme.circle
    scale: area.pressed ? 0.96 : 1
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
