"""Шифрование таблицы соответствий на диске.

На Windows используется DPAPI (CryptProtectData): ключ привязан к учётной записи
Windows, расшифровать файл можно только под тем же пользователем на том же компьютере.
Пароль вводить не нужно, сторонние библиотеки не нужны.

Формат файла: строка-заголовок, затем данные в base64.
  NEMO-DPAPI1  — зашифровано DPAPI
  NEMO-PLAIN1  — без шифрования (не Windows: разработка и тесты)
Старые файлы session.json (чистый JSON) читаются и при следующем сохранении шифруются.
"""
from __future__ import annotations

import base64
import sys

HDR_DPAPI = b"NEMO-DPAPI1\n"
HDR_PLAIN = b"NEMO-PLAIN1\n"
_ENTROPY = b"Nemo session v1"


class VaultError(Exception):
    pass


def available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":  # pragma: no cover - проверяется в CI на Windows
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes) -> _Blob:
        buf = ctypes.create_string_buffer(data, len(data))
        b = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        b._buf = buf  # буфер живёт столько же, сколько структура
        return b

    def _take(blob: _Blob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))

    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _dpapi_protect(data: bytes) -> bytes:
        out = _Blob()
        ent = _blob(_ENTROPY)
        src = _blob(data)  # держим ссылку, пока идёт вызов
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(src), "Nemo", ctypes.byref(ent), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise VaultError("CryptProtectData не сработал")
        return _take(out)

    def _dpapi_unprotect(data: bytes) -> bytes:
        out = _Blob()
        ent = _blob(_ENTROPY)
        src = _blob(data)
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(src), None, ctypes.byref(ent), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise VaultError("Не удалось расшифровать: файл создан другим пользователем Windows "
                             "или на другом компьютере")
        return _take(out)


def seal(data: bytes) -> bytes:
    """Данные → содержимое файла."""
    if available():
        return HDR_DPAPI + base64.b64encode(_dpapi_protect(data))
    return HDR_PLAIN + base64.b64encode(data)


def unseal(raw: bytes) -> bytes:
    """Содержимое файла → данные. Чистый JSON старых версий возвращается как есть."""
    if raw.startswith(HDR_DPAPI):
        if not available():
            raise VaultError("Файл зашифрован DPAPI, открыть его можно только в Windows")
        return _dpapi_unprotect(base64.b64decode(raw[len(HDR_DPAPI):]))
    if raw.startswith(HDR_PLAIN):
        return base64.b64decode(raw[len(HDR_PLAIN):])
    return raw


def is_sealed(raw: bytes) -> bool:
    return raw.startswith(HDR_DPAPI)
