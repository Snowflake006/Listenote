"""Optional downloads: resumable speech weights and official Ollama setup."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import quote

import requests
from ai_summary import Cancelled

SPEECH_REPO = 'Systran/faster-whisper-base'
SPEECH_FILES = {'config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'}
OLLAMA_URL = 'http://127.0.0.1:11434'
OLLAMA_INSTALLER = 'https://ollama.com/download/OllamaSetup.exe'
LOCAL_MODELS = [('通义千问 Qwen3 · 轻量（约 523 MB）', 'qwen3:0.6b'),
                ('通义千问 Qwen3 · 进阶（约 2.5 GB）', 'qwen3:4b')]


def check_cancel(cancel):
    if cancel():
        raise Cancelled()


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download_file(url, target, progress, cancel, expected_sha=None, expected_size=None):
    """Resume only confirmed byte ranges, validate before atomic replacement."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and expected_sha and sha256(target) == expected_sha:
        return
    part = target.with_suffix(target.suffix + '.part')
    offset = part.stat().st_size if part.exists() else 0
    check_cancel(cancel)
    with requests.get(url, headers={'Range': f'bytes={offset}-'} if offset else {},
                      stream=True, timeout=(15, 30)) as response:
        if response.status_code == 416 and expected_size and offset == expected_size:
            pass
        else:
            response.raise_for_status()
            if offset and response.status_code == 206:
                if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise RuntimeError('下载服务器返回了不匹配的续传位置，请稍后重试。')
            elif offset:
                offset = 0
            total = expected_size or (int(response.headers.get('Content-Length', 0)) + offset)
            with part.open('ab' if offset else 'wb') as stream:
                for chunk in response.iter_content(256 * 1024):
                    check_cancel(cancel)
                    if not chunk:
                        continue
                    stream.write(chunk)
                    offset += len(chunk)
                    progress(int(offset * 100 / total) if total else -1,
                             f'{offset / 1_000_000:.1f} / {total / 1_000_000:.1f} MB' if total else f'{offset / 1_000_000:.1f} MB')
    check_cancel(cancel)
    if expected_size and part.stat().st_size != expected_size:
        raise RuntimeError('文件尚未下载完整，已保留下载进度，再次点击即可继续。')
    if expected_sha and sha256(part) != expected_sha:
        part.unlink()
        raise RuntimeError('下载文件校验失败，未安装；请重新下载。')
    part.replace(target)


def speech_folder(data):
    return Path(data) / 'models' / 'faster-whisper-base'


def speech_ready(data):
    folder = speech_folder(data)
    try:
        manifest = json.loads((folder / 'ready.json').read_text('utf8'))
        return set(manifest) == SPEECH_FILES and all(
            (folder / name).stat().st_size == meta['size'] for name, meta in manifest.items())
    except (OSError, ValueError, TypeError, KeyError):
        return False


def prepare_speech(data, progress, cancel):
    progress(-1, '正在连接国内 ModelScope 下载源…')
    response = requests.get(f'https://modelscope.cn/api/v1/models/{SPEECH_REPO}/repo/files',
                            params={'Revision': 'master', 'Recursive': 'true'}, timeout=(15, 30))
    response.raise_for_status()
    files = [item for item in response.json()['Data']['Files'] if item['Path'] in SPEECH_FILES]
    if {item['Path'] for item in files} != SPEECH_FILES:
        raise RuntimeError('国内下载源暂时没有完整模型，请稍后重试。')
    folder = speech_folder(data)
    manifest = {}
    total = sum(item['Size'] for item in files)
    completed = 0
    for item in files:
        check_cancel(cancel)
        name, size = item['Path'], item['Size']
        url = (f'https://modelscope.cn/api/v1/models/{SPEECH_REPO}/repo?Revision='
               f'{quote(item["Revision"], safe="")}&FilePath={quote(name, safe="")}')
        before = completed
        def report(percent, text):
            current = size * max(percent, 0) / 100
            progress(int((before + current) * 100 / total), f'正在下载语音模型 · {name} · {text}')
        download_file(url, folder / name, report, cancel, item['Sha256'], size)
        manifest[name] = {'size': size, 'sha256': item['Sha256']}
        completed += size
    check_cancel(cancel)
    temp = folder / 'ready.tmp'
    temp.write_text(json.dumps(manifest), 'utf8')
    temp.replace(folder / 'ready.json')
    progress(100, '语音模型已准备好，之后可离线转写。')


