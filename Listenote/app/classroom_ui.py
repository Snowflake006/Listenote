from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QListWidget, QDialog, QVBoxLayout, QFormLayout, QLabel, QDialogButtonBox
from ui_components import AppleComboBox

MIME='application/x-listenote-classroom'

class ClassroomList(QListWidget):
    def __init__(self):
        super().__init__();self.setDragEnabled(True)
    def startDrag(self,actions):
        item=self.currentItem()
        if not item:return
        mime=QMimeData();mime.setData(MIME,item.data(Qt.UserRole).encode('utf8'))
        drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.MoveAction)

class SubjectList(QListWidget):
    classroomDropped=Signal(str,str)
    def __init__(self):
        super().__init__();self.setAcceptDrops(True);self.setDropIndicatorShown(True)
    def valid(self,event):
        item=self.itemAt(event.position().toPoint())
        return item if event.mimeData().hasFormat(MIME) and item and item.data(Qt.UserRole) is not None else None
    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(MIME):event.acceptProposedAction()
    def dragMoveEvent(self,event):
        if self.valid(event):event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):
        item=self.valid(event)
        if item:
            self.classroomDropped.emit(bytes(event.mimeData().data(MIME)).decode('utf8'),item.data(Qt.UserRole))
            event.setDropAction(Qt.MoveAction);event.accept()

class RecordingDialog(QDialog):
    def __init__(self,subjects,active,history,parent=None):
        super().__init__(parent);self.setWindowTitle('新建课堂录音');self.setMinimumWidth(450)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(16)
        heading=QLabel('先命名课堂，再开始录音');heading.setObjectName('setupTitle');layout.addWidget(heading)
        form=QFormLayout();self.name=AppleComboBox();self.name.setEditable(True)
        self.name.addItems(list(dict.fromkeys(h['name'] for h in history)))
        self.name.setEditText('');self.name.lineEdit().setPlaceholderText('例如：高等数学 · 第三讲')
        self.subject=AppleComboBox();self.subject.setPlaceholderText('选择学科（可选）')
        for s in subjects:self.subject.addItem(s['name'],s['id'])
        self.subject.setCurrentIndex(self.subject.findData(active or ''))
        form.addRow('录音名称',self.name);form.addRow('学科文件夹',self.subject);layout.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.button(QDialogButtonBox.Ok).setText('开始录音');buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.name.editTextChanged.connect(lambda text:buttons.button(QDialogButtonBox.Ok).setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
