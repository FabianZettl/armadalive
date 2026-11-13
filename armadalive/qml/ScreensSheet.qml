import QtQuick

// Brightness of both screens. Opened by the Brightness tile of the System page (the volume has its keys on the device).
Sheet {
    readonly property var cc: controls.state
    title: Tr.t("Brightness")
    BarSlider {
        width: parent.width; bar: 52; icon: "sun"; label: Tr.t("Top screen"); minimum: 0.03
        value: ((cc.brightness || {}).top || 0) / 100
        onCommitted: v => controls.setBrightness("top", Math.round(v * 100))
    }
    BarSlider {
        width: parent.width; bar: 52; icon: "sun"; label: Tr.t("Bottom screen"); minimum: 0.03
        value: ((cc.brightness || {}).bottom || 0) / 100
        onCommitted: v => controls.setBrightness("bottom", Math.round(v * 100))
    }
}