def ollama_available():
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(OLLAMA_URL + '/api/tags', timeout=(2, 3))
            return response.status_code == 200 and isinstance(response.json().get('models'), list)
    except (requests.RequestException, ValueError):
        return False


def find_ollama():
    found = shutil.which('ollama')
    if found:
        return Path(found)
    for path in [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/ollama.exe',
                 Path(os.environ.get('ProgramFiles', '')) / 'Ollama/ollama.exe']:
        if path.is_file():
            return path
    return None


def verify_installer(path):
    # Pass the file as an environment variable; never interpolate paths into code.
    env = dict(os.environ, LISTENOTE_INSTALLER=str(Path(path).resolve()))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "$s=Get-AuthenticodeSignature -LiteralPath $env:LISTENOTE_INSTALLER; "
        "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'Ollama'){exit 0}else{exit 1}"],
        env=env, capture_output=True, creationflags=0x08000000)
    if result.returncode:
        raise RuntimeError('Ollama 安装包的数字签名未通过验证，已停止安装。请稍后重试或使用官网安装包。')


def pull_model(model, progress, cancel):
    with requests.Session() as session:
        session.trust_env = False
        with session.post(OLLAMA_URL + '/api/pull', json={'model': model, 'stream': True},
                          stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            success = False
            for raw in response.iter_lines():
                check_cancel(cancel)
                if not raw:
                    continue
                item = json.loads(raw)
                if item.get('error'):
                    raise RuntimeError('模型下载失败。已下载的部分会由 Ollama 保留，请再次点击重试。')
                total = item.get('total', 0)
                complete = item.get('completed', 0)
                progress(int(complete * 100 / total) if total else -1,
                         f'正在准备 {model} · {complete / 1_000_000:.0f} / {total / 1_000_000:.0f} MB'
                         if total else '正在校验并载入本地模型…')
                if item.get('status') == 'success':
                    success = True
            if not success:
                raise RuntimeError('模型尚未准备完成，请再次点击重试。')


def prepare_ollama(data, model, progress, cancel):
    if model not in {item[1] for item in LOCAL_MODELS}:
        raise ValueError('请选择可一键安装的本地模型。')
    progress(-1, '正在检查本地模型环境…')
    if not ollama_available():
        executable = find_ollama()
        if executable is None:
            installer = Path(data) / 'downloads' / 'OllamaSetup.exe'
            if not installer.is_file():
                download_file(OLLAMA_INSTALLER, installer,
                              lambda percent, text: progress(percent, '正在下载 Ollama · ' + text), cancel)
            check_cancel(cancel)
            progress(-1, '正在验证并安装 Ollama，请稍候…')
            try:
                verify_installer(installer)
            except RuntimeError:
                installer.unlink(missing_ok=True)
                raise
            process = subprocess.Popen([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                                        '/NORESTART', '/SP-'], creationflags=0x08000000)
            while process.poll() is None:
                # Never terminate an installer mid-write. Cancellation takes effect after installation.
                progress(-1, '正在安装 Ollama，请稍候（安装结束后可停止）…')
                time.sleep(1)
            if process.returncode != 0:
                raise RuntimeError('Ollama 安装未完成，请重试；若 Windows 显示确认窗口，请按提示完成。')
            executable = find_ollama()
        check_cancel(cancel)
        if not ollama_available() and executable:
            subprocess.Popen([str(executable), 'serve'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=0x08000000)
        for _ in range(45):
            check_cancel(cancel)
            if ollama_available():
                break
            time.sleep(1)
        else:
            raise RuntimeError('Ollama 已安装，但服务尚未启动。请重启软件后再次点击一键准备。')
    check_cancel(cancel)
    pull_model(model, progress, cancel)
    progress(100, '已准备好，可以直接使用本地 AI 总结。')
