"""Bundled llama.cpp engine; Qwen weights are fetched from domestic ModelScope."""
import atexit
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time

import requests
from resources import download_file, check_cancel

QWEN_MODELS = [
    ('通义千问 Qwen3 · 轻量（约 640 MB）', 'qwen3-0.6b'),
    ('通义千问 Qwen3 · 进阶（约 1.8 GB）', 'qwen3-1.7b'),
]
CATALOG = {
    'qwen3-0.6b': ('Qwen/Qwen3-0.6B-GGUF', 'Qwen3-0.6B-Q8_0.gguf'),
    'qwen3-1.7b': ('Qwen/Qwen3-1.7B-GGUF', 'Qwen3-1.7B-Q8_0.gguf'),
}
_process = None
_model = None
_connection = None
_lock = threading.Lock()


def model_path(data, model):
    if model not in CATALOG:
        raise ValueError('请选择列表中的千问模型。')
    return Path(data) / 'models' / 'qwen' / CATALOG[model][1]


def model_ready(data, model):
    try:
        path = model_path(data, model)
        meta = json.loads(path.with_suffix('.ready.json').read_text('utf8'))
        return path.stat().st_size == meta['size'] and meta['model'] == model
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare_qwen(data, model, progress, cancel):
    repo, filename = CATALOG[model]
    progress(-1, '正在连接国内 ModelScope，准备下载千问模型…')
    response = requests.get(f'https://modelscope.cn/api/v1/models/{repo}/repo/files',
                            params={'Revision': 'master', 'Recursive': 'true'}, timeout=(15, 30))
    response.raise_for_status()
    entries = [entry for entry in response.json()['Data']['Files'] if entry['Path'] == filename]
    if len(entries) != 1:
        raise RuntimeError('国内源暂时没有所选模型，请稍后重试。')
    entry = entries[0]
    url = f'https://modelscope.cn/api/v1/models/{repo}/repo?Revision={entry["Revision"]}&FilePath={filename}'
    path = model_path(data, model)
    download_file(url, path, lambda n, text: progress(n, '正在下载千问模型 · ' + text),
                  cancel, entry['Sha256'], entry['Size'])
    check_cancel(cancel)
    temp = path.with_suffix('.ready.tmp')
    temp.write_text(json.dumps({'model': model, 'size': entry['Size'], 'sha256': entry['Sha256']}), 'utf8')
    temp.replace(path.with_suffix('.ready.json'))
    progress(100, '千问模型已准备好，无需安装 Ollama，可以离线总结。')


def close_engine():
    global _process, _model, _connection
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)
    _process, _model, _connection = None, None, None


def ensure_engine(data, root, model, progress, cancel):
    global _process, _model, _connection
    with _lock:
        check_cancel(cancel)
        if _process is not None and _process.poll() is None and _model == model:
            return _connection
        close_engine()
        if not model_ready(data, model):
            raise RuntimeError('请先在 AI 模型设置中点击“一键下载千问模型”。')
        executable = Path(root) / 'tools' / 'llama' / 'llama-server.exe'
        if not executable.is_file():
            raise RuntimeError('缺少内置推理引擎，请完整解压轻量版程序。')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        key = secrets.token_urlsafe(32)
        url = f'http://127.0.0.1:{port}/v1'
        progress('正在加载本地千问模型…')
        _process = subprocess.Popen([
            str(executable), '--model', str(model_path(data, model)), '--alias', model,
            '--host', '127.0.0.1', '--port', str(port), '--api-key', key,
            '--ctx-size', '8192', '--parallel', '1', '--threads', str(max(1, min(8, (os.cpu_count() or 4)//2))),
            '--jinja', '--no-webui',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        try:
            with requests.Session() as session:
                session.trust_env = False
                for _ in range(120):
                    check_cancel(cancel)
                    if _process.poll() is not None:
                        raise RuntimeError('本地引擎启动失败，请确认模型完整且电脑有足够内存。')
                    try:
                        response = session.get(url.removesuffix('/v1') + '/health',
                                               headers={'Authorization': 'Bearer ' + key}, timeout=(1, 2))
                        if response.status_code == 200:
                            _model, _connection = model, (url, key)
                            return _connection
                    except requests.RequestException:
                        pass
                    time.sleep(.5)
            raise RuntimeError('本地模型加载超时，请关闭其他占用内存的程序后重试。')
        except BaseException:
            close_engine()
            raise


atexit.register(close_engine)
