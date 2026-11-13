import QtQuick

// App settings: a menu on the left (the burger button folds it to icons) and the chosen section on the right.
Item {
    id: page
    readonly property var look: ui.state
    readonly property var up: updater.state
    readonly property var adm: admin.state
    readonly property var cc: controls.state
    readonly property var bat: battery.state
    readonly property var bk: backup.state
    readonly property var accents: ["A97BE0", "68E1FB", "2EE59D", "D4AF37", "FF9F0A", "FF453A", "FF3DF2", "1A9FFF"]
    readonly property real m: 16
    property string section: "general"
    property bool menuOpen: true
    readonly property var sections: [
        { id: "general", label: Tr.t("General"), icon: "gear" }, { id: "appearance", label: Tr.t("Appearance"), icon: "sun" },
        { id: "power", label: Tr.t("Battery and heat"), icon: "gauge" }, { id: "updates", label: Tr.t("Updates"), icon: "add" },
        { id: "setup", label: Tr.t("Setup"), icon: "perf" }, { id: "backup", label: Tr.t("Backup"), icon: "book" },
        { id: "about", label: Tr.t("About"), icon: "info" }
    ]

    component Card: Rectangle {
        property string sec: ""
        visible: page.section === sec
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

    Rectangle {
        id: menu
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: page.menuOpen ? 210 : 64
        color: Theme.card
        clip: true
        Behavior on width { NumberAnimation { duration: Theme.dur(160) } }
        Item {
            id: burger
            x: 0; y: 0; width: 64; height: 56
            Text { anchors.centerIn: parent; color: Theme.text; font.pixelSize: 26; text: "\u2630" }
            MouseArea { anchors.fill: parent; onClicked: page.menuOpen = !page.menuOpen }
        }
        Column {
            anchors { top: burger.bottom; left: parent.left; right: parent.right }
            Repeater {
                model: page.sections
                delegate: Item {
                    width: menu.width
                    height: 54
                    Rectangle {
                        anchors { fill: parent; leftMargin: 6; rightMargin: 6; topMargin: 2; bottomMargin: 2 }
                        radius: Theme.radius
                        color: page.section === modelData.id ? Theme.accentSoft : "transparent"
                    }
                    Icon { x: 18; anchors.verticalCenter: parent.verticalCenter; width: 28; height: 28; name: modelData.icon; color: page.section === modelData.id ? Theme.accent : Theme.text }
                    Text {
                        x: 60; width: parent.width - 66
                        anchors.verticalCenter: parent.verticalCenter
                        visible: page.menuOpen
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: 16
                        text: modelData.label
                    }
                    MouseArea { anchors.fill: parent; onClicked: { page.section = modelData.id; flick.contentY = 0 } }
                }
            }
        }
    }
    Flickable {
        id: flick
        anchors { left: menu.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        contentHeight: col.height + 2 * page.m
        clip: true
    Column {
        id: col
        x: page.m; y: page.m
        width: flick.width - 2 * page.m
        spacing: page.m

        Card {
            sec: "general"
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
            sec: "appearance"
            Title { text: Tr.t("Appearance") }
            // the group's tabs, then its themes as small previews: the theme's own background, a card and its accent, and its name in its own colours
            ThemePicker { width: parent.width }
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
            sec: "updates"
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
            sec: "setup"
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
            sec: "setup"
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
            PillButton { label: Tr.t("Run setup again"); onClicked: ui.setOnboarded(false) }
            Body {
                visible: page.adm.message !== ""
                color: Theme.hot
                text: page.adm.message === "wrong password" ? Tr.t("Wrong password.") : page.adm.message
            }
        }

        Card {
            sec: "power"
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
            Body { visible: page.bat.refused === true; color: Theme.muted; font.pixelSize: 13
                   text: Tr.t("This battery does not accept a charge limit (its firmware refuses it), so there is none to set.") }
            Body { visible: page.bat.error !== ""; color: Theme.hot; font.pixelSize: 13; text: page.bat.error }
        }

        Card {
            sec: "power"
            Label { text: Tr.t("Wi-Fi saver") }
            Chips {
                width: parent.width
                model: [{ key: "on", label: Tr.t("On") }, { key: "off", label: Tr.t("Off") }]
                current: page.cc.wifips === true ? "on" : "off"
                onPicked: key => { if ((key === "on") !== (page.cc.wifips === true)) controls.toggleWifiSaver() }
            }
            Label { text: Tr.t("Airplane") }
            Chips {
                width: parent.width
                model: [{ key: "on", label: Tr.t("On") }, { key: "off", label: Tr.t("Off") }]
                current: page.cc.airplane === true ? "on" : "off"
                onPicked: key => { if ((key === "on") !== (page.cc.airplane === true)) controls.toggleAirplane() }
            }
        }

        Card {
            sec: "backup"
            Label { text: Tr.t("Backup") }
            Body { color: Theme.muted; font.pixelSize: 13; text: Tr.t("Settings, game rules, tile order, apps, folders and play time in one file:") + " " + page.bk.path }
            Row {
                spacing: 10
                PillButton { label: Tr.t("Save backup"); onClicked: backup.save() }
                PillButton { label: Tr.t("Restore"); enabled: page.bk.exists; onClicked: backup.restore() }
            }
            Body { visible: page.bk.message !== ""; color: Theme.muted; font.pixelSize: 13
                   text: page.bk.message === "saved" ? Tr.t("Saved.") : (page.bk.message === "restored" ? Tr.t("Restored. The app restarts.") : page.bk.message) }
        }

        Card {
            sec: "about"
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
}
