import QtQuick

Item {
    id: page
    readonly property string gameKey: nowPlaying.state.key || ""
    readonly property var items: gameKey ? nowPlaying.cheats() : []
    readonly property var activeIndices: cheats.active[gameKey] || []

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
                border.width: page.activeIndices.indexOf(index) !== -1 ? 2 : 1
                Column {
                    id: col
                    x: 14
                    y: 10
                    width: parent.width - 28
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 18; text: modelData.desc }
                    Text { width: parent.width; wrapMode: Text.WrapAnywhere; color: Theme.accent; font.pixelSize: 14; font.family: "monospace"; text: modelData.code }
                }
                TapHandler { onTapped: cheats.toggle_cheat(page.gameKey, index) }
            }
        }
    }
}
