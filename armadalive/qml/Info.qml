import QtQuick
import QtQuick.Controls

// What ES-DE knows about the game, how long you played it, and your own notes on it.
Flickable {
    id: page
    readonly property var s: nowPlaying.state
    readonly property var info: s.info || ({})
    readonly property real m: 10
    contentHeight: col.height + 2 * m
    clip: true

    function stars(r) { const n = Math.round(parseFloat(r || 0) * 5); return n > 0 ? "★".repeat(n) + "☆".repeat(5 - n) : "" }
    function duration(sec) {
        const m = Math.floor(parseInt(sec || 0) / 60)
        return m <= 0 ? "" : (m >= 60 ? Math.floor(m / 60) + " h " : "") + (m % 60) + " min"
    }
    function day(t) { return t && t.length >= 8 ? t.slice(0, 4) + "-" + t.slice(4, 6) + "-" + t.slice(6, 8) : "" }
    readonly property var chips: [info.releasedate ? info.releasedate.slice(0, 4) : "", info.developer, info.genre,
                                  info.players ? info.players + " " + Tr.t("players") : "", stars(info.rating)].filter(c => c)
    readonly property var facts: [
        [Tr.t("Playtime"), duration(info.gametime)],
        [Tr.t("Played"), info.playcount && info.playcount !== "0" ? info.playcount + "×" : ""],
        [Tr.t("Last played"), day(info.lastplayed)]
    ].filter(f => f[1])

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: page.m

        Rectangle {
            width: parent.width
            height: head.height + 28
            radius: Theme.radius
            color: Theme.card
            Column {
                id: head
                x: 14; y: 14
                width: parent.width - 28
                spacing: 8
                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 22; font.weight: Font.Medium; text: page.s.title }
                Flow {
                    width: parent.width
                    spacing: 8
                    visible: page.chips.length > 0
                    Repeater {
                        model: page.chips
                        delegate: Rectangle {
                            height: 28; width: t.width + 22; radius: 14
                            color: Theme.circle
                            Text { id: t; anchors.centerIn: parent; color: Theme.muted; font.pixelSize: 13; text: modelData }
                        }
                    }
                }
                Repeater {
                    model: page.facts
                    delegate: Text { color: Theme.muted; font.pixelSize: 14; text: modelData[0] + ": " + modelData[1] }
                }
                Text {
                    visible: !!page.info.desc
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: Theme.text
                    font.pixelSize: 15
                    text: page.info.desc || ""
                }
            }
        }

        Rectangle {
            width: parent.width
            height: notes.height + 28
            radius: Theme.radius
            color: Theme.card
            Column {
                x: 14; y: 14
                width: parent.width - 28
                spacing: 8
                Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("Notes") }
                TextArea {
                    id: notes
                    width: parent.width
                    height: Math.max(120, contentHeight + 24)
                    wrapMode: TextArea.Wrap
                    color: Theme.text
                    placeholderText: Tr.t("Tips, where you stopped, anything you want to remember")
                    placeholderTextColor: Theme.muted
                    font.pixelSize: 16
                    inputMethodHints: Qt.ImhNoPredictiveText
                    background: Rectangle { radius: 10; color: Theme.circle; border.color: notes.activeFocus ? Theme.accent : Theme.border }
                    property string loadedKey: ""
                    function load() { loadedKey = page.s.key; text = nowPlaying.notes() }
                    Component.onCompleted: load()
                    onTextChanged: if (loadedKey === page.s.key) save.restart()
                    onActiveFocusChanged: Gesture.hold(activeFocus)     // no page swipes while typing
                    Timer { id: save; interval: 800; onTriggered: nowPlaying.setNotes(notes.text) }
                }
            }
        }
    }
    Connections {
        target: nowPlaying
        function onSelection() { save.stop(); notes.load() }
    }
}
