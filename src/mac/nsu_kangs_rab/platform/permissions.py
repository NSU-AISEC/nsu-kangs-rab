"""macOS 권한의 상태를 읽기만 한다 (AC-FR14-10, 결정 0064 · 0065).

권한 요청 창을 부르지 않는다: 화면 기록은 `CGPreflightScreenCaptureAccess`(요청하는 `CGRequestScreenCaptureAccess` 가 아니다),
마이크는 `AVCaptureDevice authorizationStatusForMediaType:`(요청하는 `requestAccess…` 가 아니다)만 호출한다.
값은 `허용` · `허용되지 않음` · `아직 묻지 않음` · `확인할 수 없음` 이다. 조회가 실패하면 `확인할 수 없음` 이다.
"""
from __future__ import annotations
from ..core.i18n import t as _t

import ctypes
import ctypes.util
import sys
from typing import Dict

GRANTED, DENIED, NOT_ASKED, UNKNOWN = "허용", _t("perm.m_448"), _t("perm.m_449"), _t("perm.m_450")
KEYS = ("screen_recording", "system_audio", "microphone")


def _screen_recording() -> str:
    lib = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    fn = lib.CGPreflightScreenCaptureAccess
    fn.restype = ctypes.c_bool
    return GRANTED if fn() else DENIED


def _microphone() -> str:
    objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    ctypes.CDLL("/System/Library/Frameworks/AVFoundation.framework/AVFoundation")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    cls_dev = objc.objc_getClass(b"AVCaptureDevice")
    cls_str = objc.objc_getClass(b"NSString")
    send.restype = ctypes.c_void_p
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
    media = send(cls_str, objc.sel_registerName(b"stringWithUTF8String:"), b"soun")
    send.restype = ctypes.c_long
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    status = send(cls_dev, objc.sel_registerName(b"authorizationStatusForMediaType:"), media)
    return {0: NOT_ASKED, 1: DENIED, 2: DENIED, 3: GRANTED}.get(int(status), UNKNOWN)


def query_status() -> Dict[str, str]:
    """`{screen_recording, system_audio, microphone}` → 상태 문구. 시스템 사운드는 화면 기록과 같은 권한이다(결정 0065)."""
    out = {k: UNKNOWN for k in KEYS}
    if sys.platform != "darwin":
        return out
    try:
        out["screen_recording"] = out["system_audio"] = _screen_recording()
    except Exception:
        pass
    try:
        out["microphone"] = _microphone()
    except Exception:
        pass
    return out
