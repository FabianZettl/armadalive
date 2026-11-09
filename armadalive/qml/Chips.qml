import QtQuick

// A row of mutually exclusive choices.
Flow {
    id: c
    property var model: []          // [{ key, label }]
    property string current
    signal picked(string key)
    spacing: 8

    Repeater {
        model: c.model
        delegate: Rectangle {
            readonly property bool on: c.current === modelData.key
            height: 42
            width: label.width + 30
            radius: Theme.radius
            color: on ? Theme.accent : Theme.card
            border.color: on ? Theme.accent : Theme.border
            border.width: Theme.borderW
            Text {
                id: label
                anchors.centerIn: parent
                text: modelData.label
                color: parent.on ? Theme.onAccent : Theme.text
                font.pixelSize: 16
            }
            MouseArea { anchors.fill: parent; onClicked: c.picked(modelData.key) }
        }
    }
}
