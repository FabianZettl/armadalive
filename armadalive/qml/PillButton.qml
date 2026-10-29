import QtQuick

Rectangle {
    id: b
    property string label
    property bool primary: false
    signal clicked()
    implicitWidth: text.width + 36
    implicitHeight: 42
    radius: height / 2
    opacity: enabled ? 1 : 0.4
    color: primary ? Theme.accent : Theme.circle
    scale: area.pressed ? 0.96 : 1
    Text {
        id: text
        anchors.centerIn: parent
        color: b.primary ? Theme.bg : Theme.text
        font.pixelSize: 15
        text: b.label
    }
    MouseArea { id: area; anchors.fill: parent; onClicked: b.clicked() }
}
