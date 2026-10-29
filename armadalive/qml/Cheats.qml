import QtQuick

Item {
    readonly property var items: nowPlaying.cheats()

    Empty { visible: parent.items.length === 0; text: Tr.t("This game has no cheats.") }
    ListView {
        id: list
        anchors.fill: parent
        clip: true
        spacing: 8
        topMargin: 12
        bottomMargin: 12
        model: parent.items
        // a ListView sets the position of its delegates itself, so the side margins live inside a full-width item
        delegate: Item {
            width: ListView.view.width
            height: card.height
            Rectangle {
                id: card
                x: 12
                width: parent.width - 24
                height: col.height + 20
                radius: Theme.radius
                color: Theme.card
                border.color: Theme.border
                Column {
                    id: col
                    x: 14
                    y: 10
                    width: parent.width - 28
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 18; text: modelData.desc }
                    Text { width: parent.width; wrapMode: Text.WrapAnywhere; color: Theme.accent; font.pixelSize: 14; font.family: "monospace"; text: modelData.code }
                }
            }
        }
    }
}
