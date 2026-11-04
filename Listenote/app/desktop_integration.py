"""Windows taskbar identity, Jump List tasks and same-instance command routing."""
import ctypes
import hashlib
import os
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

APP_ID='Listenote.Desktop'
ACTIONS=('record','pause','stop')


def set_process_identity():
    if sys.platform=='win32':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def server_name(data):
    return 'Listenote-'+hashlib.sha256(str(Path(data).resolve()).lower().encode()).hexdigest()[:24]


def forward_action(data,action):
    socket=QLocalSocket();socket.connectToServer(server_name(data))
    if not socket.waitForConnected(400):return False
    socket.write((action+'\n').encode());socket.flush();socket.waitForBytesWritten(500)
    # Keep the named pipe alive until the running instance has consumed it.
    received=socket.waitForReadyRead(2000)
    acknowledged=received and bytes(socket.readAll())==b'ok\n'
    socket.disconnectFromServer();return acknowledged


class DesktopIntegration(QObject):
    def __init__(self,window,data):
        super().__init__(window);self.window=window;self.data=data
        self.server=None;self.shell_error=''
        if QApplication.platformName() in ('offscreen','minimal'):return
        self.server=QLocalServer(self)
        if not self.server.listen(server_name(data)):
            # A live listener is left alone; only stale endpoints are removed.
            if not forward_action(data,'activate'):
                QLocalServer.removeServer(server_name(data));self.server.listen(server_name(data))
        self.server.newConnection.connect(self.receive)
        if sys.platform=='win32' and not os.environ.get('LISTENOTE_DISABLE_SHELL_INTEGRATION'):
            QTimer.singleShot(500,self.register_shell)

    def receive(self):
        while self.server.hasPendingConnections():
            socket=self.server.nextPendingConnection();socket.setProperty('buffer',b'')
            socket.readyRead.connect(lambda socket=socket:self.read_command(socket))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():self.read_command(socket)

    def read_command(self,socket):
        data=bytes(socket.property('buffer') or b'')+bytes(socket.readAll())
        if len(data)>128:socket.abort();return
        socket.setProperty('buffer',data)
        if b'\n' in data:
            action=data.split(b'\n',1)[0].decode('ascii','ignore')
            if action in (*ACTIONS,'activate'):
                socket.write(b'ok\n');socket.flush()
                self.dispatch(action)
            socket.disconnectFromServer()

    def dispatch(self,action):
        if action not in (*ACTIONS,'activate'):return
        w=self.window
        if action=='record':
            if w.isMinimized():w.showNormal()
            w.raise_();w.activateWindow();w.record()
        elif action=='pause':
            if w.rec and not w.rec_paused:w.pause_record()
        elif action=='stop':
            if w.rec:w.finish_record()
        else:
            if w.isMinimized():w.showNormal()
            w.raise_();w.activateWindow()

    def register_shell(self):
        try:
            from windows_shell import register_taskbar
            register_taskbar(self.window,self.data)
        except (OSError,RuntimeError,ValueError) as exc:
            self.shell_error=str(exc)
