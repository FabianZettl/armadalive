import QtQuick

// Idle screen: nine square app covers. Tap launches on this screen, long-press (or tapping an empty one) picks the app.
Item {
    id: grid
    property int picking: -1
    readonly property var slots: apps.slots
    readonly property real gap: 14
    readonly property real cell: Math.max(60, Math.min((width - 4 * gap) / 3, (height - 4 * gap) / 3))

    // every cell is placed from the current size, not by a Grid that lays out a frame after the cells have already resized
    Item {
        anchors.fill: parent
        Repeater {
            model: 9
            delegate: Rectangle {
                readonly property var app: grid.slots[index] || ({})
                width: grid.cell
                height: grid.cell
                x: Math.round((grid.width - 3 * grid.cell - 2 * grid.gap) / 2) + (index % 3) * (grid.cell + grid.gap)
                y: Math.round((grid.height - 3 * grid.cell - 2 * grid.gap) / 2) + Math.floor(index / 3) * (grid.cell + grid.gap)
                radius: 18
                border.color: Theme.border
                scale: area.pressed ? 0.95 : 1
                Behavior on scale { NumberAnimation { duration: 90 } }
                gradient: Gradient {
                    GradientStop { position: 0; color: Theme.accentSoft }
                    GradientStop { position: 1; color: Theme.card }
                }
                Image {
                    visible: !!app.icon
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -parent.height * 0.06
                    width: parent.width * 0.5
                    height: width
                    source: app.icon || ""
                    sourceSize: Qt.size(width * 2, height * 2)
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }
                Text {
                    visible: !app.icon && !!app.name
                    anchors.centerIn: parent
                    color: Theme.accent
                    font.pixelSize: parent.width * 0.4
                    font.weight: Font.DemiBold
                    text: app.name ? app.name[0] : ""
                }
                Text {
                    visible: !!app.name
                    anchors { bottom: parent.bottom; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
                    width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    color: Theme.muted
                    font.pixelSize: Math.max(11, parent.width * 0.095)
                    text: app.name || ""
                }
                Text {
                    visible: !app.name
                    anchors.centerIn: parent
                    color: Theme.border
                    font.pixelSize: parent.width * 0.4
                    text: "+"
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    onClicked: app.id ? apps.launch(index) : grid.picking = index
                    onPressAndHold: grid.picking = index
                }
            }
        }
    }

    AppPicker {
        anchors.fill: parent
        visible: grid.picking >= 0
        slot: grid.picking
        onClosed: grid.picking = -1
    }
}
