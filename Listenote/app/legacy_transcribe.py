"""Run original Whisper in its own runtime; exchange progress via JSON lines."""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))


def send(kind, value):
    print(json.dumps({'type':kind,'value':value},ensure_ascii=False),flush=True)


if __name__=='__main__':
    import main
    from runtime_support import legacy_root_available
    from PySide6.QtCore import QCoreApplication
    root=Path(sys.argv[1]).resolve()
    if not legacy_root_available(root):
        send('error','原版高精度识别文件不完整，请选择原版软件所在目录。')
        raise SystemExit(1)
    main.ROOT=root
    app=QCoreApplication([])
    worker=main.Worker(sys.argv[2],sys.argv[3],'legacy',root)
    cancel_marker=Path(sys.argv[4]) if len(sys.argv)>4 else None
    def commands():
        while not worker.cancel:
            if cancel_marker.exists():worker.cancel=True;return
            time.sleep(.1)
    if cancel_marker:threading.Thread(target=commands,daemon=True).start()
    worker.segment.connect(lambda value:send('segment',value))
    worker.progress.connect(lambda n,text:send('progress',[n,text]))
    worker.finished_job.connect(lambda text:send('done',text))
    worker.failed.connect(lambda text:send('error',text))
    worker.run()
