"""Small COM bridge for taskbar metadata and executable Jump List tasks."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import subprocess
import uuid

from desktop_integration import APP_ID

class GUID(c.Structure):
    _fields_=[('data',c.c_byte*16)]
    def __init__(self,value):super().__init__((c.c_byte*16).from_buffer_copy(uuid.UUID(value).bytes_le))

class Key(c.Structure):
    _fields_=[('fmtid',GUID),('pid',w.DWORD)]

class Value(c.Structure):
    _fields_=[('vt',c.c_ushort),('r1',c.c_ushort),('r2',c.c_ushort),('r3',c.c_ushort),('value',c.c_void_p),('padding',c.c_void_p)]

IID_STORE='886d8eeb-8cf2-4446-8d02-cdba1dbdcf99'
FMT_APP='9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'

def call(ptr,index,types,*args):
    table=c.cast(ptr,c.POINTER(c.POINTER(c.c_void_p))).contents
    fn=c.WINFUNCTYPE(c.c_long,c.c_void_p,*types)(table[index])
    result=fn(ptr,*args)
    if result<0:raise RuntimeError('Windows Shell HRESULT '+hex(result & 0xffffffff))
    return result

def create(clsid,iid):
    ptr=c.c_void_p()
    result=c.windll.ole32.CoCreateInstance(c.byref(GUID(clsid)),None,1,c.byref(GUID(iid)),c.byref(ptr))
    if result<0:raise RuntimeError('Windows Shell creation failed '+hex(result & 0xffffffff))
    return ptr

def query(ptr,iid):
    result=c.c_void_p();call(ptr,0,[c.c_void_p,c.c_void_p],c.byref(GUID(iid)),c.byref(result));return result

def release(ptr):
    if ptr:call(ptr,2,[])

def prop(store,fmt,pid,text):
    key=Key(GUID(fmt),pid);buf=c.create_unicode_buffer(text)
    value=Value();value.vt=31;value.value=c.cast(buf,c.c_void_p)
    call(store,6,[c.c_void_p,c.c_void_p],c.byref(key),c.byref(value))

def register_taskbar(window,data):
    initialized=c.windll.ole32.CoInitializeEx(None,2)
    try:_register_taskbar(window,data)
    finally:
        if initialized>=0:c.windll.ole32.CoUninitialize()


def _register_taskbar(window,data):
    root=Path(__file__).resolve().parent.parent
    launcher=root/'听课.exe';icon=root/'app'/'icon.ico'
    # Jump List commands use the app launcher, so taskbar entries retain the
    # same name/icon and forward into the existing instance via QLocalSocket.
    store=c.c_void_p()
    get=c.windll.shell32.SHGetPropertyStoreForWindow
    get.argtypes=[w.HWND,c.c_void_p,c.c_void_p];get.restype=c.c_long
    hr=get(w.HWND(int(window.winId())),c.byref(GUID(IID_STORE)),c.byref(store))
    if hr<0:raise RuntimeError('无法设置任务栏应用标识')
    try:
        for pid,text in [(5,APP_ID),(2,subprocess.list2cmdline([str(launcher),'--data-dir',str(data)])),
                         (3,str(icon)+',0'),(4,'Listenote')]:prop(store,FMT_APP,pid,text)
        call(store,7,[])
    finally:release(store)
    destination=create('77f10cf0-3db5-4966-b520-b7c54fd35ed6','6332debf-87b5-4670-90c0-5e57b408a49e')
    collection=None;removed=c.c_void_p()
    try:
        call(destination,3,[c.c_wchar_p],APP_ID)
        count=w.UINT()
        call(destination,4,[c.c_void_p,c.c_void_p,c.c_void_p],c.byref(count),
             c.byref(GUID('92ca9dcd-5622-4bba-a805-5e9f541bd8c9')),c.byref(removed))
        collection=create('2d3468c1-36a7-43b6-ac24-d3f02fd9607a','5632b1a4-e38a-400a-928a-d4cd63230295')
        for title,action in [('开始录制','record'),('暂停录制','pause'),('结束录制','stop')]:
            link=create('00021401-0000-0000-c000-000000000046','000214f9-0000-0000-c000-000000000046')
            properties=None
            try:
                call(link,20,[c.c_wchar_p],str(launcher))
                call(link,11,[c.c_wchar_p],subprocess.list2cmdline(['--data-dir',str(data),'--task-action',action]))
                call(link,9,[c.c_wchar_p],str(root))
                call(link,17,[c.c_wchar_p,c.c_int],str(icon),0)
                properties=query(link,IID_STORE)
                prop(properties,'f29f85e0-4ff9-1068-ab91-08002b27b3d9',2,title)
                call(properties,7,[])
                call(collection,5,[c.c_void_p],link)
            finally:release(properties);release(link)
        call(destination,7,[c.c_void_p],collection)
        call(destination,8,[])
    except Exception:
        try:call(destination,11,[])
        except RuntimeError:pass
        raise
    finally:release(removed);release(collection);release(destination)
