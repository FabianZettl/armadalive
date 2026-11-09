import QtQuick

// A faint pattern behind everything, the theme's `pattern` (Theme.qml): painted once per change, in the text colour at a low opacity.
Canvas {
    id: c
    readonly property string kind: Theme.pattern
    visible: kind !== "none"
    onKindChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Connections { target: Theme; function onTextChanged() { c.requestPaint() } }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        if (kind === "none") return
        const t = Theme.text
        ctx.fillStyle = Qt.rgba(t.r, t.g, t.b, 0.07)
        ctx.strokeStyle = Qt.rgba(t.r, t.g, t.b, 0.07)
        ctx.lineWidth = 1
        const w = width, h = height
        if (kind === "dots") {
            for (let y = 14; y < h; y += 28) for (let x = ((y / 28) % 2 ? 28 : 14); x < w; x += 28) { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 6.2832); ctx.fill() }
        } else if (kind === "grid") {
            ctx.beginPath()
            for (let x = 0; x < w; x += 36) { ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, h) }
            for (let y = 0; y < h; y += 36) { ctx.moveTo(0, y + 0.5); ctx.lineTo(w, y + 0.5) }
            ctx.stroke()
        } else if (kind === "scan") {
            for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1)
        } else if (kind === "diag") {
            ctx.lineWidth = 8
            ctx.beginPath()
            for (let x = -h; x < w; x += 44) { ctx.moveTo(x, h); ctx.lineTo(x + h, 0) }
            ctx.stroke()
        } else if (kind === "checker") {
            for (let y = 0; y * 40 < h; y++) for (let x = 0; x * 40 < w; x++) if ((x + y) % 2) ctx.fillRect(x * 40, y * 40, 40, 40)
        } else if (kind === "stars") {
            let seed = 7
            for (let i = 0; i < 90; i++) {
                seed = (seed * 1103515245 + 12345) % 2147483648; const x = seed % Math.max(1, Math.floor(w))
                seed = (seed * 1103515245 + 12345) % 2147483648; const y = seed % Math.max(1, Math.floor(h))
                const r = 0.8 + (seed % 3) * 0.6
                ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill()
            }
        }
    }
}
