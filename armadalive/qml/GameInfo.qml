import QtQuick

// The game in front: what ES-DE knows about it (description, genre, developer, year, rating), your play time with it and its pictures.
// Reached by tapping the Game page and then Info.
Flickable {
    id: page
    readonly property var s: nowPlaying.state
    property var d: gameinfo.of(s.system || "", s.path || "", s.key || "", s.title || "")
    onSChanged: d = gameinfo.of(s.system || "", s.path || "", s.key || "", s.title || "")
    Connections { target: gameinfo; function onUpdated() { page.d = gameinfo.of(page.s.system || "", page.s.path || "", page.s.key || "", page.s.title || "") } }
    Connections { target: history; function onChanged() { page.d = gameinfo.of(page.s.system || "", page.s.path || "", page.s.key || "", page.s.title || "") } }
    readonly property real m: 16
    contentHeight: col.height + 2 * m
    clip: true

    function span(sec) {
        const h = Math.floor(sec / 3600), mi = Math.round((sec % 3600) / 60)
        return h > 0 ? h + " h " + (mi < 10 ? "0" : "") + mi + " m" : Math.max(mi, sec > 0 ? 1 : 0) + " min"
    }
    function stars(r) { const n = Math.round(r); return "★★★★★".slice(0, n) + "☆☆☆☆☆".slice(0, 5 - n) }

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: 14

        Row {
            width: parent.width
            spacing: 14
            Rectangle {
                visible: !!page.d.cover
                width: 130; height: 130
                radius: Theme.radius
                color: Theme.circle
                clip: true
                Image { anchors.fill: parent; source: page.d.cover || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
            }
            Column {
                width: parent.width - (page.d.cover ? 144 : 0)
                spacing: 5
                Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 24; font.weight: Font.DemiBold; text: page.d.name || page.s.title || "" }
                Text {
                    visible: text !== ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: Theme.muted
                    font.pixelSize: 14
                    text: [page.d.genre, page.d.developer, page.d.year].filter(x => !!x).join("  ·  ")
                }
                PillButton {
                    label: (page.d.favorite ? "♥ " : "♡ ") + Tr.t("Favorite")
                    primary: page.d.favorite === true
                    onClicked: history.toggleFavorite(page.s.key || "", page.s.title || "", page.s.system || "", page.s.path || "")
                }
                Text { visible: page.d.rating > 0; color: Theme.accent; font.pixelSize: 18; text: page.stars(page.d.rating) + "  " + page.d.rating }
            }
        }

        Rectangle {
            width: parent.width
            height: 76
            radius: Theme.radius
            color: Theme.card
            border.width: Theme.borderW
            border.color: Theme.border
            Row {
                anchors.fill: parent
                Repeater {
                    model: [
                        { k: Tr.t("Played"), v: page.span(page.d.total || 0) },
                        { k: Tr.t("Started"), v: (page.d.plays || 0) + "×" },
                        { k: Tr.t("Last played"), v: page.d.last ? new Date(page.d.last * 1000).toLocaleDateString(Qt.locale(), Locale.ShortFormat) : "–" }
                    ]
                    delegate: Column {
                        width: parent.width / 3
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; color: Theme.text; font.pixelSize: 20; font.weight: Font.Medium; text: modelData.v }
                        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.pixelSize: 12; text: modelData.k }
                    }
                }
            }
        }

        Text {
            visible: !!page.d.desc
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.text
            font.pixelSize: 15
            lineHeight: 1.15
            text: page.d.desc || ""
        }
        Text {
            readonly property bool steamGame: /^steam\/\d+$/.test(page.s.key || "") && parseInt((page.s.key || "").slice(6)) < 2147483648
            visible: !page.d.desc
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.muted
            font.pixelSize: 14
            text: (steamGame ? Tr.t("Steam has not sent this game's data yet. It needs an internet connection and shows up here after a moment.")
                             : Tr.t("ES-DE has no description for this game. Scrape it there (media and metadata) and it shows up here."))
                  + "\n\n" + (page.s.system || "?") + "  ·  " + (page.s.path || page.s.key || "?")
        }
        Flow {
            width: parent.width
            spacing: 8
            Repeater {
                model: page.d.shots || []
                delegate: Rectangle {
                    width: (col.width - 8) / 2
                    height: width * 0.6
                    radius: Theme.radius
                    color: Theme.circle
                    clip: true
                    Image { anchors.fill: parent; source: modelData; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                }
            }
        }
    }
}
