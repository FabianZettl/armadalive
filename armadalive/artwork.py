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
        path = QUrl(unquote(image_id)).toLocalFile()
        if not path or requested_size.isEmpty():
            return QImage()

        reader = QImageReader(path)
        natural_size = reader.size()
        if natural_size.isEmpty():
            return QImage()
        scaled_size = natural_size.scaled(requested_size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled_size.expandedTo(QSize(1, 1)))
        image = reader.read()
        if not image.isNull():
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image
