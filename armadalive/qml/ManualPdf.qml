import QtQuick
import QtQuick.Pdf

// Qt's own PDF viewer. Not every system has the module: Manual.qml then falls back to ManualImages.qml.
PdfMultiPageView {
    document: PdfDocument { source: nowPlaying.state.manual }
}
