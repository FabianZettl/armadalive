import QtQuick

// The last two minutes of FPS, CPU, temperature, power and battery. Reached from the Graphs tile on the dashboard.
Item {
    id: page
    property string series: "fps"
    readonly property var hist: system.history
    readonly property var values: hist[series] || []
    readonly property var meta: ({
        fps:     { label: "FPS", unit: "",   lo: 0,  hi: 0 },
        cpu:     { label: "CPU", unit: " %", lo: 0,  hi: 100 },
        temp:    { label: Tr.t("Temperature"), unit: " °C", lo: 30, hi: 100 },
        watts:   { label: Tr.t("Power"), unit: " W", lo: 0, hi: 0 },
        battery: { label: Tr.t("Battery"), unit: " %", lo: 0, hi: 100 }
    })
    readonly property var m: meta[series]
    // fixed scales for percentages, a scale that follows the data for FPS and watts
    readonly property real scaleMax: m.hi > 0 ? m.hi : Math.max(series === "fps" ? 60 : 10, Math.ceil(Math.max.apply(null, values.concat([1])) / 10) * 10)
    onValuesChanged: canvas.requestPaint()
    onScaleMaxChanged: canvas.requestPaint()
    Connections { target: Theme; function onAccentChanged() { canvas.requestPaint() } }

    Chips {
        id: chips
        x: 12; y: 12
        width: parent.width - 24
        model: [{ key: "fps", label: "FPS" }, { key: "cpu", label: "CPU" }, { key: "temp", label: Tr.t("Temperature") },
                { key: "watts", label: Tr.t("Power") }, { key: "battery", label: Tr.t("Battery") }]
        current: page.series
        onPicked: key => page.series = key
    }
    Text {
        id: now
        anchors { left: parent.left; leftMargin: 18; top: chips.bottom; topMargin: 10 }
        color: Theme.text
        font.pixelSize: 34
        font.weight: Font.Medium
        text: page.values.length ? page.values[page.values.length - 1] + page.m.unit : "–"
    }
    Text {
        anchors { right: parent.right; rightMargin: 18; verticalCenter: now.verticalCenter }
        color: Theme.muted
        font.pixelSize: 13
        text: Tr.t("last 2 minutes")
    }
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: now.bottom; bottom: parent.bottom; margins: 12 }
        radius: Theme.radius
        color: Theme.card
        Canvas {
            id: canvas
            anchors { fill: parent; margins: 14 }
            onPaint: {
                const c = getContext("2d"), w = width, h = height, lo = page.m.lo, hi = page.scaleMax, d = page.values
                c.reset()
                c.font = "12px sans-serif"
                c.fillStyle = Theme.muted
                c.strokeStyle = Theme.border
                c.lineWidth = 1
                for (let i = 0; i <= 4; i++) {
                    const y = h - h * i / 4
                    c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.stroke()
                    c.fillText(Math.round(lo + (hi - lo) * i / 4), 2, y - 3)
                }
                if (d.length < 2) return
                const off = 119 - (d.length - 1)    // the newest sample sits on the right edge
                const y = v => h - h * Math.max(0, Math.min(1, (v - lo) / (hi - lo)))
                c.beginPath()
                c.moveTo(w * off / 119, y(d[0]))
                for (let i = 1; i < d.length; i++) c.lineTo(w * (off + i) / 119, y(d[i]))
                c.strokeStyle = Theme.accent
                c.lineWidth = 3
                c.lineJoin = "round"
                c.stroke()
                c.lineTo(w, h); c.lineTo(w * off / 119, h); c.closePath()
                c.fillStyle = Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                c.fill()
            }
        }
    }
}
