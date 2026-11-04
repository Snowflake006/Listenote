"""Keep source-directory launches on the complete bundled preview runtime."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def compatible_runtime(root):
    if importlib.util.find_spec('faster_whisper') is not None:
        return None
    preview = Path(root).parent / '.preview' / 'Listenote' / 'runtime'
    candidate = preview / ('pythonw.exe' if Path(sys.executable).name.lower() == 'pythonw.exe' else 'python.exe')
    if candidate.is_file() and (preview / 'Lib' / 'site-packages' / 'faster_whisper' / '__init__.py').is_file():
        if candidate.resolve() != Path(sys.executable).resolve():
            return candidate
    return None


def bootstrap(script):
    script = Path(script).resolve()
    candidate = compatible_runtime(script.parent.parent)
    if candidate:
        args = [str(candidate), str(script), *sys.argv[1:]]
        if candidate.name.lower() == 'pythonw.exe':
            subprocess.Popen(args, cwd=script.parent.parent, env=os.environ.copy(), creationflags=0x08000000)
            raise SystemExit(0)
        raise SystemExit(subprocess.call(args, cwd=script.parent.parent, env=os.environ.copy()))


def transcription_available(engine):
    names = ['faster_whisper', 'av', 'ctranslate2'] if engine == 'lite' else ['torch', 'transformers']
    return all(importlib.util.find_spec(name) is not None for name in names)


def legacy_root_available(root):
    root=Path(root)
    return all((root/name).is_file() for name in [
        'runtime/python.exe','runtime/Lib/site-packages/torch/__init__.py',
        'runtime/Lib/site-packages/transformers/__init__.py',
        'models/whisper/model.safetensors','tools/ffmpeg.exe'])


def find_legacy_root(root):
    root=Path(root).resolve()
    candidates=[root,root.parent/'Listenote']
    if len(root.parents)>1:candidates.append(root.parents[1]/'Listenote')
    for candidate in candidates:
        if legacy_root_available(candidate):return candidate
    return None
