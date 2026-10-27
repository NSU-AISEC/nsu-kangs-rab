"""전역 단축키의 등록과 macOS 시스템 단축키 조회 (결정 0141, 조사 `docs/research/capture-feasibility.md` 의 "2026-10-22 16:47" 절).

- `GlobalHotkeys`: Carbon `RegisterEventHotKey` 로 키를 등록하고 눌림을 콜백으로 알린다. 접근성 · 입력 모니터링 권한이 필요 없다
  (권한이 모두 없는 프로세스에서 등록 status 0 과 처리 호출을 실측했다). 눌림은 Carbon 이벤트 루프(Qt 의 NSApplication)에서
  메인 스레드로 온다. 시험은 `backend` 를 갈아 끼워 실제 등록 없이 호출한다.
- `system_shortcuts()`: `CopySymbolicHotKeys` 가 반환하는 켜진 시스템 단축키 (가상 키 코드, Carbon 수식 키) 집합. 읽지 못하면 None.
- `FIXED_SYSTEM_SHORTCUTS`: 읽기에 실패했을 때만 쓰는 닫힌 목록.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable, Dict, Optional, Set, Tuple

CMD, SHIFT, OPT, CTRL = 256, 512, 2048, 4096

# 읽기에 실패했을 때의 목록 (가상 키 코드, Carbon 수식 키) → 이름 키(KEY-3N 의 항목)
FIXED_SYSTEM_SHORTCUTS: Dict[Tuple[int, int], str] = {
    (49, CMD): "spotlight", (48, CMD): "switcher", (123, CTRL): "spaces", (124, CTRL): "spaces",
    (20, CMD | SHIFT): "screenshot", (21, CMD | SHIFT): "screenshot", (23, CMD | SHIFT): "screenshot",
}

_SIGNATURE = int.from_bytes(b"nkrh", "big")


def system_shortcuts() -> Optional[Set[Tuple[int, int]]]:
    """켜져 있는 시스템 단축키의 (가상 키 코드, Carbon 수식 키). macOS 밖이거나 읽기에 실패하면 None."""
    if sys.platform != "darwin":
        return None
    try:
        hit = ctypes.CDLL(ctypes.util.find_library("Carbon"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        hit.CopySymbolicHotKeys.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        hit.CopySymbolicHotKeys.restype = ctypes.c_int32
        arr = ctypes.c_void_p()
        if hit.CopySymbolicHotKeys(ctypes.byref(arr)) != 0 or not arr:
            return None
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        def num(d, name: bytes):
            k = ctypes.c_void_p(cf.CFStringCreateWithCString(None, name, 0x08000100))
            v = cf.CFDictionaryGetValue(d, k)
            cf.CFRelease(k)
            if not v:
                return None
            out = ctypes.c_int32()
            return out.value if cf.CFNumberGetValue(v, 3, ctypes.byref(out)) else None

        result: Set[Tuple[int, int]] = set()
        for i in range(cf.CFArrayGetCount(arr)):
            d = cf.CFArrayGetValueAtIndex(arr, i)
            k = ctypes.c_void_p(cf.CFStringCreateWithCString(None, b"enabled", 0x08000100))
            en = cf.CFDictionaryGetValue(d, k)
            cf.CFRelease(k)
            if not en or not cf.CFBooleanGetValue(en):
                continue
            code, mods = num(d, b"keyCode"), num(d, b"modifiers")
            if code is None or code == 65535:           # 65535 는 키가 없는 항목
                continue
            result.add((code, (mods or 0) & (CMD | SHIFT | OPT | CTRL)))
        cf.CFRelease(arr)
        return result
    except Exception:                               # noqa: BLE001 (읽기 실패는 닫힌 목록으로 대신한다)
        return None


class _CarbonBackend:
    """Carbon 등록의 실제 호출. `register` 는 (등록 번호 또는 None, status)를 반환한다."""

    def __init__(self, on_fired: Callable[[int], None]):
        self._carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))
        c = self._carbon

        class _EventType(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class _HotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        self._HotKeyID = _HotKeyID
        handler_t = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        self._refs: Dict[int, ctypes.c_void_p] = {}

        def fired(_call, event, _data):
            hk = _HotKeyID()
            if c.GetEventParameter(event, int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big"), None,
                                   ctypes.sizeof(hk), None, ctypes.byref(hk)) == 0 and hk.signature == _SIGNATURE:
                try:
                    on_fired(int(hk.id))
                except Exception:                   # noqa: BLE001 (콜백 오류가 Carbon 이벤트 처리를 끊지 않게 한다)
                    pass
            return 0

        self._handler = handler_t(fired)             # 참조를 유지한다
        self._installed = c.InstallEventHandler(ctypes.c_void_p(c.GetApplicationEventTarget()), self._handler, 1,
                                                ctypes.byref(_EventType(int.from_bytes(b"keyb", "big"), 5)), None, None)

    def register(self, ident: int, vk: int, mods: int) -> int:
        if self._installed != 0:
            return int(self._installed)
        ref = ctypes.c_void_p()
        st = self._carbon.RegisterEventHotKey(vk, mods, self._HotKeyID(_SIGNATURE, ident),
                                              ctypes.c_void_p(self._carbon.GetApplicationEventTarget()), 0, ctypes.byref(ref))
        if st == 0:
            self._refs[ident] = ref
        return int(st)

    def unregister(self, ident: int) -> None:
        ref = self._refs.pop(ident, None)
        if ref is not None:
            self._carbon.UnregisterEventHotKey(ref)


class GlobalHotkeys:
    """이름으로 구분하는 전역 키 등록기. `set(name, vk, mods)` 가 등록하고 status 를 반환한다(0 이 성공).
    같은 이름은 먼저 해제한 뒤 다시 등록한다. 등록은 이 객체를 만든 프로세스의 메인 스레드에서 한다."""

    def __init__(self, callback: Callable[[str], None], backend=None):
        self._callback = callback
        self._ids: Dict[str, int] = {}
        self._names: Dict[int, str] = {}
        self._next = 1
        self._backend = backend if backend is not None else _CarbonBackend(self._fired)

    def _fired(self, ident: int) -> None:
        name = self._names.get(ident)
        if name is not None:
            self._callback(name)

    def set(self, name: str, vk: int, mods: int) -> int:
        self.clear(name)
        ident = self._next
        self._next += 1
        st = self._backend.register(ident, vk, mods)
        if st == 0:
            self._ids[name] = ident
            self._names[ident] = name
        return st

    def clear(self, name: str) -> None:
        ident = self._ids.pop(name, None)
        if ident is not None:
            self._names.pop(ident, None)
            self._backend.unregister(ident)

    def clear_all(self) -> None:
        for name in list(self._ids):
            self.clear(name)

    def registered(self, name: str) -> bool:
        return name in self._ids
