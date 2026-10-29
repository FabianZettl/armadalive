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
    signal clicked()
    signal held()

    implicitWidth: 72
    implicitHeight: 96

    Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: 6
        Rectangle {
            id: disc
            width: b.size; height: b.size; radius: width / 2
            anchors.horizontalCenter: parent.horizontalCenter
            color: b.on ? Theme.accentSoft : Theme.circle
            scale: area.pressed ? 0.92 : 1
            Behavior on scale { NumberAnimation { duration: 80 } }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width + 8; height: width; radius: width / 2
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
