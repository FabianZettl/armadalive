import QtQuick

// App settings: language, look, updates, and who made this.
Flickable {
    id: page
    readonly property var look: ui.state
    readonly property var up: updater.state
    readonly property var adm: admin.state
    readonly property var rl: rules.state
    readonly property var bat: battery.state
    readonly property var bk: backup.state
    readonly property var accents: ["A97BE0", "68E1FB", "2EE59D", "D4AF37", "FF9F0A", "FF453A", "FF3DF2", "1A9FFF"]
    readonly property real m: 16
    contentHeight: col.height + 2 * m
    clip: true

    component Card: Rectangle {
        default property alias content: inner.data
        width: parent.width
        height: inner.height + 36
        radius: Theme.radius + 4
        color: Theme.card
        Column { id: inner; x: 18; y: 18; width: parent.width - 36; spacing: 12 }
    }
    component Title: Text { color: Theme.muted; font.pixelSize: 15; font.letterSpacing: 0.6; font.capitalization: Font.AllUppercase; width: parent.width }
    // one row per setting: its name on the left, a single button on the right that flips it (like the tiles on the System page)
    component Setting: Item {
        id: st
        property string title
        property string hint
        property string label
        property bool on: false
        property bool last: false
        signal toggled()
        width: parent.width
        height: 62
        Column {
            anchors { left: parent.left; right: btn.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 17; text: st.title }
            Text { visible: st.hint !== ""; width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 12; text: st.hint }
        }
        Rectangle {
            id: btn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: Math.max(96, txt.width + 36); height: 44; radius: 22
            color: st.on ? Theme.accentSoft : Theme.circle
            border.width: 1.5
            border.color: st.on ? Theme.accent : Theme.border
            scale: tap.pressed ? 0.95 : 1
            Text { id: txt; anchors.centerIn: parent; color: st.on ? Theme.accent : Theme.muted; font.pixelSize: 16; font.weight: Font.Medium; text: st.label }
            MouseArea { id: tap; anchors.fill: parent; onClicked: st.toggled() }
        }
        Rectangle {
            visible: !st.last
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            color: Theme.border
        }
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
            Title { text: Tr.t("General") }
            Column {
                width: parent.width
                Setting {
                    title: Tr.t("Language")
                    label: page.look.lang === "de" ? "Deutsch" : "English"
                    on: true
                    onToggled: ui.setLang(page.look.lang === "de" ? "en" : "de")
                }
                Setting {
                    title: Tr.t("Logo animation")
                    label: page.look.animate === false ? Tr.t("Off") : Tr.t("On")
                    on: page.look.animate !== false
                    onToggled: ui.setAnimate(page.look.animate === false)
                }
                Setting {
                    title: Tr.t("Dim after 10 s")
                    label: page.look.dim === false ? Tr.t("Off") : Tr.t("On")
                    on: page.look.dim !== false
                    onToggled: ui.setDim(page.look.dim === false)
                }
                Setting {
                    title: Tr.t("Apps page")
                    hint: Tr.t("The app grid in the bar")
                    label: page.look.apps === false ? Tr.t("Off") : Tr.t("On")
                    on: page.look.apps !== false
                    onToggled: ui.setApps(page.look.apps === false)
                }
                Setting {
                    title: Tr.t("Close game")
                    hint: Tr.t("Hold Start + Select for 2 s")
                    label: page.look.close === false ? Tr.t("Off") : Tr.t("On")
                    on: page.look.close !== false
                    last: true
                    onToggled: ui.setClose(page.look.close === false)
                }
            }
        }

        Card {
            Title { text: Tr.t("Appearance") }
            Chips {
                width: parent.width
                model: Object.keys(Theme.themes).map(k => ({ key: k, label: Theme.themes[k].name }))
                current: page.look.theme
                onPicked: key => ui.setTheme(key)
            }
            Row {
                spacing: 12
                Repeater {
                    model: page.accents
                    delegate: Rectangle {
                        width: 42; height: 42; radius: 21
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
            Label { text: Tr.t("Health check") }
            Repeater {
                model: health.checks
                delegate: Column {
                    width: parent.width
                    spacing: 2
                    Row {
                        spacing: 10
                        Rectangle { width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: modelData.ok ? Theme.accent : Theme.hot }
                        Text { color: Theme.text; font.pixelSize: 15; text: ({ hooks: Tr.t("ES-DE hooks"), events: Tr.t("ES-DE event scripts"), media: Tr.t("ES-DE media"), steam: Tr.t("Steam Big Picture link"), gamescope: Tr.t("FPS source") })[modelData.id] }
                    }
                    Text { visible: !modelData.ok; x: 22; width: parent.width - 22; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; text: Tr.t(modelData.hint) }
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
            Label { text: Tr.t("Game rules") }
            Chips {
                width: parent.width
                model: [{ key: "on", label: Tr.t("Apply automatically") }, { key: "off", label: Tr.t("Off") }]
                current: page.rl.enabled ? "on" : "off"
                onPicked: key => rules.setEnabled(key === "on")
            }
            Body {
                visible: page.rl.rules.length === 0
                color: Theme.muted
                font.pixelSize: 13
                text: Tr.t("While a game is in front, tap Game rule or System rule on the System page to save its power profile and FPS limit here.")
            }
            Repeater {
                model: page.rl.rules
                delegate: Item {
                    width: parent.width
                    height: 44
                    Text {
                        anchors { left: parent.left; right: del.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: 14
                        text: (modelData.key.indexOf("system:") === 0 ? Tr.t("System") + " " : "") + modelData.key.replace(/^(game|system):/, "") + "  ·  " + (modelData.profile || "–") + (modelData.fps ? ", " + modelData.fps + " FPS" : "") + (modelData.res ? ", " + modelData.res + "×" : "")
                    }
                    PillButton { id: del; anchors { right: parent.right; verticalCenter: parent.verticalCenter } label: "✕"; onClicked: rules.remove(modelData.key) }
                }
            }
        }

        Card {
            Label { text: Tr.t("Battery and heat") }
            Label { text: Tr.t("Warn when it gets hot") }
            Chips {
                width: parent.width
                model: [{ key: "0", label: Tr.t("Off") }, { key: "80", label: "80 °C" }, { key: "85", label: "85 °C" }, { key: "90", label: "90 °C" }]
                current: String(page.look.heat === undefined ? 85 : page.look.heat)
                onPicked: key => ui.setHeat(parseInt(key))
            }
            Label { text: Tr.t("Warn when the battery drops to") }
            Chips {
                width: parent.width
                model: [{ key: "0", label: Tr.t("Off") }, { key: "15", label: "15 %" }, { key: "20", label: "20 %" }, { key: "30", label: "30 %" }]
                current: String(page.bat.warn)
                onPicked: key => battery.setWarn(parseInt(key))
            }
            Label { visible: page.bat.supported; text: Tr.t("Charge only up to (needs the root helper)") }
            Chips {
                visible: page.bat.supported
                width: parent.width
                model: [{ key: "100", label: "100 %" }, { key: "90", label: "90 %" }, { key: "80", label: "80 %" }]
                current: String(page.bat.limit)
                onPicked: key => battery.setLimit(parseInt(key))
            }
            Body { visible: page.bat.error !== ""; color: Theme.hot; font.pixelSize: 13; text: page.bat.error }
        }

        Card {
            Label { text: Tr.t("Backup") }
            Body { color: Theme.muted; font.pixelSize: 13; text: Tr.t("Settings, game rules and tile order in one file:") + " " + page.bk.path }
            Row {
                spacing: 10
                PillButton { label: Tr.t("Save backup"); onClicked: backup.save() }
                PillButton { label: Tr.t("Restore"); enabled: page.bk.exists; onClicked: backup.restore() }
            }
            Body { visible: page.bk.message !== ""; color: Theme.muted; font.pixelSize: 13
                   text: page.bk.message === "saved" ? Tr.t("Saved.") : (page.bk.message === "restored" ? Tr.t("Restored. The app restarts.") : page.bk.message) }
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
