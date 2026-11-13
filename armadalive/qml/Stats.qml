import QtQuick

// A week of play: how long each day, and what was played most. From the history of what ran on the main screen (history.py). Reached from the Playtime tile on System.
Flickable {
    id: page
    property var week: history.week(7)
    property var leaders: history.top(7, 5)
    property int total: history.totalSeconds(7)
    readonly property real m: 16
    readonly property real peak: Math.max(1, Math.max.apply(null, week.map(d => d.seconds)))
    contentHeight: col.height + 2 * m
    clip: true
    Connections { target: history; function onChanged() { page.week = history.week(7); page.leaders = history.top(7, 5); page.total = history.totalSeconds(7) } }

    function span(sec) {
        const h = Math.floor(sec / 3600), mi = Math.round((sec % 3600) / 60)
        return h > 0 ? h + " h " + (mi < 10 ? "0" : "") + mi + " m" : mi + " min"
    }

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: 14
        Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("This week") }
        Text { color: Theme.text; font.pixelSize: 34; font.weight: Font.Medium; text: page.span(page.total) }

        Rectangle {
            width: parent.width
            height: 190
            radius: Theme.radius
            color: Theme.card
            border.width: Theme.borderW
            border.color: Theme.border
            Row {
                anchors { fill: parent; margins: 14 }
                spacing: 8
                Repeater {
                    model: page.week
                    delegate: Item {
                        width: (parent.width - 6 * 8) / 7
                        height: parent.height
                        Text {
                            anchors { horizontalCenter: parent.horizontalCenter; bottom: bar.top; bottomMargin: 3 }
                            visible: modelData.seconds > 0
                            color: Theme.muted
                            font.pixelSize: 11
                            text: page.span(modelData.seconds).replace(" h ", "h ").replace(" m", "").replace(" min", "m")
                        }
                        Rectangle {
                            id: bar
                            anchors { horizontalCenter: parent.horizontalCenter; bottom: label.top; bottomMargin: 6 }
                            width: parent.width * 0.7
                            height: Math.max(3, (parent.height - 44) * modelData.seconds / page.peak)
                            radius: Theme.pill(Math.min(width, height))
                            color: index === page.week.length - 1 ? Theme.accent : Theme.accentSoft
                            Behavior on height { NumberAnimation { duration: Theme.dur(300); easing.type: Theme.ease } }
                        }
                        Text { id: label; anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom } color: Theme.muted; font.pixelSize: 12; text: modelData.day }
                    }
                }
            }
        }

        Text { visible: page.leaders.length > 0; color: Theme.muted; font.pixelSize: 14; text: Tr.t("Most played") }
        Repeater {
            model: page.leaders
            delegate: Rectangle {
                width: col.width
                height: 52
                radius: Theme.radius
                color: Theme.card
                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    width: parent.width * modelData.seconds / Math.max(1, page.leaders[0].seconds)
                    radius: parent.radius
                    color: Theme.accentSoft
                }
                Text { anchors { left: parent.left; leftMargin: 14; right: time.left; rightMargin: 8; verticalCenter: parent.verticalCenter } elide: Text.ElideRight; color: Theme.text; font.pixelSize: 16; text: modelData.title }
                Text { id: time; anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter } color: Theme.muted; font.pixelSize: 14; text: page.span(modelData.seconds) }
            }
        }
        Text {
            visible: page.leaders.length === 0
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.muted
            font.pixelSize: 15
            text: Tr.t("Nothing played this week yet. ArmadaLive counts every game that runs on the main screen from now on.")
        }
    }
}
