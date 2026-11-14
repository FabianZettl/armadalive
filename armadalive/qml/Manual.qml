import QtQuick

Item {
    id: root
    property bool presentationActive: true
    visible: presentationActive
    readonly property string source: nowPlaying.state.manual

    Empty { visible: root.source === ""; text: Tr.t("This game has no manual.") }
    // Qt's PDF viewer if this system has it, else the pictures drawn by PyMuPDF
    Loader { id: pdf; anchors.fill: parent; active: root.source !== ""; source: "ManualPdf.qml" }
    Loader {
        anchors.fill: parent
        active: root.source !== "" && pdf.status === Loader.Error
        onActiveChanged: if (active) setSource("ManualImages.qml", {"presentationActive": Qt.binding(() => root.presentationActive)})
    }
}
