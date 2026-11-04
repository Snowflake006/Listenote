"""Build a portable preview or a trimmed release, with a standard Windows ZIP."""
from pathlib import Path
import hashlib
import shutil
import sys
import zipfile
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Listenote'
sys.path.insert(0,str(SOURCE/'app'))
from version import VERSION
RELEASE = '--release' in sys.argv
TARGET = ROOT / ('.release' if RELEASE else '.preview') / 'Listenote'


def pe_imports(file):
    """Read DLL imports, including delay imports, without an extra build dependency."""
    data=file.read_bytes()
    if data[:2]!=b'MZ':return []
    pe=struct.unpack_from('<I',data,0x3c)[0]
    count=struct.unpack_from('<H',data,pe+6)[0]
    size=struct.unpack_from('<H',data,pe+20)[0]
    optional=pe+24
    wide=struct.unpack_from('<H',data,optional)[0]==0x20b
    directories=optional+(112 if wide else 96)
    sections=[struct.unpack_from('<IIII',data,optional+size+i*40+8) for i in range(count)]
    def offset(rva):
        for virtual_size,address,raw_size,raw in sections:
            if address<=rva<address+max(virtual_size,raw_size):return raw+rva-address
        return rva
    names=[]
    for entry,stride,name_pos in [(1,20,12),(13,32,4)]:
        rva=struct.unpack_from('<I',data,directories+entry*8)[0]
        if not rva:continue
        pos=offset(rva)
        while any(data[pos:pos+stride]):
            name_rva=struct.unpack_from('<I',data,pos+name_pos)[0]
            name=offset(name_rva);end=data.index(b'\0',name)
            names.append(data[name:end].decode('ascii').lower());pos+=stride
    return names


def qt_files():
    """Keep actual widget modules/plugins plus their recursively required DLLs."""
    qt=ROOT/'.lite-site'/'PySide6'
    modules=('QtCore','QtGui','QtWidgets','QtNetwork','QtPrintSupport','QtSvg')
    plugins=('platforms','imageformats','styles','printsupport','iconengines','tls')
    keep={p.relative_to(qt).as_posix() for p in qt.glob('*.py')}
    seeds=[qt/(name+'.pyd') for name in modules]
    for folder in plugins:
        seeds.extend(p for p in (qt/'plugins'/folder).glob('*.dll') if p.name not in ('qminimal.dll','qoffscreen.dll'))
    dlls={p.name.lower():p for p in qt.glob('*.dll')}
    seeds.extend(p for name,p in dlls.items() if not name.startswith(('qt6','pyside6qml','opengl32sw')))
    pending=list(seeds)
    while pending:
        file=pending.pop();relative=file.relative_to(qt).as_posix()
        if relative in keep:continue
        keep.add(relative)
        pending.extend(dlls[name] for name in pe_imports(file) if name in dlls and dlls[name].relative_to(qt).as_posix() not in keep)
    keep.update(p.relative_to(qt).as_posix() for p in (qt/'translations').glob('*zh_CN*'))
    keep.update(p.relative_to(qt).as_posix() for p in qt.rglob('*') if p.is_file() and ('license' in p.name.lower() or 'copying' in p.name.lower()))
    return keep


def site_ignore(directory,names):
    relative=Path(directory).relative_to(ROOT/'.lite-site')
    skipped={name for name in names if name=='__pycache__' or name.endswith(('.pyc','.pyo'))}
    if not RELEASE:return skipped
    if relative.parts and relative.parts[0]=='PySide6':
        prefix=Path(*relative.parts[1:])
        for name in names:
            path=prefix/name;key=path.as_posix()
            if not any(item==key or item.startswith(key+'/') for item in QT_FILES):skipped.add(name)
    elif not any(part.endswith('.dist-info') for part in relative.parts):
        skipped.update(name for name in names if name in ('tests','__tests__') or name.endswith('.pyi'))
    return skipped


QT_FILES=qt_files() if RELEASE else set()


def copy_changed(source, target):
    source, target = Path(source), Path(target)
    if target.is_file():
        a, b = source.stat(), target.stat()
        if a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns:
            return str(target)
    return shutil.copy2(source, target)


