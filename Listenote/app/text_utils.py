"""Convert recognition output to Simplified Chinese without network dependencies."""
import ctypes
from ctypes import wintypes
from functools import lru_cache
import sys


@lru_cache(maxsize=256)
def to_simplified(text):
    if not text:
        return text
    if sys.platform != 'win32':
        from opencc import OpenCC
        return OpenCC('t2s').convert(text)
    mapping = ctypes.WinDLL('kernel32', use_last_error=True).LCMapStringEx
    mapping.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_int,
                        wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t]
    mapping.restype = ctypes.c_int
    count = mapping('zh-CN', 0x02000000, text, -1, None, 0, None, None, 0)
    if not count:
        raise ctypes.WinError(ctypes.get_last_error())
    result = ctypes.create_unicode_buffer(count)
    if not mapping('zh-CN', 0x02000000, text, -1, result, count, None, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return result.value


def simplify_note(data):
    changed = False
    for key in ('transcript', 'summary', 'ai_summary'):
        old = data.get(key, '')
        new = to_simplified(old)
        if old != new:
            data[key] = new
            changed = True
    for segment in data.get('segments', []):
        old = segment.get('text', '')
        segment['text'] = to_simplified(old)
        changed = changed or old != segment['text']
    return changed
