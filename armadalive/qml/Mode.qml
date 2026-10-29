import QtQuick

// Brightness of both screens and the stick LEDs, volume.
Flickable {
    id: page
    readonly property var cc: controls.state
    readonly property var rgb: settings.data.rgb || ({})
    readonly property real m: 10
    contentHeight: col.height + 2 * m
    clip: true

    Column {
        id: col
        x: page.m; y: page.m
        width: page.width - 2 * page.m
        spacing: page.m

        Rectangle {
            width: parent.width
            height: bright.height + 28
            radius: Theme.radius
            color: Theme.card
            Column {
                id: bright
                x: 14; y: 14
                width: parent.width - 28
                spacing: 4
                Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("Brightness") }
                BarSlider {
                    width: parent.width; icon: "sun"; label: Tr.t("Top screen"); minimum: 0.03
                    value: ((page.cc.brightness || {}).top || 0) / 100
                    onCommitted: v => controls.setBrightness("top", Math.round(v * 100))
                }
                BarSlider {
                    width: parent.width; icon: "sun"; label: Tr.t("Bottom screen"); minimum: 0.03
                    value: ((page.cc.brightness || {}).bottom || 0) / 100
                    onCommitted: v => controls.setBrightness("bottom", Math.round(v * 100))
                }
                BarSlider {
                    width: parent.width; icon: "led"; label: Tr.t("Stick LEDs")
                    value: (page.rgb.brightness || 0) / 100
                    onCommitted: v => { if (settings.data.helper) settings.setRgb(true, page.rgb.color || "FFFFFF", Math.round(v * 100)) }
                }
            }
        }
        Rectangle {
            width: parent.width
            height: sound.height + 28
            radius: Theme.radius
            color: Theme.card
            Column {
                id: sound
                x: 14; y: 14
                width: parent.width - 28
                spacing: 4
                Text { color: Theme.muted; font.pixelSize: 14; text: Tr.t("Volume") }
                BarSlider {
                    width: parent.width; icon: page.cc.muted ? "mute" : "sound"; label: page.cc.muted ? Tr.t("Muted") : Tr.t("Output")
                    value: page.cc.volume || 0
                    onCommitted: v => controls.setVolume(v)
                }
            }
        }
    }
}
