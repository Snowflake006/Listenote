"""Public release checks only: no recordings, notes or API keys are sent."""
import re
import json
import time
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests
from PySide6.QtCore import QThread, Signal

from version import VERSION
VERSION_LABEL = VERSION
REPOSITORY_URL = 'https://github.com/Snowflake006/Listenote'
LATEST_URL = 'https://api.github.com/repos/Snowflake006/Listenote/releases/latest'
WEB_LATEST_URL = REPOSITORY_URL + '/releases/latest'
CHECK_INTERVAL = 3600
MANUAL_INTERVAL = 60


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value or '')
    return tuple(map(int, match.groups())) if match else None


def parse_release(data):
    if not isinstance(data, dict):
        raise ValueError('GitHub 版本信息格式不正确。')
    tag = data.get('tag_name', '')
    version = version_tuple(tag)
    if not version or data.get('draft') or data.get('prerelease'):
        raise ValueError('暂时没有可用的正式版本。')
    return {'tag': tag, 'newer': version > version_tuple(VERSION),
            'url': REPOSITORY_URL + '/releases/tag/' + tag,
            'notes': str(data.get('body', ''))[:6000]}


def load_cache(path):
    try:
        data = json.loads(Path(path).read_text('utf8')) if path else {}
        if not isinstance(data, dict):
            return {}
        # Reparse cached tags so a damaged cache cannot supply arbitrary links.
        if 'release' in data:
            data['release'] = parse_release({'tag_name': data['release']['tag'],
                                            'body': data['release'].get('notes', '')})
        for key in ('checked_at', 'api_retry_at', 'retry_at'):
            value = data.get(key, 0)
            if not isinstance(value, (int, float)) or not 0 <= value < 1e11:
                return {}
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def save_cache(path, data):
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False), 'utf8')
        temporary.replace(target)
    except OSError:
        pass


def retry_time(response, now):
    """Honor GitHub's server-provided cooldown, including shared-IP limits."""
    headers = response.headers
    try:
        delay = float(headers.get('Retry-After', 0))
    except (ValueError, TypeError):
        try:
            from email.utils import parsedate_to_datetime
            delay = parsedate_to_datetime(headers['Retry-After']).timestamp() - now
        except (ValueError, TypeError, KeyError):
            delay = 0
    try:
        reset = float(headers.get('X-RateLimit-Reset', 0)) - now
    except (ValueError, TypeError):
        reset = 0
    return now + min(86400, max(60, delay, reset, 3600 if not delay and not reset else 0))


def web_release():
    # /releases/latest resolves to the latest public non-prerelease tag without
    # consuming the REST API quota. No HTML parsing or third-party proxy needed.
    response = requests.get(WEB_LATEST_URL, headers={'User-Agent':'Listenote/' + VERSION},
                            timeout=(5, 10), stream=True)
    try:
        response.raise_for_status()
        url = urlparse(response.url)
        prefix = '/Snowflake006/Listenote/releases/tag/'
        if url.scheme != 'https' or url.netloc.lower() != 'github.com' or not url.path.startswith(prefix):
            raise ValueError('未能确认 GitHub 正式版本。')
        release = parse_release({'tag_name': unquote(url.path[len(prefix):])})
        release['source'] = 'github-web'
        return release
    finally:
        response.close()


def check_release(cache_path=None, manual=False):
    now = time.time()
    cache = load_cache(cache_path)
    cached = cache.get('release')
    interval = MANUAL_INTERVAL if manual else CHECK_INTERVAL
    if cached and now - cache.get('checked_at', 0) < interval:
        return dict(cached, cached=True, stale=False)
    if now < cache.get('retry_at', 0):
        if cached:
            return dict(cached, cached=True, stale=True)
        raise RuntimeError('更新服务暂时不可用，已暂停重复请求；稍后会自动重试，也可打开 GitHub 发布页查看。')
    try:
        if now < cache.get('api_retry_at', 0):
            release = web_release()
        else:
            headers = {'Accept':'application/vnd.github+json', 'User-Agent':'Listenote/' + VERSION}
            if cached and cache.get('etag'):
                headers['If-None-Match'] = cache['etag']
            try:
                response = requests.get(LATEST_URL, headers=headers, timeout=(5, 10))
                try:
                    if response.status_code in (403, 429):
                        cache['api_retry_at'] = retry_time(response, now)
                        raise requests.HTTPError('REST API cooldown')
                    if response.status_code == 304 and cached:
                        release = cached
                    else:
                        response.raise_for_status()
                        release = parse_release(response.json())
                        cache['etag'] = response.headers.get('ETag', '')
                finally:
                    response.close()
            except (requests.RequestException, ValueError):
                cache['api_retry_at'] = max(cache.get('api_retry_at', 0), now + 300)
                release = web_release()
        cache.update(release=release, checked_at=now, retry_at=0)
        save_cache(cache_path, cache)
        return dict(release, cached=False, stale=False)
    except (requests.RequestException, ValueError):
        cache['retry_at'] = now + 300
        save_cache(cache_path, cache)
        if cached:
            return dict(cached, cached=True, stale=True)
        raise RuntimeError('暂时无法连接 GitHub，已暂停重复请求；稍后会自动重试，也可打开发布页查看。')


class UpdateWorker(QThread):
    checked = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None, cache_path=None, manual=False):
        super().__init__(parent)
        self.cache_path, self.manual = cache_path, manual

    def run(self):
        try:
            self.checked.emit(check_release(self.cache_path, self.manual))
        except RuntimeError as exc:
            self.failed.emit(str(exc))
