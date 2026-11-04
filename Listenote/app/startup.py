import os,sys,traceback,runpy,ctypes
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import bootstrap
bootstrap(__file__)
if '--runtime-info' in sys.argv:
    import importlib.util,json
    print(json.dumps({'executable':sys.executable,'faster_whisper':bool(importlib.util.find_spec('faster_whisper'))}))
    raise SystemExit(0)
if '--data-dir' in sys.argv:
    i=sys.argv.index('--data-dir')
    if i+1<len(sys.argv):os.environ['LISTENOTE_DATA']=sys.argv[i+1]
folder=Path(os.environ.get('LISTENOTE_DATA',str(Path(os.environ.get('LOCALAPPDATA',str(Path(__file__).parent)))/'Listenote')))
folder.mkdir(parents=True,exist_ok=True)
try:
    with (folder/'startup.log').open('w',encoding='utf8') as log:
        sys.stdout=log;sys.stderr=log
        runpy.run_path(str(Path(__file__).with_name('main.py')),run_name='__main__')
except Exception:
    (folder/'error.log').write_text(traceback.format_exc(),encoding='utf8')
    ctypes.windll.user32.MessageBoxW(0,'启动失败。请确认完整解压软件包。\n错误日志：'+str(folder/'error.log'),'听课 Listenote',0x10)
