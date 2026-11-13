import QtQuick

// A popup over the page: a dimmed background (tap it to close) and a card with a title and scrolling content.
Item {
    id: sheet
    property bool shown: false
    property string title: ""
    default property alias content: inner.data
    anchors.fill: parent
    z: 50
    opacity: shown ? 1 : 0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Theme.dur(160) } }

    Rectangle { anchors.fill: parent; color: "#aa000000"; MouseArea { anchors.fill: parent; onClicked: sheet.shown = false } }
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(sheet.width - 32, 560)
        height: Math.min(sheet.height - 32, flick.contentHeight + 64)
        radius: Theme.radius + 4
        color: Theme.card
        border.width: Theme.borderW
        border.color: Theme.border
        Text { id: head; x: 20; y: 16; color: Theme.muted; font.pixelSize: 15; font.letterSpacing: 0.6; font.capitalization: Font.AllUppercase; text: sheet.title }
        PillButton { anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 8 } label: Tr.t("Done"); primary: true; onClicked: sheet.shown = false }
        Flickable {
            id: flick
            anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 52; bottom: parent.bottom; bottomMargin: 8 }
            contentHeight: inner.height + 12
            clip: true
            Column { id: inner; x: 20; width: parent.width - 40; spacing: 12 }
        }
    }
}
