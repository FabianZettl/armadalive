import QtQuick

// Fan curve: temperature (x) against fan PWM (y). Drag the points, the new curve is committed on release.
// Points below the visible range (the 0 °C baseline) are kept as they are.
Item {
    id: ed
    property var points: []         // [[tempC, pwm], ...]
    signal committed(string curve)

    readonly property real tMin: 30
    readonly property real tMax: 100
    property var work: []
    property var fixed: []
    property int active: -1

    implicitHeight: 230
    onPointsChanged: {
        work = points.filter(p => p[0] >= tMin).map(p => [p[0], p[1]])
        fixed = points.filter(p => p[0] < tMin)
        canvas.requestPaint()
    }
    function px(t) { return (t - tMin) / (tMax - tMin) * canvas.width }
    function py(v) { return canvas.height - v / 255 * canvas.height }
    function text() {
        return fixed.concat(work).map(p => Math.round(p[0]) + ":" + Math.round(p[1])).join(",")
    }

    Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.card; border.color: Theme.border }
    Canvas {
        id: canvas
        anchors { fill: parent; margins: 14 }
        onPaint: {
            const c = getContext("2d")
            c.reset()
            c.lineWidth = 1
            c.font = "12px sans-serif"
            c.fillStyle = Theme.muted
            c.strokeStyle = Theme.border
            for (const t of [40, 60, 80, 100]) {
                c.beginPath(); c.moveTo(ed.px(t), 0); c.lineTo(ed.px(t), height); c.stroke()
                c.fillText(t + "°", ed.px(t) - 12, height - 2)
            }
            for (const v of [64, 128, 192, 255]) {
                c.beginPath(); c.moveTo(0, ed.py(v)); c.lineTo(width, ed.py(v)); c.stroke()
                c.fillText(Math.round(v / 2.55) + "%", 2, ed.py(v) - 3)
            }
            const w = ed.work
            if (w.length === 0) return
            c.strokeStyle = Theme.accent
            c.lineWidth = 3
            c.lineJoin = "round"
            c.beginPath()
            c.moveTo(0, ed.py(ed.fixed.length ? ed.fixed[0][1] : w[0][1]))
            for (const p of w) c.lineTo(ed.px(p[0]), ed.py(p[1]))
            c.lineTo(width, ed.py(w[w.length - 1][1]))
            c.stroke()
            for (let i = 0; i < w.length; i++) {
                c.fillStyle = i === ed.active ? "#ffffff" : Theme.accent
                c.beginPath(); c.arc(ed.px(w[i][0]), ed.py(w[i][1]), i === ed.active ? 11 : 8, 0, 2 * Math.PI); c.fill()
            }
            if (ed.active >= 0) {
                c.fillStyle = Theme.text
                c.fillText(Math.round(w[ed.active][0]) + "°C  " + Math.round(w[ed.active][1] / 2.55) + "%", width - 90, 14)
            }
        }
        MouseArea {
            anchors.fill: parent
            onPressed: mouse => {
                Gesture.hold(true)
                let best = -1, dist = 36
                for (let i = 0; i < ed.work.length; i++) {
                    const d = Math.hypot(ed.px(ed.work[i][0]) - mouse.x, ed.py(ed.work[i][1]) - mouse.y)
                    if (d < dist) { dist = d; best = i }
                }
                ed.active = best
                canvas.requestPaint()
            }
            onPositionChanged: mouse => {
                if (ed.active < 0) return
                const w = ed.work, i = ed.active
                const lo = i > 0 ? w[i - 1][0] + 1 : ed.tMin, hi = i < w.length - 1 ? w[i + 1][0] - 1 : ed.tMax
                w[i] = [Math.max(lo, Math.min(hi, ed.tMin + mouse.x / canvas.width * (ed.tMax - ed.tMin))),
                        Math.max(0, Math.min(255, (1 - mouse.y / canvas.height) * 255))]
                canvas.requestPaint()
            }
            onCanceled: Gesture.hold(false)
            onReleased: {
                Gesture.hold(false)
                if (ed.active >= 0) ed.committed(ed.text())
                ed.active = -1
                canvas.requestPaint()
            }
        }
    }
}
