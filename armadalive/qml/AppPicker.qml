import QtQuick

// Choose which installed app goes into a grid slot.
Rectangle {
    id: p
    property int slot: -1
    property var items: []
    signal closed()

    color: Theme.bg
    onVisibleChanged: if (visible) items = apps.catalog()
    MouseArea { anchors.fill: parent }      // swallow touches so the grid below stays untouched

    Item {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 56
        Text {
            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
            color: Theme.text
            font.pixelSize: 18
            font.weight: Font.DemiBold
            text: Tr.t("App for slot") + " " + (p.slot + 1)
        }
        Row {
            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 8
            Repeater {
                model: [{ l: Tr.t("Remove"), remove: true }, { l: Tr.t("Cancel"), remove: false }]
                delegate: Rectangle {
                    width: t.width + 28
                    height: 38
                    radius: Theme.radius
                    color: Theme.card
                    border.color: Theme.border
                    Text { id: t; anchors.centerIn: parent; color: modelData.remove ? Theme.hot : Theme.text; font.pixelSize: 15; text: modelData.l }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { if (modelData.remove) apps.assign(p.slot, ""); p.closed() }
                    }
                }
            }
        }
    }
    ListView {
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom }
        clip: true
        model: p.items
        delegate: Item {
            width: ListView.view.width
            height: 60
            Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 } height: 1; color: Theme.border }
            Image {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                width: 40
                height: 40
                source: modelData.icon || ""
                sourceSize: Qt.size(80, 80)
                fillMode: Image.PreserveAspectFit
                asynchronous: true
            }
            Text {
                x: 72
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.text
                font.pixelSize: 17
                text: modelData.name
            }
            MouseArea { anchors.fill: parent; onClicked: { apps.assign(p.slot, modelData.id); p.closed() } }
        }
    }
}
