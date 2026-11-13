import QtQuick
import QtQuick.Window

// Idle screen: rounded square covers in three rows that scroll sideways. Tap launches, long-press (or the last, empty tile) picks the app.
Item {
    id: grid
    property int picking: -1
    property string opened: ""      // the folder whose view is open
    onOpenedChanged: Gesture.hold(opened !== "")
    readonly property var win: Window.window || ({ width: width, height: height })
    readonly property var slots: apps.slots
    // Touching the grid or the picker locks the page swipe from touch-down, as the dashboard's cards do; while the picker is open
    // the swipe stays locked, so scrolling its tabs or list can never turn the page and close it.
    onPickingChanged: Gesture.hold(picking >= 0)
    PointHandler { target: null; onActiveChanged: { if (grid.picking < 0) Gesture.hold(active) } }
    readonly property real gap: 14
    // The size must not change when the dock hides (the grid gets taller then, the tiles stay and are just centred), so it is
    // taken from the window: the width, and the height that is left with status line, media bar and dock all showing.
    readonly property real u: Math.min(win.width / 620, win.height / 540)
    readonly property real pad: 10 * u   // room for a tapped tile to swell without being clipped
    readonly property real cell: Math.max(60, Math.min((width * 0.76 - 4 * gap) / 3, (win.height - 184 * u - 4 * gap - 2 * pad) / 3))

    GridView {
        id: view
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; verticalCenterOffset: grid.gap / 2 }
        height: 3 * (grid.cell + grid.gap) + 2 * grid.pad   // three whole rows fit: the row count is the height left after the top margin
        leftMargin: grid.gap
        topMargin: grid.pad
        clip: true
        flow: GridView.FlowTopToBottom
        cellWidth: grid.cell + grid.gap
        cellHeight: grid.cell + grid.gap
        model: grid.slots
        boundsBehavior: Flickable.StopAtBounds
        delegate: Item {
            readonly property var app: modelData || ({})
            width: view.cellWidth
            height: view.cellHeight
            // tiles pop in one after another, and a tapped one swells and flashes while its app opens
            Component.onCompleted: appear.start()
            SequentialAnimation {
                id: appear
                PauseAnimation { duration: Math.min(index, 12) * 30 }
                ParallelAnimation {
                    NumberAnimation { target: tile; property: "opacity"; to: 1; duration: Theme.dur(220) }
                    NumberAnimation { target: tile; property: "scale"; to: 1; duration: Theme.dur(260); easing.type: Theme.popEase; easing.overshoot: Theme.overshoot }
                }
            }
            SequentialAnimation {
                id: launched
                ParallelAnimation {
                    NumberAnimation { target: tile; property: "scale"; to: 1.12; duration: Theme.dur(140); easing.type: Theme.ease }
                    NumberAnimation { target: flash; property: "opacity"; to: 0.45; duration: 140 }
                }
                ParallelAnimation {
                    NumberAnimation { target: tile; property: "scale"; to: 1; duration: Theme.dur(320); easing.type: Theme.popEase; easing.overshoot: Theme.overshoot }
                    NumberAnimation { target: flash; property: "opacity"; to: 0; duration: 420 }
                }
            }
            Rectangle {
                id: tile
                width: grid.cell
                height: grid.cell
                radius: grid.cell * Theme.tileCorner
                color: "transparent"
                border.color: app.cover ? "transparent" : Theme.border
                transformOrigin: Item.Center
                opacity: 0
                scale: 0.85
                transform: Scale {   // press feedback, separate from `scale` which the animations drive
                    origin.x: tile.width / 2
                    origin.y: tile.height / 2
                    xScale: area.pressed ? 0.95 : 1
                    yScale: xScale
                    Behavior on xScale { NumberAnimation { duration: 90 } }
                }
                gradient: app.cover && !app.folder ? null : cardGradient
                Gradient {
                    id: cardGradient
                    GradientStop { position: 0; color: Theme.accentSoft }
                    GradientStop { position: 1; color: Theme.card }
                }
                // a folder: up to four of its covers, a sign for the smart ones, its name below
                Grid {
                    visible: !!app.folder && !app.art
                    anchors { top: parent.top; topMargin: parent.height * 0.07; horizontalCenter: parent.horizontalCenter }
                    columns: 2
                    spacing: parent.width * 0.04
                    Repeater {
                        model: app.folder ? Math.max(1, (app.preview || []).length) : 0
                        delegate: Rectangle {
                            width: tile.width * 0.32
                            height: width
                            radius: width * Theme.tileCorner
                            color: Theme.circle
                            Image {
                                anchors.fill: parent
                                source: ((app.preview || [])[index]) || ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                    }
                }
                Item {   // an ES-DE system: its picture from the theme in use, over the whole tile with the tile's corners
                    visible: !!app.art
                    anchors.fill: parent
                    Canvas {   // Canvas clips to the rounded corners on every render backend, unlike a mask effect
                        id: art
                        anchors.fill: parent
                        property url src: app.art || ""
                        onSrcChanged: if (src != "") loadImage(src)
                        Component.onCompleted: if (src != "") loadImage(src)
                        onImageLoaded: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            if (!isImageLoaded(src)) return
                            var r = tile.radius, w = width, h = height
                            ctx.beginPath()
                            ctx.moveTo(r, 0); ctx.arcTo(w, 0, w, h, r); ctx.arcTo(w, h, 0, h, r); ctx.arcTo(0, h, 0, 0, r); ctx.arcTo(0, 0, w, 0, r)
                            ctx.closePath()
                            ctx.clip()
                            // like PreserveAspectCrop: scale to cover, centred
                            ctx.drawImage(src, 0, 0, w, h)
                        }
                    }
                    Rectangle {   // keeps the name readable on a bright picture
                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                        height: parent.height * 0.34
                        radius: tile.radius
                        gradient: Gradient {
                            GradientStop { position: 0; color: "transparent" }
                            GradientStop { position: 1; color: "#cc000000" }
                        }
                    }
                }
                Text {
                    visible: !!app.glyph
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -parent.height * 0.06
                    font.pixelSize: parent.width * 0.42
                    color: Theme.accent
                    text: app.glyph || ""
                }
                Image {
                    visible: !!app.icon && !app.folder
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: app.cover ? 0 : -parent.height * 0.06
                    width: app.cover ? parent.width : parent.width * 0.5
                    height: width
                    source: app.icon || ""
                    sourceSize: Qt.size(width * 2, height * 2)
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }
                Text {
                    visible: !app.icon && !!app.name && !app.folder && !app.glyph
                    anchors.centerIn: parent
                    color: Theme.accent
                    font.pixelSize: parent.width * 0.4
                    font.weight: Font.DemiBold
                    text: app.name ? app.name[0] : ""
                }
                Text {
                    visible: !!app.name && (!app.cover || !!app.folder)
                    anchors { bottom: parent.bottom; bottomMargin: 10; horizontalCenter: parent.horizontalCenter }
                    width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    color: app.art ? "#ffffff" : Theme.muted
                    font.pixelSize: Math.max(11, parent.width * 0.095)
                    text: (app.folder || app.glyph) ? Tr.t(app.name || "") : (app.name || "")
                }
                Text {
                    visible: !app.name
                    anchors.centerIn: parent
                    color: Theme.border
                    font.pixelSize: parent.width * 0.4
                    text: "+"
                }
                Rectangle {
                    id: flash
                    anchors.fill: parent
                    radius: parent.radius
                    color: Theme.accent
                    opacity: 0
                }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    onClicked: { if (app.folder) grid.opened = app.id; else if (app.id) { launched.start(); apps.launch(index) } else grid.picking = index }
                    onPressAndHold: grid.picking = index
                }
            }
        }
    }

    FolderView {
        anchors.fill: parent
        opacity: grid.opened !== "" ? 1 : 0
        scale: grid.opened !== "" ? 1 : 0.96
        visible: opacity > 0.01
        folder: grid.opened
        onClosed: grid.opened = ""
        Behavior on opacity { NumberAnimation { duration: Theme.dur(180) } }
        Behavior on scale { NumberAnimation { duration: Theme.dur(220); easing.type: Theme.ease } }
    }
    AppPicker {
        anchors.fill: parent
        opacity: grid.picking >= 0 ? 1 : 0
        scale: grid.picking >= 0 ? 1 : 0.96
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        slot: grid.picking
        onClosed: grid.picking = -1
    }
}
