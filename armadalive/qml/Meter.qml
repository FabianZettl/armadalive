import QtQuick

Rectangle {
    id: m
    property string label
    property string value
    property string detail
    property real fraction: 0
    property color tint: Theme.accent

    implicitHeight: 124
    radius: Theme.radius
    color: Theme.card
    border.color: Theme.border

    Column {
        x: 14; y: 10
        width: parent.width - 28
        spacing: 2
        Text { color: Theme.muted; font.pixelSize: 15; text: m.label }
        Text { color: Theme.text; font.pixelSize: 30; font.weight: Font.DemiBold; text: m.value }
        Text { color: Theme.muted; font.pixelSize: 14; text: m.detail; visible: m.detail !== "" }
    }
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 14 }
        height: 6
        radius: 3
        color: Theme.border
        Rectangle {
            width: parent.width * Math.max(0, Math.min(1, m.fraction))
            height: parent.height
            radius: 3
            color: m.tint
            Behavior on width { NumberAnimation { duration: 300 } }
        }
    }
}
