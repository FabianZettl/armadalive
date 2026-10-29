import QtQuick

// 270 degree gauge with the caption above the value and the unit below it, like the stock telemetry rings.
Item {
    id: r
    property real value: 0      // 0..1
    property string text
    property string unit
    property string label
    property color tint: Theme.accent

    onValueChanged: canvas.requestPaint()
    onTintChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        width: Math.min(r.width, r.height)
        height: width
        anchors.centerIn: parent
        onPaint: {
            const c = getContext("2d"), w = width * 0.075, rad = width / 2 - w
            if (rad <= 0) return    // not laid out yet
            const a0 = Math.PI * 0.75, span = Math.PI * 1.5
            c.reset()
            c.lineWidth = w
            c.lineCap = "round"
            c.strokeStyle = Theme.circle
            c.beginPath(); c.arc(width / 2, height / 2, rad, a0, a0 + span); c.stroke()
            c.strokeStyle = r.tint
            c.beginPath(); c.arc(width / 2, height / 2, rad, a0, a0 + span * Math.max(0.02, Math.min(1, r.value))); c.stroke()
        }
    }
    Column {
        anchors.centerIn: parent
        spacing: 0
        Text { anchors.horizontalCenter: parent.horizontalCenter; color: Theme.muted; font.pixelSize: canvas.width * 0.13; text: r.label }
        Text { anchors.horizontalCenter: parent.horizontalCenter; color: Theme.text; font.pixelSize: canvas.width * 0.27; font.weight: Font.Medium; text: r.text }
        Text { anchors.horizontalCenter: parent.horizontalCenter; color: Theme.muted; font.pixelSize: canvas.width * 0.12; text: r.unit }
    }
}
