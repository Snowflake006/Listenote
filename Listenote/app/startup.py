import os,sys,traceback,runpy,ctypes
from pathlib import Path
folder=Path(os.environ.get('LISTENOTE_DATA',str(Path(os.environ.get('LOCALAPPDATA',str(Path(__file__).parent)))/'Listenote')))
folder.mkdir(parents=True,exist_ok=True)
try:
    with (folder/'startup.log').open('w',encoding='utf8') as log:
        sys.stdout=log;sys.stderr=log
        runpy.run_path(str(Path(__file__).with_name('main.py')),run_name='__main__')
except Exception:
    (folder/'error.log').write_text(traceback.format_exc(),encoding='utf8')
    ctypes.windll.user32.MessageBoxW(0,'启动失败。请确认完整解压软件包。\n错误日志：'+str(folder/'error.log'),'听课 Listenote',0x10)
