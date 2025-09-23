from PySide6 import QtWidgets, QtGui, QtCore
import sys, os

class SegmentsModel(QtCore.QAbstractListModel):
    PixmapRole = QtCore.Qt.UserRole + 1
    PathRole   = QtCore.Qt.UserRole + 2

    def __init__(self, paths):
        super().__init__()
        self._items = [{"path": p, "name": os.path.basename(p), "pix": None} for p in paths]

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._items)

    def data(self, index, role):
        it = self._items[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return it["name"]
        if role == SegmentsModel.PixmapRole:
            return it["pix"]
        if role == SegmentsModel.PathRole:
            return it["path"]

    def setPixmap(self, row, pix):
        self._items[row]["pix"] = pix
        ix = self.index(row)
        self.dataChanged.emit(ix, ix, [SegmentsModel.PixmapRole])

class TileDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter, option, index):
        # základní vykreslení
        super().paint(painter, option, index)

        # náhled
        pix = index.data(SegmentsModel.PixmapRole)
        rect = option.rect.adjusted(6, 6, -6, -28)
        if pix:
            scaled = pix.scaled(rect.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

        # titulek
        name = index.data(QtCore.Qt.DisplayRole)
        text_rect = option.rect.adjusted(6, option.rect.height()-24, -6, -6)
        painter.drawText(text_rect, QtCore.Qt.TextWordWrap, name)

        # červený rámeček při výběru
        if option.state & QtWidgets.QStyle.State_Selected:
            pen = QtGui.QPen(QtGui.QColor("red"), 2)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))

class Window(QtWidgets.QWidget):
    def __init__(self, folder):
        super().__init__()
        self.setWindowTitle("Qt Tiles Demo")
        paths = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.lower().endswith(".png")]
        self.model = SegmentsModel(paths)

        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QtWidgets.QListView.IconMode)
        self.view.setResizeMode(QtWidgets.QListView.Adjust)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.view.setSpacing(12)
        self.view.setItemDelegate(TileDelegate())
        self.view.setIconSize(QtCore.QSize(260, 130))  # prostor pro pix
        self.view.setUniformItemSizes(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.view)

        # asynchronně vytvoř náhledy
        self.pool = QtCore.QThreadPool.globalInstance()
        for row, p in enumerate(paths):
            self.pool.start(self._thumb_job(row, p))

    def _thumb_job(self, row, path):
        class Job(QtCore.QRunnable):
            def run(job_self):
                img = QtGui.QImage(path)
                pix = QtGui.QPixmap.fromImage(img)
                # signal back to GUI thread
                QtCore.QMetaObject.invokeMethod(
                    self, "setThumb", QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(int, row), QtCore.Q_ARG(QtGui.QPixmap, pix)
                )
        return Job()

    @QtCore.Slot(int, QtGui.QPixmap)
    def setThumb(self, row, pix):
        self.model.setPixmap(row, pix)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    # zadej svou složku se segmenty:
    w = Window("/Users/jirka/Downloads/tvorba cenovych nabidek/python/aplikace na generovani/pool/segmenty")
    w.resize(1100, 700)
    w.show()
    sys.exit(app.exec())