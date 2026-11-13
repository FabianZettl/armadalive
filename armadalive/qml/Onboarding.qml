import QtQuick

// The first-run setup: what ArmadaLive needs and why, one step at a time. Every step except the first can be skipped, and says what is lost then.
// The steps: root helper, AYN button, ES-DE, Steam, a theme, the first eight tiles, a summary. Shown on a fresh install, again from Settings > Setup.
Rectangle {
    id: ob
    color: Theme.bg
    property int step: 0
    property bool tilesTouched: false
    property string tileNote: ""
    property var picked: ["perf", "fan", "led", "brightness", "wifi", "rules", "graphs", "prefs"]
    readonly property var adm: admin.state
    function check(id) { const c = (health.checks || []).find(x => x.id === id); return c ? c.ok === true : false }
    // the quick tiles of the System page (the same ids as there), for the "first eight" choice
    readonly property var tileChoices: [
        { id: "perf", icon: "perf", label: Tr.t("Performance") }, { id: "fan", icon: "fan", label: Tr.t("Fan") },
        { id: "led", icon: "led", label: Tr.t("Stick LEDs") }, { id: "brightness", icon: "sun", label: Tr.t("Brightness") },
        { id: "wifi", icon: "wifi", label: Tr.t("Wi-Fi") }, { id: "rules", icon: "star", label: Tr.t("Rules") },
        { id: "graphs", icon: "graph", label: Tr.t("Graphs") }, { id: "prefs", icon: "gear", label: Tr.t("Settings") },
        { id: "clean", icon: "clean", label: Tr.t("Clear RAM") }, { id: "framegen", icon: "perf", label: Tr.t("Frame gen") },
        { id: "tailscale", icon: "vpn", label: "Tailscale" }, { id: "bluetooth", icon: "bluetooth", label: "Bluetooth" },
        { id: "sound", icon: "sound", label: Tr.t("Sound") }, { id: "shot", icon: "shot", label: "Screenshot" },
        { id: "tuning", icon: "edit", label: Tr.t("Tuning") }, { id: "tasks", icon: "apps", label: Tr.t("Tasks") },
        { id: "stats", icon: "graph", label: Tr.t("Playtime") }, { id: "screenoff", icon: "power", label: Tr.t("Screen off") },
        { id: "keyboard", icon: "edit", label: Tr.t("Keyboard") }, { id: "steam", icon: "add", label: Tr.t("Add to Steam") }
    ]
    // ok: true/false shows a status line and, when false, what is lost without it; undefined: nothing to check
    readonly property var steps: [
        { id: "welcome", title: Tr.t("Welcome to ArmadaLive"),
          why: Tr.t("This short setup checks what ArmadaLive needs and lets you pick a look and your quick tiles. You can skip every step and change everything later in Settings.") },
        { id: "helper", title: Tr.t("Root helper"), ok: adm.helper === "ok",
          why: Tr.t("A small program that may change the power profile, fan curves and stick LEDs, clear the RAM and set a charge limit. It needs your password once."),
          lose: Tr.t("Without it: no profile tuning, no fan curves, no LED control and no Clear RAM. Everything else works.") },
        { id: "ayn", title: Tr.t("AYN button"), ok: adm.ayn === true,
          why: Tr.t("A tap on the AYN button brings ArmadaLive up or sends it away. Setting it up restarts InputPlumber, so the controllers reconnect for a moment."),
          lose: Tr.t("Without it: open ArmadaLive from the taskbar or the app launcher instead.") },
        { id: "esde", title: "ES-DE", ok: check("hooks") && check("events"),
          why: Tr.t("ArmadaLive shows the game you are in (logo, background, manual) from ES-DE. For that, ES-DE needs two settings: START, Other Settings, then turn on Custom Event Scripts and Browsing Custom Event Scripts. Scrape the media there too."),
          lose: Tr.t("Without it: the Game page stays empty for ES-DE games, and the Info page has no pictures.") },
        { id: "steam", title: "Steam", ok: check("steam"),
          why: Tr.t("To show the game you highlight in Steam's Big Picture, ArmadaLive talks to Steam's remote debugging. Turn on CEF Remote Debugging in Steam's developer settings, or install Decky Loader, then restart Steam."),
          lose: Tr.t("Without it: Steam games show only while they run, not while you browse the library, and ES-DE games cannot be started from the Apps page.") },
        { id: "theme", title: Tr.t("Pick a look"),
          why: Tr.t("Themes change colours, shapes and fonts, and the stick LEDs follow the accent. You can change it any time in Settings, Appearance."),
          lose: Tr.t("Skipping keeps the current look.") },
        { id: "tiles", title: Tr.t("Your first eight tiles"),
          why: Tr.t("These are the quick buttons on the first page of the System page. Pick up to eight; the others follow on the next pages. You can move them later by pressing a tile for a moment."),
          lose: Tr.t("Skipping keeps the standard set.") },
        { id: "done", title: Tr.t("All set"),
          why: Tr.t("This is where things stand. Anything marked red can be set up later: Settings, Setup.") }
    ]
    readonly property var cur: steps[step]
    readonly property bool last: step === steps.length - 1
    readonly property bool skipping: cur.ok === false || (cur.id === "theme") || (cur.id === "tiles" && !tilesTouched)
    function toggleTile(id) {
        tileNote = ""
        const i = picked.indexOf(id)
        if (i >= 0) picked = picked.filter(x => x !== id)
        else if (picked.length < 8) picked = picked.concat([id])
        else tileNote = Tr.t("Eight at most: take one away first.")
        tilesTouched = true
    }
    function next() {
        if (cur.id === "tiles" && tilesTouched) tileStore.setOrder(picked)
        if (last) { ui.setOnboarded(true); step = 0; tilesTouched = false; return }
        step++
    }

    MouseArea { anchors.fill: parent }   // swallow touches so the page below stays untouched

    Item {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
        height: 52
        Text { anchors { left: parent.left; verticalCenter: parent.verticalCenter } color: Theme.text; font.pixelSize: 26; font.weight: Font.DemiBold; text: ob.cur.title }
        Text { anchors { right: parent.right; verticalCenter: parent.verticalCenter } color: Theme.muted; font.pixelSize: 14; text: (ob.step + 1) + " / " + ob.steps.length }
    }

    Flickable {
        id: body
        anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: foot.top; leftMargin: 20; rightMargin: 20 }
        contentHeight: col.height + 12
        clip: true
        Column {
            id: col
            width: body.width
            spacing: 14
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 17; lineHeight: 1.1; text: ob.cur.why }
            Row {
                visible: ob.cur.ok !== undefined && ob.cur.id !== "done"
                spacing: 10
                Rectangle { width: 14; height: 14; radius: 7; anchors.verticalCenter: parent.verticalCenter; color: ob.cur.ok ? Theme.accent : Theme.hot }
                Text { color: ob.cur.ok ? Theme.accent : Theme.hot; font.pixelSize: 16; text: ob.cur.ok ? Tr.t("Ready") : Tr.t("Not set up yet") }
            }
            Text { visible: ob.cur.ok === false; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 15; text: ob.cur.lose || "" }
            Text { visible: ob.cur.id === "theme" || ob.cur.id === "tiles"; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14; text: ob.cur.lose || "" }

            // the actions of the step
            Flow {
                width: parent.width
                spacing: 10
                PillButton { visible: ob.cur.id === "helper" && ob.adm.helper !== "ok"; primary: true; label: ob.adm.helper === "outdated" ? Tr.t("Update") : Tr.t("Install"); onClicked: Auth.ask = "helper" }
                PillButton { visible: ob.cur.id === "ayn" && ob.adm.ayn !== true; primary: true; label: Tr.t("Set up"); onClicked: Auth.ask = "ayn" }
                PillButton { visible: ob.cur.id === "esde" && onboarding.esdeFound; primary: true; label: Tr.t("Open ES-DE"); onClicked: onboarding.openEsde() }
                Text { visible: ob.cur.id === "esde" && !onboarding.esdeFound; width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14; text: Tr.t("ES-DE was not found in ~/Applications. Install it first.") }
            }
            Text { visible: ob.adm.message !== "" && (ob.cur.id === "helper" || ob.cur.id === "ayn"); width: parent.width; wrapMode: Text.WordWrap; color: Theme.hot; font.pixelSize: 14
                   text: ob.adm.message === "wrong password" ? Tr.t("Wrong password.") : ob.adm.message }

            // ES-DE and the summary: the checks, each with the hint that fixes it
            Column {
                visible: ob.cur.id === "esde" || ob.cur.id === "done"
                width: parent.width
                spacing: 8
                Repeater {
                    model: ob.cur.id === "done" ? [{ id: "helper", ok: ob.adm.helper === "ok" }, { id: "ayn", ok: ob.adm.ayn === true }].concat(health.checks || []) : (health.checks || []).filter(c => c.id === "hooks" || c.id === "events" || c.id === "media")
                    delegate: Column {
                        width: parent.width
                        spacing: 2
                        Row {
                            spacing: 10
                            Rectangle { width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: modelData.ok ? Theme.accent : Theme.hot }
                            Text { color: Theme.text; font.pixelSize: 15
                                   text: ({ helper: Tr.t("Root helper"), ayn: Tr.t("AYN button"), hooks: Tr.t("ES-DE hooks"), events: Tr.t("ES-DE event scripts"), media: Tr.t("ES-DE media"), steam: Tr.t("Steam Big Picture link"), gamescope: Tr.t("FPS source") })[modelData.id] }
                        }
                        Text { visible: !modelData.ok && modelData.hint !== undefined; x: 22; width: parent.width - 22; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; text: Tr.t(modelData.hint || "") }
                    }
                }
            }

            ThemePicker { visible: ob.cur.id === "theme"; width: parent.width }

            Flow {
                visible: ob.cur.id === "tiles"
                width: parent.width
                spacing: 8
                Repeater {
                    model: ob.tileChoices
                    delegate: Rectangle {
                        readonly property int at: ob.picked.indexOf(modelData.id)
                        width: (col.width - 16) / 3
                        height: 52
                        radius: Theme.radius
                        color: at >= 0 ? Theme.accentSoft : Theme.card
                        border.width: Theme.borderW
                        border.color: at >= 0 ? Theme.accent : Theme.border
                        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 26; height: 26; name: modelData.icon; color: at >= 0 ? Theme.accent : Theme.text }
                        Text { x: 44; width: parent.width - 80; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 14; text: modelData.label }
                        Text { visible: at >= 0; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } color: Theme.accent; font.pixelSize: 16; font.weight: Font.DemiBold; text: at + 1 }
                        MouseArea { anchors.fill: parent; onClicked: ob.toggleTile(modelData.id) }
                    }
                }
            }
            Text { visible: ob.cur.id === "tiles"; width: parent.width; wrapMode: Text.WordWrap; color: ob.tileNote !== "" ? Theme.hot : Theme.muted; font.pixelSize: 14
                   text: ob.tileNote !== "" ? ob.tileNote : ob.picked.length + " / 8" }
        }
    }

    Item {
        id: foot
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 20 }
        height: 56
        PillButton { visible: ob.step > 0; anchors { left: parent.left; verticalCenter: parent.verticalCenter } label: Tr.t("Back"); onClicked: ob.step-- }
        PillButton {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            primary: !ob.skipping
            label: ob.last ? Tr.t("Finish") : (ob.cur.id === "welcome" ? Tr.t("Start") : (ob.skipping ? Tr.t("Skip") : Tr.t("Next")))
            onClicked: ob.next()
        }
    }
}
