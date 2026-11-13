import QtQuick

// The stick LEDs: on/off, brightness and colour. Opened by a tap on the Stick LEDs tile of the System page.
Sheet {
    id: page
    readonly property var rgb: settings.data.rgb || ({})
    readonly property bool helper: settings.data.helper === true
    readonly property var swatches: ["FFFFFF", "FF3B30", "FF9500", "FFD60A", "30D158", "64D2FF", "0A84FF", "BF5AF2", "FF2D92"]
    readonly property real bar: 52
    // a colour just picked shows at once; the helper's file catches up a moment later
    property string led: ""
    readonly property string ledColor: (led !== "" ? led : (rgb.color || "FFFFFF")).toUpperCase()
    onRgbChanged: led = ""
    title: Tr.t("Stick LEDs")

    function hex(c) { return [c.r, c.g, c.b].map(x => ("0" + Math.round(x * 255).toString(16)).slice(-2)).join("").toUpperCase() }
    readonly property bool follows: ui.state.ledFollow !== false
    function paint(color) {
        ui.setLedFollow(false)   // a colour picked here is the user's own: the LEDs stop following the theme
        led = color
        if (helper) settings.setRgb(true, color, rgb.brightness === undefined ? 25 : rgb.brightness)
    }

    Chips {
        width: parent.width
        model: [{ key: "on", label: Tr.t("On") }, { key: "off", label: Tr.t("Off") }]
        current: page.rgb.enabled === false ? "off" : "on"
        onPicked: key => { if (page.helper) settings.setRgb(key === "on", page.ledColor, page.rgb.brightness === undefined ? 25 : page.rgb.brightness) }
    }
    BarSlider {
        width: parent.width; bar: page.bar; icon: "led"; label: Tr.t("Brightness")
        value: (page.rgb.brightness || 0) / 100
        onCommitted: v => { if (page.helper) settings.setRgb(true, page.ledColor, Math.round(v * 100)) }
    }
    // the rainbow: touch or drag to pick a hue, the colour is sent when the finger lifts
    Item {
        id: hue
        width: parent.width
        height: 56
        property real pos: -1
        readonly property color shown: Qt.color("#" + page.ledColor)
        readonly property real at: pos >= 0 ? pos : (shown.hsvSaturation < 0.1 ? -1 : shown.hsvHue)
        Rectangle {
            id: ramp
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
            height: 40
            radius: 20
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.00; color: "#ff0000" }
                GradientStop { position: 0.17; color: "#ffff00" }
                GradientStop { position: 0.33; color: "#00ff00" }
                GradientStop { position: 0.50; color: "#00ffff" }
                GradientStop { position: 0.67; color: "#0000ff" }
                GradientStop { position: 0.83; color: "#ff00ff" }
                GradientStop { position: 1.00; color: "#ff0000" }
            }
        }
        Rectangle {
            visible: hue.at >= 0
            x: hue.at * (ramp.width - width)
            anchors.verticalCenter: parent.verticalCenter
            width: 48; height: 48; radius: 24
            color: hue.shown
            border.width: 4
            border.color: "#ffffff"
        }
        MouseArea {
            anchors.fill: parent
            function set(mx) { hue.pos = Math.max(0, Math.min(1, (mx - 24) / (ramp.width - 48))) }
            onPressed: mouse => { Gesture.hold(true); set(mouse.x) }
            onPositionChanged: mouse => set(mouse.x)
            onReleased: { Gesture.hold(false); page.paint(page.hex(Qt.hsva(hue.pos, 1, 1, 1))); hue.pos = -1 }
            onCanceled: { Gesture.hold(false); hue.pos = -1 }
        }
    }
    Flow {
        width: parent.width
        spacing: 12
        Repeater {
            model: page.swatches
            delegate: Rectangle {
                width: 52; height: 52; radius: 26
                color: "#" + modelData
                border.width: page.ledColor === modelData ? 4 : 1
                border.color: page.ledColor === modelData ? Theme.text : Theme.border
                MouseArea { anchors.fill: parent; onClicked: page.paint(modelData) }
            }
        }
        Rectangle {
            width: 52; height: 52; radius: 26
            color: Theme.accent
            border.width: page.follows ? 4 : 1
            border.color: page.follows ? Theme.text : Theme.border
            Text { anchors.centerIn: parent; color: Theme.onAccent; font.pixelSize: 11; font.weight: Font.DemiBold; text: Tr.t("Theme") }
            MouseArea { anchors.fill: parent; onClicked: { page.paint(page.hex(Theme.accent)); ui.setLedFollow(true) } }
        }
    }
    Text {
        visible: page.follows && page.helper
        width: parent.width
        wrapMode: Text.WordWrap
        color: Theme.muted
        font.pixelSize: 13
        text: Tr.t("The LEDs follow the theme until you pick a colour of your own.")
    }
    Text {
        visible: !page.helper
        width: parent.width
        wrapMode: Text.WordWrap
        color: Theme.muted
        font.pixelSize: 13
        text: Tr.t("Changing the LEDs needs the root helper (Settings → Setup).")
    }
}
