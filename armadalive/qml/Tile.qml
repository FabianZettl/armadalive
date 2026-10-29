import QtQuick

// Quick-setting tile: a caption, a state line and a lit edge while active.
Rectangle {
    id: t
    property string label
    property string state
    property bool active: false
    signal clicked()

    implicitWidth: 120
    implicitHeight: 74
    radius: Theme.radius
    color: mouse.pressed ? Theme.border : Theme.card
    border.color: active ? Theme.accent : Theme.border

    Column {
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
        spacing: 2
        Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 17; font.weight: Font.DemiBold; text: t.label }
        Text { width: parent.width; elide: Text.ElideRight; color: t.active ? Theme.accent : Theme.muted; font.pixelSize: 14; text: t.state }
    }
    MouseArea { id: mouse; anchors.fill: parent; onClicked: t.clicked() }
}
