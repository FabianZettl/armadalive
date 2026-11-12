import QtQuick

// What is open on the bottom screen (Firefox, a file manager, ...): bring it forward, close it, or force it to end. Reached from the Tasks tile on System.
Item {
    id: page
    readonly property var st: tasks.state
    property string confirm: ""      // the window whose "End" was tapped once

    Component.onCompleted: tasks.setActive(true)
    Component.onDestruction: tasks.setActive(false)

    Text {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 16; rightMargin: 16; topMargin: 12 }
        color: Theme.muted
        font.pixelSize: 14
        wrapMode: Text.WordWrap
        text: Tr.t("Open on the bottom screen")
    }
    Text {
        visible: page.st.items.length === 0
        anchors.centerIn: parent
        width: parent.width - 48
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        color: Theme.muted
        font.pixelSize: 17
        text: page.st.ok ? Tr.t("Nothing is open here.") : Tr.t("Looking for the bottom screen's windows…")
    }
    ListView {
        id: list
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; topMargin: 8 }
        clip: true
        spacing: 10
        leftMargin: 12
        rightMargin: 12
        model: page.st.items
        delegate: Rectangle {
            readonly property bool asked: page.confirm === modelData.id
            width: ListView.view.width - 24
            height: 78
            radius: Theme.radius
            color: Theme.card
            border.width: Theme.borderW
            border.color: Theme.border
            MouseArea {     // tap the row to go to that window
                anchors.fill: parent
                onClicked: tasks.activate(modelData.id)
            }
            Column {
                anchors { left: parent.left; right: buttons.left; verticalCenter: parent.verticalCenter; leftMargin: 14; rightMargin: 8 }
                spacing: 3
                Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 17; font.weight: Font.Medium; text: modelData.title }
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    color: Theme.muted
                    font.pixelSize: 13
                    text: modelData.app + "  ·  " + modelData.mb + " MB" + (modelData.windows > 1 ? "  ·  " + modelData.windows + " " + Tr.t("windows") : "") + (modelData.minimized ? "  ·  " + Tr.t("minimised") : "")
                }
            }
            Row {
                id: buttons
                anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                spacing: 8
                PillButton { label: Tr.t("Close"); onClicked: tasks.close(modelData.id) }
                PillButton {
                    label: parent.parent.asked ? Tr.t("Really end?") : Tr.t("End")
                    primary: parent.parent.asked
                    onClicked: { if (parent.parent.asked) { page.confirm = ""; tasks.kill(modelData.id) } else page.confirm = modelData.id }
                }
            }
        }
    }
    Timer { running: page.confirm !== ""; interval: 4000; onTriggered: page.confirm = "" }     // the second tap has to come soon
}
