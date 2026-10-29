import QtQuick

// The manual's pages as pictures (see manuals.py), scrolling like a long page.
Item {
    id: root
    readonly property string source: nowPlaying.state.manual
    onSourceChanged: manuals.load(source)
    Component.onCompleted: manuals.load(source)

    Empty { visible: manuals.pages.length === 0; text: manuals.error === "nopdf" ? Tr.t("Manuals need PyMuPDF (pip install pymupdf).") : (manuals.error === "badpdf" ? Tr.t("This manual could not be read.") : Tr.t("Loading…")) }
    ListView {
        anchors.fill: parent
        clip: true
        spacing: 8
        model: manuals.pages
        delegate: Image {
            width: ListView.view.width
            height: implicitHeight > 0 ? width * implicitHeight / implicitWidth : width
            source: modelData
            asynchronous: true
            fillMode: Image.PreserveAspectFit
        }
    }
}
