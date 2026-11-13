import QtQuick

// Choose which installed app goes into a grid slot.
Rectangle {
    id: p
    property int slot: -1
    property string folder: ""     // set: the picker adds to this folder instead of filling a grid slot
    property var items: []
    property var groups: []
    property string group: "apps"
    property string query: ""
    signal closed()

    color: Theme.bg
    onVisibleChanged: if (visible) { query = ""; search.text = ""; items = apps.catalog().concat(apps.folderChoices()); groups = apps.groups().filter(g => p.folder === "" || g.id !== "folders"); if (folder !== "" && group === "folders") group = "apps" }
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
            text: p.folder !== "" ? Tr.t("Add to folder") : Tr.t("App for slot") + " " + (p.slot + 1)
        }
        Row {
            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 8
            Repeater {
                model: p.folder !== "" ? [{ l: Tr.t("Cancel"), remove: false }] : [{ l: Tr.t("Remove"), remove: true }, { l: Tr.t("Cancel"), remove: false }]
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
    // tabs: desktop apps, Steam, and one per ES-DE system that has games
    ListView {
        id: tabs
        anchors { left: parent.left; right: parent.right; top: head.bottom }
        height: 44
        orientation: ListView.Horizontal
        spacing: 8
        leftMargin: 12
        rightMargin: 12
        clip: true
        model: p.groups
        delegate: Rectangle {
            width: tabText.width + 28
            height: 36
            radius: Theme.radius
            color: p.group === modelData.id ? Theme.accentSoft : Theme.card
            border.color: p.group === modelData.id ? Theme.accent : Theme.border
            Text {
                id: tabText
                anchors.centerIn: parent
                color: Theme.text
                font.pixelSize: 15
                text: modelData.id === "apps" ? Tr.t("Apps") : modelData.id === "steam" ? "Steam" : modelData.id === "folders" ? Tr.t("Folders") : modelData.label
            }
            MouseArea { anchors.fill: parent; onClicked: p.group = modelData.id }
        }
    }
    // search: while something is typed it looks through every tab at once
    Rectangle {
        id: searchBox
        anchors { left: parent.left; right: parent.right; top: tabs.bottom; leftMargin: 12; rightMargin: 12 }
        height: 38
        radius: Theme.radius
        color: Theme.card
        border.color: search.activeFocus ? Theme.accent : Theme.border
        TextInput {
            id: search
            anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
            verticalAlignment: TextInput.AlignVCenter
            color: Theme.text
            font.pixelSize: 16
            clip: true
            onActiveFocusChanged: shell.textFocus(activeFocus)
            onTextChanged: p.query = text.trim().toLowerCase()
        }
        Text {
            visible: search.text === ""
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            color: Theme.muted
            font.pixelSize: 16
            text: Tr.t("Search")
        }
    }
    ListView {
        anchors { left: parent.left; right: parent.right; top: searchBox.bottom; topMargin: 6; bottom: parent.bottom }
        clip: true
        model: p.items.filter(function (i) { return p.query !== "" ? (i.name || "").toLowerCase().indexOf(p.query) >= 0 && (p.folder === "" || i.group !== "folders") : i.group === p.group })
        delegate: Item {
            width: ListView.view.width
            height: 60
            Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 } height: 1; color: Theme.border }
            Text {
                visible: !!modelData.glyph || !!modelData.folder
                x: 16
                width: 40
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 26
                color: Theme.accent
                text: modelData.glyph || "▣"
            }
            Image {
                visible: !modelData.glyph && !modelData.folder
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
                text: modelData.folder || modelData.glyph ? Tr.t(modelData.name) : modelData.name
            }
            MouseArea { anchors.fill: parent; onClicked: { if (p.folder !== "") apps.addToFolder(p.folder, modelData.id); else apps.assign(p.slot, modelData.id); p.closed() } }
        }
    }
}
