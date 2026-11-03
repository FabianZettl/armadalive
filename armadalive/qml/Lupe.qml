import QtQuick

// A part of the main screen, live and enlarged. First drag a rectangle on a small picture of the main screen; then only
// that part is shown. The capture runs only while this page is open.
Item {
    id: page
    readonly property string mode: lupe.mode
    property bool alive: true
    function start() { if (alive && lupe.available && lupe.mode === "off" && lupe.problem === "") lupe.show(width, height) }
    Timer { interval: 60; running: true; onTriggered: page.start() }   // the size is known by then
    Connections { target: lupe; function onChanged() { page.start() } }   // the capture check may finish after the page opened
    Component.onDestruction: { alive = false; lupe.stop() }

    Image {
        id: view
        anchors.fill: parent
        visible: lupe.available && page.mode !== "off"
        fillMode: Image.PreserveAspectFit
        cache: false
        source: "image://lupe/" + lupe.tick
        // where the picture really is inside the item (PreserveAspectFit leaves bars)
        readonly property real shownW: paintedWidth
        readonly property real shownH: paintedHeight
        readonly property real offX: (width - paintedWidth) / 2
        readonly property real offY: (height - paintedHeight) / 2
    }
    // picking: drag a rectangle over the picture
    Rectangle {
        id: box
        visible: page.mode === "pick" && area.pressed
        color: "#33ffffff"
        border.color: Theme.accent
        border.width: 2
        x: Math.min(area.sx, area.cx); y: Math.min(area.sy, area.cy)
        width: Math.abs(area.cx - area.sx); height: Math.abs(area.cy - area.sy)
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: page.mode === "pick"
        property real sx: 0
        property real sy: 0
        property real cx: 0
        property real cy: 0
        onPressed: mouse => { Gesture.hold(true); sx = cx = mouse.x; sy = cy = mouse.y }
        onPositionChanged: mouse => { cx = Math.max(view.offX, Math.min(view.offX + view.shownW, mouse.x)); cy = Math.max(view.offY, Math.min(view.offY + view.shownH, mouse.y)) }
        onReleased: {
            Gesture.hold(false)
            if (view.shownW <= 0) return
            const x0 = (Math.min(sx, cx) - view.offX) / view.shownW, y0 = (Math.min(sy, cy) - view.offY) / view.shownH
            lupe.select(Math.max(0, x0), Math.max(0, y0), Math.abs(cx - sx) / view.shownW, Math.abs(cy - sy) / view.shownH, page.width, page.height)
        }
        onCanceled: Gesture.hold(false)
    }
    Text {
        visible: page.mode === "pick"
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 10 }
        color: Theme.text
        font.pixelSize: 16
        style: Text.Outline
        styleColor: "#000000"
        text: Tr.t("Drag a rectangle over the part of the main screen you want to see")
    }
    // zoomed: choose another area
    PillButton {
        visible: page.mode === "zoom"
        anchors { right: parent.right; bottom: parent.bottom; margins: 10 }
        label: Tr.t("Choose area")
        onClicked: lupe.pick()
    }
    Text {
        visible: page.mode !== "off" && !lupe.live
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 8 }
        color: Theme.muted
        font.pixelSize: 15
        text: Tr.t("Waiting for the main screen to change …")
    }
    // nothing to show
    Text {
        visible: !lupe.available || (page.mode === "off" && lupe.problem !== "")
        anchors { centerIn: parent }
        width: parent.width - 48
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        color: Theme.muted
        font.pixelSize: 16
        text: lupe.problem === "checking" ? Tr.t("Looking for the main screen …")
            : lupe.problem === "source" ? Tr.t("The main screen's video source was not found. Is a game or Steam running there?")
            : Tr.t("The Lupe needs GStreamer's PipeWire plugin (package pipewire-gstreamer), or a copy of libgstpipewire.so in the gst-plugins folder of ArmadaLive.")
    }
}
