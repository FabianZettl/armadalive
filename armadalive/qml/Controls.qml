import QtQuick

// Controls: the Trackpad and the Lupe, one tab each.
Item {
    id: page
    property string tab: "trackpad"
    Chips {
        id: tabs
        x: 14; y: 6
        model: [{ key: "trackpad", label: Tr.t("Trackpad") }, { key: "lupe", label: Tr.t("Lupe") }]
        current: page.tab
        onPicked: key => page.tab = key
    }
    Loader {
        anchors { top: tabs.bottom; topMargin: 8; left: parent.left; right: parent.right; bottom: parent.bottom }
        source: page.tab === "lupe" ? "Lupe.qml" : "Trackpad.qml"
    }
}
