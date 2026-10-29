import QtQuick
import QtQuick.Pdf

Item {
    id: root
    readonly property string source: nowPlaying.state.manual

    Empty { visible: root.source === ""; text: Tr.t("This game has no manual.") }
    PdfMultiPageView {
        anchors.fill: parent
        visible: root.source !== ""
        document: PdfDocument { source: root.source }
    }
}
