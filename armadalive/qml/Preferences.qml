import QtQuick

// App settings: language, look, updates, and who made this.
Flickable {
    id: page
    readonly property var look: ui.state
    readonly property var up: updater.state
    readonly property var adm: admin.state
    readonly property var accents: ["A97BE0", "68E1FB", "2EE59D", "D4AF37", "FF9F0A", "FF453A", "FF3DF2", "1A9FFF"]
    readonly property real m: 10
    contentHeight: col.height + 2 * m
    clip: true

    component Card: Rectangle {
        default property alias content: inner.data
        width: parent.width
        height: inner.height + 28
        radius: Theme.radius
        color: Theme.card
        Column { id: inner; x: 14; y: 14; width: parent.width - 28; spacing: 10 }
    }
    component Label: Text { color: Theme.muted; font.pixelSize: 14; width: parent.width; wrapMode: Text.WordWrap }
    component Setup: Item {
        id: row
        property string title
        property string hint
        property string status
        property string button
        property bool done: false
        property bool busy: false
        signal triggered()
        height: Math.max(text.height, 42) + 4
        Column {
            id: text
            anchors { left: parent.left; right: btn.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 2
            Text { color: Theme.text; font.pixelSize: 15; text: row.title + "  ·  " + (row.busy ? Tr.t("Working…") : row.status) }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; text: row.hint }
        }
        PillButton {
            id: btn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            label: row.button
            primary: !row.done
            enabled: !row.done && !row.busy
            onClicked: row.triggered()
        }
    }
    component Body: Text { color: Theme.text; font.pixelSize: 15; width: parent.width; wrapMode: Text.WordWrap }

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: page.m

        Card {
            Label { text: Tr.t("Language") }
            Chips {
                width: parent.width
                model: [{ key: "en", label: "English" }, { key: "de", label: "Deutsch" }]
                current: page.look.lang
                onPicked: key => ui.setLang(key)
            }
            Label { text: Tr.t("Logo animation") }
            Chips {
                width: parent.width
                model: [{ key: "on", label: Tr.t("On") }, { key: "off", label: Tr.t("Off") }]
                current: page.look.animate === false ? "off" : "on"
                onPicked: key => ui.setAnimate(key === "on")
            }
            Label { text: Tr.t("Appearance") }
            Chips {
                width: parent.width
                model: Object.keys(Theme.themes).map(k => ({ key: k, label: Theme.themes[k].name }))
                current: page.look.theme
                onPicked: key => ui.setTheme(key)
            }
            Row {
                spacing: 10
                Repeater {
                    model: page.accents
                    delegate: Rectangle {
                        width: 38; height: 38; radius: 19
                        color: "#" + modelData
                        border.width: Theme.accent.toString().toUpperCase() === ("#" + modelData) ? 3 : 1
                        border.color: Theme.accent.toString().toUpperCase() === ("#" + modelData) ? Theme.text : Theme.border
                        MouseArea { anchors.fill: parent; onClicked: ui.setAccent(modelData) }
                    }
                }
            }
        }

        Card {
            Label { text: Tr.t("Updates") }
            Body { text: "ArmadaLive " + page.up.version + (page.up.latest ? "  →  " + page.up.latest : "") }
            Body {
                visible: page.up.status === "norepo"
                color: Theme.muted
                text: Tr.t("Updates need the GitHub repository, which does not exist yet.")
            }
            Body {
                visible: ["checking", "uptodate", "available", "installing", "installed", "error"].indexOf(page.up.status) >= 0
                color: page.up.status === "error" ? Theme.hot : (page.up.status === "uptodate" ? Theme.muted : Theme.text)
                text: ({ checking: Tr.t("Checking…"), uptodate: Tr.t("Up to date"), available: Tr.t("Update available"),
                         installing: Tr.t("Installing…"), installed: Tr.t("Installed. The app restarts in a moment."),
                         error: page.up.message })[page.up.status] || ""
            }
            Row {
                spacing: 10
                PillButton {
                    label: Tr.t("Check for updates")
                    enabled: page.up.status !== "norepo" && page.up.status !== "checking" && page.up.status !== "installing"
                    onClicked: updater.check()
                }
                PillButton {
                    visible: page.up.status === "available"
                    primary: true
                    label: Tr.t("Install update")
                    onClicked: updater.install()
                }
            }
        }

        Card {
            Label { text: Tr.t("Setup") }
            Setup {
                width: parent.width
                title: Tr.t("Root helper")
                hint: Tr.t("Fan curves, profile tuning, stick LEDs, Clear RAM")
                status: ({ ok: Tr.t("Installed"), outdated: Tr.t("Needs update"), missing: Tr.t("Not installed") })[page.adm.helper] || ""
                done: page.adm.helper === "ok"
                button: page.adm.helper === "outdated" ? Tr.t("Update") : Tr.t("Install")
                busy: page.adm.busy === "helper"
                onTriggered: Auth.ask = "helper"
            }
            Setup {
                width: parent.width
                title: Tr.t("AYN button")
                hint: Tr.t("Opens ArmadaLive. Restarts InputPlumber, controllers reconnect briefly.")
                status: page.adm.ayn ? Tr.t("Active") : Tr.t("Not set up")
                done: page.adm.ayn
                button: Tr.t("Set up")
                busy: page.adm.busy === "ayn"
                onTriggered: Auth.ask = "ayn"
            }
            Body {
                visible: page.adm.message !== ""
                color: Theme.hot
                text: page.adm.message === "wrong password" ? Tr.t("Wrong password.") : page.adm.message
            }
        }

        Card {
            Label { text: Tr.t("About") }
            Body { text: "ArmadaLive " + page.up.version }
            Body { text: "© 2026 Fabian Zettl, Stuttgart" }
            Row {
                spacing: 10
                PillButton {
                    label: page.up.repoUrl !== "" ? Tr.t("Source code") + " · GitHub" : Tr.t("Repository coming soon")
                    enabled: page.up.repoUrl !== ""
                    onClicked: updater.openRepo()
                }
            }
            Label { text: Tr.t("AI disclosure") }
            Body {
                font.pixelSize: 14
                text: Tr.t("ArmadaLive was developed with the help of AI (Claude Code by Anthropic). A large part of the code and the texts was written by the AI. Mistakes are possible; use at your own risk.")
            }
        }
    }
}
