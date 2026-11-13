import QtQuick

// The theme groups as tabs, then the themes of one group as small previews: the theme's own background, a card and its accent, and its name in its own colours.
Column {
    id: picker
    property string tab: ""   // the group shown; empty = the current theme's own
    spacing: 12
    Chips {
        width: parent.width
        model: Theme.themeGroups.map(g => ({ key: g.id, label: Tr.t(g.short || g.name) }))
        current: picker.tab || (Theme.themes[ui.state.theme] || ({})).group || "general"
        onPicked: key => picker.tab = key
    }
    Flow {
        id: swatches
        width: parent.width
        spacing: 8
        readonly property int cols: width > 560 ? 4 : 3
        Repeater {
            model: Object.keys(Theme.themes).filter(k => (Theme.themes[k].group || "general") === (picker.tab || (Theme.themes[ui.state.theme] || ({})).group || "general"))
            delegate: Rectangle {
                readonly property var th: Theme.themes[modelData]
                readonly property bool on: ui.state.theme === modelData
                width: Math.floor((swatches.width - (swatches.cols - 1) * swatches.spacing) / swatches.cols)
                height: 62
                radius: Theme.radiusFor((Theme.styles[modelData] || ({})).shape || "round")
                color: th.bg
                border.width: on ? 3 : ((Theme.styles[modelData] || ({})).border || 1)
                border.color: on ? th.accent : th.border
                Rectangle {
                    id: chip
                    x: 10; y: 10; width: parent.width - 20; height: 18; radius: 9
                    color: th.card
                    Rectangle { x: 4; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: th.accent }
                    Rectangle { x: 18; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 24; height: 4; radius: 2; color: th.circle }
                }
                Text {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 9 }
                    elide: Text.ElideRight
                    color: th.text
                    font.pixelSize: 13
                    font.weight: on ? Font.DemiBold : Font.Normal
                    text: th.name
                }
                MouseArea { anchors.fill: parent; onClicked: ui.setTheme(modelData) }
            }
        }
    }
}
