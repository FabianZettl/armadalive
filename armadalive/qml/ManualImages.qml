import QtQuick

// The manual's pages as pictures (see manuals.py), scrolling like a long page.
Item {
    id: root
    property bool presentationActive: true
    readonly property bool presented: presentationActive && visible
    readonly property string source: nowPlaying.state.manual
    function sync() {
        if (!presented) manuals.setActive(false)
        manuals.load(source)
        if (presented) manuals.setActive(true)
    }
    onSourceChanged: sync()
    onPresentedChanged: sync()
    Component.onCompleted: sync()
    Component.onDestruction: if (manuals) manuals.load("")

    Empty { visible: pages.count === 0; text: manuals.error === "nopdf" ? Tr.t("Manuals need PyMuPDF (pip install pymupdf).") : (manuals.error === "badpdf" ? Tr.t("This manual could not be read.") : Tr.t("Loading…")) }
    ListView {
        id: pages
        anchors.fill: parent
        clip: true
        spacing: 8
        model: manuals.model
        delegate: Image {
            width: ListView.view.width
            height: implicitHeight > 0 ? width * implicitHeight / implicitWidth : width
            source: model.display
            asynchronous: true
            fillMode: Image.PreserveAspectFit
        }
    }
}
