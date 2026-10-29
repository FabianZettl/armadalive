import QtQuick

// Outline icons drawn on a 24x24 grid. Our own drawings, in the stroke style of the stock dual-screen app.
Canvas {
    id: ic
    property string name
    property color color: Theme.text
    implicitWidth: 28
    implicitHeight: 28
    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()

    function rr(c, x, y, w, h, r) {
        c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r)
        c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath()
    }
    function ln(c, a, b, x, y) { c.moveTo(a, b); c.lineTo(x, y) }
    function ci(c, x, y, r) { c.moveTo(x + r, y); c.arc(x, y, r, 0, 2 * Math.PI) }

    onPaint: {
        const c = getContext("2d")
        c.reset()
        c.scale(width / 24, height / 24)
        c.strokeStyle = color
        c.fillStyle = color
        c.lineWidth = 1.8
        c.lineCap = "round"
        c.lineJoin = "round"
        c.beginPath()
        switch (name) {
        case "play":        // game controller
            rr(c, 2.5, 7, 19, 11, 5); ln(c, 8, 10.5, 8, 14.5); ln(c, 6, 12.5, 10, 12.5); ci(c, 15.5, 11.5, 0.6); ci(c, 18, 14, 0.6); break
        case "apps":
            rr(c, 4, 4, 6.5, 6.5, 1.6); rr(c, 13.5, 4, 6.5, 6.5, 1.6); rr(c, 4, 13.5, 6.5, 6.5, 1.6); rr(c, 13.5, 13.5, 6.5, 6.5, 1.6); break
        case "mode":        // two screens
            rr(c, 5, 3, 14, 8, 2); rr(c, 5, 13, 14, 8, 2); break
        case "gear":
            ci(c, 12, 12, 3); ci(c, 12, 12, 7)
            for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4; ln(c, 12 + 7 * Math.cos(a), 12 + 7 * Math.sin(a), 12 + 9.8 * Math.cos(a), 12 + 9.8 * Math.sin(a)) }
            break
        case "edit":
            rr(c, 3.5, 6, 14, 14.5, 2.5); ln(c, 10, 14, 20.5, 3.5); ln(c, 17.5, 3.5, 20.5, 6.5); break
        case "book":
            rr(c, 5, 3, 14, 18, 2); ln(c, 9, 3, 9, 21); ln(c, 12, 8, 16, 8); ln(c, 12, 12, 16, 12); break
        case "cheats":
            ln(c, 4, 7, 20, 7); ln(c, 4, 12, 20, 12); ln(c, 4, 17, 13, 17); ci(c, 18, 17, 1.2); break
        case "perf":        // chip
            rr(c, 6.5, 6.5, 11, 11, 2); rr(c, 10, 10, 4, 4, 0.8)
            for (const p of [9.5, 12, 14.5]) { ln(c, p, 3, p, 6.5); ln(c, p, 17.5, p, 21); ln(c, 3, p, 6.5, p); ln(c, 17.5, p, 21, p) }
            break
        case "fan":
            ci(c, 12, 12, 1.6)
            for (let i = 0; i < 3; i++) {
                const a = i * 2 * Math.PI / 3 - Math.PI / 2
                c.moveTo(12 + 1.6 * Math.cos(a), 12 + 1.6 * Math.sin(a))
                c.bezierCurveTo(12 + 9 * Math.cos(a - 0.5), 12 + 9 * Math.sin(a - 0.5), 12 + 9 * Math.cos(a + 0.9), 12 + 9 * Math.sin(a + 0.9), 12 + 5 * Math.cos(a + 1.2), 12 + 5 * Math.sin(a + 1.2))
            }
            break
        case "clean":       // broom
            ln(c, 14, 4, 9, 13); ln(c, 9, 13, 5, 21); ln(c, 5, 21, 15, 21); ln(c, 15, 21, 15, 13); ln(c, 9, 13, 15, 13); ln(c, 10, 17, 14, 17); break
        case "led":         // bulb
            ci(c, 12, 9.5, 5.5); ln(c, 9.5, 17, 14.5, 17); ln(c, 10, 20, 14, 20); ln(c, 10.5, 15, 10.5, 17); ln(c, 13.5, 15, 13.5, 17); break
        case "wifi":
            c.arc(12, 18, 3.5, -2.35, -0.8); c.moveTo(12 + 7 * Math.cos(-2.35), 18 + 7 * Math.sin(-2.35)); c.arc(12, 18, 7, -2.35, -0.8)
            c.moveTo(12 + 10.5 * Math.cos(-2.35), 18 + 10.5 * Math.sin(-2.35)); c.arc(12, 18, 10.5, -2.35, -0.8); ci(c, 12, 18.5, 0.5); break
        case "bluetooth":
            ln(c, 7, 8, 17, 16); ln(c, 17, 16, 12, 21); ln(c, 12, 21, 12, 3); ln(c, 12, 3, 17, 8); ln(c, 17, 8, 7, 16); break
        case "plane":
            ln(c, 21, 3, 11, 13); ln(c, 21, 3, 14.5, 21); ln(c, 14.5, 21, 11, 13); ln(c, 11, 13, 3, 9.5); ln(c, 3, 9.5, 21, 3); break
        case "sound":
            c.moveTo(4, 9.5); c.lineTo(8, 9.5); c.lineTo(13, 5); c.lineTo(13, 19); c.lineTo(8, 14.5); c.lineTo(4, 14.5); c.closePath()
            c.moveTo(16, 9); c.arc(14, 12, 3.2, -0.7, 0.7); c.moveTo(18.5, 6.5); c.arc(14, 12, 7, -0.75, 0.75); break
        case "mute":
            c.moveTo(4, 9.5); c.lineTo(8, 9.5); c.lineTo(13, 5); c.lineTo(13, 19); c.lineTo(8, 14.5); c.lineTo(4, 14.5); c.closePath(); ln(c, 17, 9, 22, 15); ln(c, 22, 9, 17, 15); break
        case "shot":
            ln(c, 4, 9, 4, 4); ln(c, 4, 4, 9, 4); ln(c, 15, 4, 20, 4); ln(c, 20, 4, 20, 9); ln(c, 20, 15, 20, 20); ln(c, 20, 20, 15, 20); ln(c, 9, 20, 4, 20); ln(c, 4, 20, 4, 15); ci(c, 12, 12, 2.5); break
        case "sun":
            ci(c, 12, 12, 4)
            for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4; ln(c, 12 + 6.8 * Math.cos(a), 12 + 6.8 * Math.sin(a), 12 + 9.5 * Math.cos(a), 12 + 9.5 * Math.sin(a)) }
            break
        case "temp":
            rr(c, 10, 3, 4, 12, 2); ci(c, 12, 17.5, 3.5); ln(c, 12, 8, 12, 17); break
        case "gauge":
            c.arc(12, 14, 8, Math.PI, 2 * Math.PI); ln(c, 4, 14, 20, 14); ln(c, 12, 14, 16.5, 9); break
        case "dual":
            rr(c, 6, 3, 12, 8, 2); rr(c, 6, 13, 12, 8, 2); ln(c, 9, 7, 15, 7); ln(c, 9, 17, 15, 17); break
        case "power":
            c.arc(12, 13, 8, -Math.PI * 0.3, Math.PI * 1.3, false); ln(c, 12, 3, 12, 11); break
        case "graph":
            ln(c, 4, 4, 4, 20); ln(c, 4, 20, 20, 20); c.moveTo(6, 16); c.lineTo(10, 11); c.lineTo(13, 14); c.lineTo(19, 6); break
        case "star":
            for (let i = 0; i < 10; i++) { const r = i % 2 ? 4.2 : 9.5, a = -Math.PI / 2 + i * Math.PI / 5; (i ? c.lineTo : c.moveTo).call(c, 12 + r * Math.cos(a), 12.5 + r * Math.sin(a)) }
            c.closePath(); break
        case "info":
            ci(c, 12, 12, 9); ln(c, 12, 11, 12, 17); ci(c, 12, 7.6, 0.5); break
        default:
            ci(c, 12, 12, 8)
        }
        c.stroke()
    }
}