def stage():
    if not (ROOT / '.lite-site' / 'faster_whisper').exists():
        raise RuntimeError('请先将 requirements-lite.txt 安装到 .lite-site。')
    if not (SOURCE / 'tools' / 'llama' / 'llama-server.exe').is_file():
        raise RuntimeError('请先运行 scripts/prepare_llama.py，准备内置本地推理引擎。')
    runtime = TARGET / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    for file in (SOURCE / 'runtime').iterdir():
        if file.is_file():
            copy_changed(file, runtime / file.name)
    (runtime / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n', encoding='utf8')
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    if RELEASE and (runtime/'Lib'/'site-packages').exists():
        raise RuntimeError('Release staging directory already exists; use a fresh .release directory to avoid stale dependencies.')
    shutil.copytree(ROOT / '.lite-site', runtime / 'Lib' / 'site-packages', dirs_exist_ok=True, ignore=site_ignore, copy_function=copy_changed)
    shutil.copytree(SOURCE / 'app', TARGET / 'app', dirs_exist_ok=True, ignore=ignore, copy_function=copy_changed)
    shutil.copytree(SOURCE / 'tools' / 'llama', TARGET / 'tools' / 'llama', dirs_exist_ok=True, copy_function=copy_changed)
    for name in ['听课.exe', 'Launcher.cs']:
        shutil.copy2(SOURCE / name, TARGET / name)
    (TARGET / '使用说明.txt').write_text(
        f'听课 Listenote {VERSION}\n\n'
        '完整解压后运行 听课.exe，无需安装 Python。\n'
        '首次转写请点击「语音模型与下载」，从国内 ModelScope 一键准备约 148 MB 的语音模型。\n'
        'AI 模型设置支持「一键从国内下载千问模型」，内置推理引擎，无需安装 Ollama。\n'
        '也可选择国内 DeepSeek，填写自己的密钥；地址和模型已预填。远程总结会发送转写原文，可能收费。\n'
        '语音模型和笔记保存在 %LOCALAPPDATA%\\Listenote；API 密钥仅本次运行保留。\n'
        '本地模型首次需要额外下载，下载后可以离线使用。轻量语音模型与原版 large-v3-turbo 精度不同，请核对重要内容。\n', encoding='utf8')
    if RELEASE:shutil.copy2(SOURCE/'使用说明.txt',TARGET/'使用说明.txt')
    shutil.copy2(ROOT / 'requirements-lite.txt', TARGET / 'requirements-lite.txt')
    (TARGET / 'THIRD-PARTY.txt').write_text(
        'Python: PSF License, runtime/LICENSE.txt\n'
        'PySide6 / Qt Essentials: LGPLv3/GPL/commercial, dynamically linked and replaceable.\n'
        'faster-whisper: MIT; CTranslate2: MIT; Whisper weights: MIT.\n'
        'PyAV bundles FFmpeg; license metadata is preserved in runtime/Lib/site-packages.\n'
        'python-docx, sounddevice, Requests and all dependencies retain their .dist-info license metadata.\n'
        'Noto Sans SC: SIL OFL, app/fonts/OFL.txt.\n'
        'llama.cpp: MIT, tools/llama/LICENSE.txt; optional Qwen models are downloaded from ModelScope at the user’s request.\n', encoding='utf8')
    shutil.copy2(SOURCE / 'models' / 'whisper' / 'LICENSE.txt', TARGET / 'app' / 'Whisper-LICENSE.txt')
    print(str(TARGET), flush=True)


def package():
    dest = ROOT / 'dist'
    dest.mkdir(exist_ok=True)
    archive = dest / f'Listenote-Windows-x64-v{VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for file in sorted(TARGET.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.pyc', '.log'):
                output.write(file, file.relative_to(TARGET.parent).as_posix())
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (dest / 'SHA256.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf8')
    print(f'{archive.name}: {archive.stat().st_size / 1_000_000:.1f} MB', flush=True)


if __name__ == '__main__':
    if '--package-only' not in sys.argv:
        stage()
    if '--zip' in sys.argv:
        package()
