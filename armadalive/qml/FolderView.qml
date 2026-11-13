import QtQuick

// The inside of a folder: its games and apps as a grid. Tap starts one, press and hold takes it out of a manual folder; a manual folder is renamed by
// tapping its name and gets new things with the + tile.
Rectangle {
    id: v
    property string folder: ""
    property var items: []
    property bool renaming: false
    readonly property bool manual: folder.indexOf("folder:") === 0
    readonly property string title: { const s = apps.slots.find(e => e && e.id === folder); return s ? s.name : "" }
    property bool adding: false
    signal closed()

    color: Theme.bg
    function reload() { items = folder !== "" ? apps.folderItems(folder) : [] }
    onFolderChanged: { renaming = false; reload() }
    Connections { target: apps; function onChanged() { v.reload() } }
    MouseArea { anchors.fill: parent }      // swallow touches so the grid below stays untouched

    Item {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 56
        Text {
            visible: !v.renaming
            anchors { left: parent.left; leftMargin: 16; right: diceBtn.visible ? diceBtn.left : closeBtn.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            color: Theme.text
            font.pixelSize: 19
            font.weight: Font.DemiBold
            text: Tr.t(v.title) + (v.items.length ? "  ·  " + v.items.length : "")
            MouseArea { anchors.fill: parent; enabled: v.manual; onClicked: { v.renaming = true; field.text = v.title; field.forceActiveFocus() } }
        }
        TextInput {
            id: field
            visible: v.renaming
            anchors { left: parent.left; leftMargin: 16; right: closeBtn.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            color: Theme.text
            font.pixelSize: 19
            maximumLength: 40
            selectByMouse: true
            onAccepted: { apps.renameFolder(v.folder, text); v.renaming = false }
            onActiveFocusChanged: { shell.textFocus(activeFocus); if (!activeFocus && v.renaming) { apps.renameFolder(v.folder, text); v.renaming = false } }
        }
        PillButton {
            id: diceBtn
            visible: v.items.length > 1
            anchors { right: closeBtn.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            label: "🎲 " + Tr.t("Random")
            onClicked: apps.randomIn(v.folder)
        }
        PillButton { id: closeBtn; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter } label: Tr.t("Back"); onClicked: v.closed() }
    }
    Text {
        visible: v.items.length === 0 && !v.manual
        anchors.centerIn: parent
        color: Theme.muted
        font.pixelSize: 16
        text: Tr.t("Nothing here yet.")
    }
    GridView {
        id: g
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; leftMargin: 12; rightMargin: 12 }
        clip: true
        readonly property int cols: width > 560 ? 4 : 3
        cellWidth: Math.floor(width / cols)
        cellHeight: cellWidth + 26
        model: v.items.concat(v.manual ? [{ plus: true }] : [])
        delegate: Item {
            width: g.cellWidth
            height: g.cellHeight
            Rectangle {
                id: box
                x: 6; y: 6
                width: parent.width - 12
                height: width
                radius: Theme.radius
                color: modelData.plus ? "transparent" : Theme.circle
                border.width: modelData.plus ? 2 : 0
                border.color: Theme.border
                scale: area.pressed ? 0.95 : 1
                Behavior on scale { NumberAnimation { duration: Theme.dur(90) } }
                Image {
                    visible: !!modelData.icon
                    anchors.fill: parent
                    anchors.margins: modelData.cover ? 0 : parent.width * 0.2
                    source: modelData.icon || ""
                    fillMode: modelData.cover ? Image.PreserveAspectCrop : Image.PreserveAspectFit
                    asynchronous: true
                }
                Text {
                    visible: !modelData.icon
                    anchors.centerIn: parent
                    color: modelData.plus ? Theme.border : Theme.accent
                    font.pixelSize: parent.width * 0.4
                    text: modelData.plus ? "+" : (modelData.glyph || (modelData.name ? modelData.name[0] : ""))
                }
            }
            Text {
                visible: !modelData.plus
                anchors { top: box.bottom; topMargin: 3; left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 8 }
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                color: Theme.muted
                font.pixelSize: 12
                text: modelData.name || ""
            }
            MouseArea {
                id: area
                anchors.fill: parent
                onClicked: { if (modelData.plus) v.adding = true; else { apps.launchId(modelData.id); v.closed() } }
                onPressAndHold: { if (v.manual && !modelData.plus) apps.removeFromFolder(v.folder, modelData.id) }
            }
        }
    }
    AppPicker {
        anchors.fill: parent
        visible: v.adding
        folder: v.folder
        onClosed: v.adding = false
    }
}
