import QtQuick
import QtQuick.Controls

// Power-profile editor: governor, underclock, GPU limits and fan curves. Reached from the Tuning tile on the dashboard.
Flickable {
    id: page
    readonly property var d: settings.data
    property string sel: "balanced"
    readonly property var prof: (d.profiles || []).find(p => p.id === sel)
    readonly property var curve: prof ? (d.curves || []).find(c => c.id === prof.fanCurve) : undefined
    readonly property var rgb: d.rgb || ({})
    readonly property var swatches: ["FFFFFF", "1A9FFF", "34C759", "FF9F0A", "FF453A", "BF5AF2"]
    property string notice: ""

    contentHeight: col.height + 28
    clip: true
    Component.onCompleted: sel = (system.stats.profile || "Balanced").toLowerCase()

    Connections {
        target: settings
        function onMessage(err) { page.notice = err; hide.restart() }
    }
    Timer { id: hide; interval: 5000; onTriggered: page.notice = "" }

    function steps() { return d.gpuSteps || [] }

    Column {
        id: col
        x: 16
        y: 14
        width: page.width - 32
        spacing: 12

        Rectangle {
            visible: page.notice !== "" || !page.d.helper
            width: parent.width
            height: msg.height + 24
            radius: Theme.radius
            color: Theme.card
            border.color: page.notice !== "" ? Theme.hot : Theme.warm
            Text {
                id: msg
                x: 14; y: 12
                width: parent.width - 28
                wrapMode: Text.WordWrap
                color: Theme.text
                font.pixelSize: 15
                text: page.notice !== "" ? page.notice : Tr.t("Changing this needs the root helper. Install it under Settings > Setup.")
            }
        }

        Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("Edit profile") }
        Chips {
            width: parent.width
            model: (page.d.profiles || []).map(p => ({ key: p.id, label: p.label }))
            current: page.sel
            onPicked: key => page.sel = key
        }

        Column {
            visible: page.prof !== undefined
            width: parent.width
            spacing: 12
            enabled: page.d.helper === true

            Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("CPU governor") }
            Chips {
                width: parent.width
                model: (page.d.governors || []).map(g => ({ key: g, label: g }))
                current: page.prof ? page.prof.governor : ""
                onPicked: key => settings.setProfileOption(page.sel, "cpu_governor", key)
            }

            Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("Underclock") }
            Chips {
                width: parent.width
                model: [{ key: "none", label: Tr.t("Off") }, { key: "small", label: Tr.t("Small") }, { key: "medium", label: Tr.t("Medium") }, { key: "large", label: Tr.t("Large") }]
                current: page.prof ? page.prof.underclock : ""
                onPicked: key => settings.setProfileOption(page.sel, "cpu_underclock", key)
            }

            Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("GPU clock max") + ": " + (page.prof ? page.prof.gpuMax : 0) + " MHz" }
            Slider {
                width: parent.width
                from: 0; to: Math.max(1, page.steps().length - 1); stepSize: 1; snapMode: Slider.SnapAlways
                value: page.steps().indexOf(page.prof ? page.prof.gpuMax : 0)
                onPressedChanged: if (Gesture.hold(pressed)) {
                    const mhz = page.steps()[Math.round(value)]
                    settings.setProfileOption(page.sel, "gpu_max_mhz", mhz)
                    if (page.prof && page.prof.gpuMin > mhz) settings.setProfileOption(page.sel, "gpu_min_mhz", mhz)
                }
            }
            Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("GPU clock min") + ": " + (page.prof ? page.prof.gpuMin : 0) + " MHz" }
            Slider {
                width: parent.width
                from: 0; to: Math.max(1, page.steps().length - 1); stepSize: 1; snapMode: Slider.SnapAlways
                value: page.steps().indexOf(page.prof ? page.prof.gpuMin : 0)
                onPressedChanged: if (Gesture.hold(pressed)) {
                    const mhz = page.steps()[Math.round(value)]
                    settings.setProfileOption(page.sel, "gpu_min_mhz", mhz)
                    if (page.prof && page.prof.gpuMax < mhz) settings.setProfileOption(page.sel, "gpu_max_mhz", mhz)
                }
            }

            Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("Fan curve (drag the points, releasing saves)") }
            Chips {
                width: parent.width
                model: (page.d.curves || []).map(c => ({ key: c.id, label: c.label }))
                current: page.prof ? page.prof.fanCurve : ""
                onPicked: key => settings.setProfileOption(page.sel, "fan_curve", key)
            }
            CurveEditor {
                width: parent.width
                height: 230
                points: page.curve ? page.curve.points : []
                onCommitted: curve => settings.saveFanCurve(page.curve.id, curve)
            }
        }

        Text { color: Theme.muted; font.pixelSize: 15; text: Tr.t("Stick LED colour") }
        Row {
            spacing: 10
            enabled: page.d.helper === true
            Repeater {
                model: page.swatches
                delegate: Rectangle {
                    width: 44; height: 44; radius: 22
                    color: "#" + modelData
                    border.width: (page.rgb.color || "").toUpperCase() === modelData ? 3 : 1
                    border.color: (page.rgb.color || "").toUpperCase() === modelData ? Theme.text : Theme.border
                    MouseArea { anchors.fill: parent; onClicked: settings.setRgb(true, modelData, page.rgb.brightness === undefined ? 25 : page.rgb.brightness) }
                }
            }
        }
    }
}
