import QtQuick

// Game rules: the power profile and FPS limit (and render resolution) kept for one game, one system, for idle, or as the base for everything else.
// Reached from the Rules tile on System. The list names each game, not only its Steam id.
Flickable {
    id: page
    readonly property var rl: rules.state
    readonly property var s: nowPlaying.state
    readonly property bool inGame: s.kind === "game"
    readonly property real m: 16
    contentHeight: col.height + 2 * m
    clip: true

    function saved(key) { return key !== "" && rl.rules.some(r => r.key === key) }
    function summary(r) { return (r.profile || "–") + (r.fps ? ", " + r.fps + " FPS" : "") + (r.res ? ", " + r.res + "× " + Tr.t("render") : "") }
    function title(r) {
        return r.kind === "idle" ? Tr.t("Idle rule") : r.kind === "base" ? Tr.t("Base rule") : r.kind === "system" ? Tr.t("System") + ": " + r.name : r.name
    }

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: 14

        Chips {
            width: parent.width
            model: [{ key: "on", label: Tr.t("Apply automatically") }, { key: "off", label: Tr.t("Off") }]
            current: page.rl.enabled ? "on" : "off"
            onPicked: key => rules.setEnabled(key === "on")
        }
        Text { visible: page.rl.loaded !== ""; width: parent.width; color: Theme.accent; font.pixelSize: 13; text: Tr.t("Loaded last") + ": " + page.rl.loaded }

        Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("Save the current profile and FPS limit for") }
        Flow {
            width: parent.width
            spacing: 8
            PillButton {
                visible: page.inGame && page.rl.gameKey !== ""
                label: (page.saved(page.rl.gameKey) ? "✓ " : "") + (page.s.title || Tr.t("Game rule"))
                onClicked: rules.toggle("game")
            }
            PillButton {
                visible: page.inGame && page.rl.systemKey !== ""
                label: (page.saved(page.rl.systemKey) ? "✓ " : "") + Tr.t("System rule")
                onClicked: rules.toggle("system")
            }
            PillButton { label: (page.saved(page.rl.idleKey) ? "✓ " : "") + Tr.t("Idle rule"); onClicked: rules.toggle("idle") }
            PillButton { label: (page.saved(page.rl.baseKey) ? "✓ " : "") + Tr.t("Base rule"); onClicked: rules.toggle("base") }
            PillButton { visible: page.inGame && page.rl.resOk; label: Tr.t("Resolution"); onClicked: rules.cycleRes() }
        }
        Text {
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.muted
            font.pixelSize: 13
            text: Tr.t("The game and system buttons appear while a game is in front. Base applies to every game without a rule of its own, Idle when no game runs any more.")
        }

        Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("Saved rules") }
        Text { visible: page.rl.rules.length === 0; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14; text: Tr.t("Nothing saved yet.") }
        Repeater {
            model: page.rl.rules
            delegate: Rectangle {
                width: col.width
                height: 58
                radius: Theme.radius
                color: Theme.card
                border.width: Theme.borderW
                border.color: Theme.border
                Column {
                    anchors { left: parent.left; leftMargin: 14; right: del.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 16; text: page.title(modelData) }
                    Text { width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 13; text: page.summary(modelData) }
                }
                PillButton { id: del; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } label: "✕"; onClicked: rules.remove(modelData.key) }
            }
        }
    }
}
