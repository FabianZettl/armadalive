"""Rasterize local vectors inside the requested bounds on Qt's image loader thread."""
from urllib.parse import unquote

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider


class VectorArtwork(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image,
                         QQuickImageProvider.Flag.ForceAsynchronousImageLoading)

    def requestImage(self, image_id, size, requested_size):
        natural_request_width = 0
        if image_id.startswith("natural/"):
            _, width, image_id = image_id.split("/", 2)
            natural_request_width = float(width)
        path = QUrl(unquote(image_id)).toLocalFile()
        if not path or requested_size.isEmpty():
            return QImage()

        reader = QImageReader(path)
        natural_size = reader.size()
        if natural_size.isEmpty():
            return QImage()
        size.setWidth(natural_size.width())
        size.setHeight(natural_size.height())
        scaled_size = natural_size.scaled(requested_size, Qt.AspectRatioMode.KeepAspectRatio)
        if natural_request_width:
            # Qt scales provider requests for the window's pixel ratio. Keep game marquees
            # at their natural logical size without reducing resolution on scaled displays.
            pixel_ratio = requested_size.width() / natural_request_width
            scaled_size = scaled_size.boundedTo(natural_size * pixel_ratio)
        reader.setScaledSize(scaled_size.expandedTo(QSize(1, 1)))
        return reader.read()
