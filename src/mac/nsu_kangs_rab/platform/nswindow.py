"""macOS 창(NSWindow)의 기본 크기 조절을 끈다(D-120). 표준 라이브러리 ctypes 만 쓴다(새 의존성 없음).

Qt(PySide6 6.12.0)는 `Qt.FramelessWindowHint` 창에도 styleMask 의 Resizable 비트를 켠다(실측 styleMask 14).
그러면 macOS 가 창의 모서리 · 가장자리 끌기를 Qt 보다 먼저 가로채 크기를 바꾸고, 그 입력은 앱에 오지 않는다.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

RESIZABLE = 1 << 3          # NSWindowStyleMaskResizable


def without_resizable(mask: int) -> int:
    return mask & ~RESIZABLE


def disable_native_resize(widget) -> bool:
    """`widget` 의 NSWindow 에서 Resizable 비트를 지운다. 바꾸었으면 True, 대상이 아니거나 실패하면 False(예외를 내지 않는다)."""
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return False
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend

        def sel(name: bytes):
            return objc.sel_registerName(name)

        send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        win = send(int(widget.winId()), sel(b"window"))
        if not win:
            return False
        send.restype = ctypes.c_ulong
        mask = send(win, sel(b"styleMask"))
        new = without_resizable(mask)
        if new == mask:
            return False
        send.restype, send.argtypes = None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        send(win, sel(b"setStyleMask:"), new)
        return True
    except Exception:
        return False


def style_mask(widget):
    """시험용: 현재 styleMask 를 반환한다(cocoa 가 아니면 None)."""
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return None
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend
        send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        win = send(int(widget.winId()), objc.sel_registerName(b"window"))
        if not win:
            return None
        send.restype = ctypes.c_ulong
        return send(win, objc.sel_registerName(b"styleMask"))
    except Exception:
        return None


_objc_lib = None


def _objc():
    """libobjc 를 프로세스당 한 번만 불러온다(마우스 이동마다 호출되는 `apply_cursor` 가 쓴다)."""
    global _objc_lib
    if _objc_lib is None:
        lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        _objc_lib = lib
    return _objc_lib


def apply_cursor(widget) -> bool:
    """`widget.setCursor` 로 정한 커서를 곧바로 시스템 커서로 적용한다(D-123, 결정 0086).
    Qt 는 커서를 NSView 의 커서 사각형 · `cursorUpdate` 로 적용하는데, 창에 들어올 때 한 번뿐이고 키 창이 아니면 적용되지 않으므로
    창 안에서 손잡이를 옮겨 다닐 때 바뀌지 않는다. 그래서 `QNSView.cursor` 를 `[NSCursor set]` 으로 직접 적용한다.
    앱이 활성 앱이 아닐 때의 커서는 이 함수의 범위가 아니다(결정 0086, 단계 3 뒤로 미룸). `cursor` 선택자가 뷰에 없으면 False 이다."""
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return False
        objc = _objc()
        send = objc.objc_msgSend
        view = int(widget.winId())
        sel = objc.sel_registerName
        send.restype, send.argtypes = ctypes.c_bool, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        if not send(view, sel(b"respondsToSelector:"), sel(b"cursor")):      # 없는 선택자를 보내면 ObjC 예외로 프로세스가 끝난다
            return False
        send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        cur = send(view, sel(b"cursor"))
        if not cur:
            return False
        send.restype = None
        send(cur, sel(b"set"))
        return True
    except Exception:
        return False


NONACTIVATING_PANEL = 1 << 7        # NSWindowStyleMaskNonactivatingPanel (NSPanel 에서만 유효)
PREVENTS_ACTIVATION = b"_setPreventsActivation:"      # 비공개 메서드(결정 0112)


def make_nonactivating(widget, pretend_missing: bool = False) -> dict:
    """액자 창을 앱을 활성화하지 않는 패널로 만든다(결정 0112, 기능 정의 FR-12). 네이티브 창이 (다시) 만들어질 때마다 호출한다.

    1. 창이 `NSPanel`(`Qt.Tool`)이면 `setHidesOnDeactivate:NO` 로 다른 앱이 앞일 때도 액자가 숨지 않게 하고, `setFloatingPanel:YES` 가
       바꾸는 창 수준은 Qt 가 준 값으로 되돌린다. 이것은 비공개 메서드가 없을 때도 한다(W-136 ③).
    2. 비공개 `-[NSWindow _setPreventsActivation:]` 가 있으면(`respondsToSelector:` 로 확인한다. 없는 선택자를 보내면 ObjC 예외로
       프로세스가 끝난다) styleMask 에 nonactivating 비트를 더하고 `YES` 로 호출한다. 없거나 `pretend_missing`(5-1절 개발 옵션)이면
       적용하지 않고 이전 동작(누르면 앱이 맨 앞이 된다)으로 남는다.
    3. 창을 다시 만들면 Resizable 비트가 되살아나므로 `disable_native_resize` 를 마지막에 다시 적용한다(D-120).

    반환: `{"native": bool, "class": str, "is_panel": bool, "has_method": bool, "applied": bool, "pretended": bool, ...}`.
    cocoa 가 아니면(`offscreen` 등) 아무것도 하지 않고 `native` 가 False 이다. 예외를 내지 않는다."""
    info = {"native": False, "class": "", "is_panel": False, "has_method": False, "applied": False,
            "pretended": bool(pretend_missing)}
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return info
        objc = _objc()
        send = objc.objc_msgSend
        sel = objc.sel_registerName

        def call(obj, name, restype=ctypes.c_void_p, *args):
            send.restype, send.argtypes = restype, [ctypes.c_void_p, ctypes.c_void_p] + [t for t, _ in args]
            return send(obj, sel(name), *[v for _, v in args])

        win = call(int(widget.winId()), b"window")
        if not win:
            return info
        info["native"] = True
        cls = call(win, b"className")
        name = call(cls, b"UTF8String", ctypes.c_char_p) if cls else None
        info["class"] = name.decode() if name else ""
        objc.objc_getClass.restype, objc.objc_getClass.argtypes = ctypes.c_void_p, [ctypes.c_char_p]
        info["is_panel"] = bool(call(win, b"isKindOfClass:", ctypes.c_bool, (ctypes.c_void_p, objc.objc_getClass(b"NSPanel"))))
        if info["is_panel"]:
            mask = call(win, b"styleMask", ctypes.c_ulong)
            level = call(win, b"level", ctypes.c_long)
            call(win, b"setHidesOnDeactivate:", None, (ctypes.c_bool, False))
            call(win, b"setFloatingPanel:", None, (ctypes.c_bool, True))
            call(win, b"setLevel:", None, (ctypes.c_long, level))
            info["has_method"] = bool(call(win, b"respondsToSelector:", ctypes.c_bool, (ctypes.c_void_p, sel(PREVENTS_ACTIVATION))))
            if info["has_method"] and not pretend_missing:
                call(win, b"setStyleMask:", None, (ctypes.c_ulong, mask | NONACTIVATING_PANEL))
                call(win, b"_setPreventsActivation:", None, (ctypes.c_bool, True))
                info["applied"] = bool(call(win, b"styleMask", ctypes.c_ulong) & NONACTIVATING_PANEL)
        disable_native_resize(widget)
    except Exception:  # noqa: BLE001 (액자는 이 호출이 실패해도 이전 동작으로 보인다)
        pass
    return info


_bg_cursor_done = False


def allow_background_cursor() -> bool:
    """이 프로세스가 활성 앱이 아닐 때도 `[NSCursor set]` 이 화면에 적용되도록 한다(D-145).
    WindowServer 연결의 비공개 속성 `SetsCursorInBackground` 를 켠다. 한 번만 설정하며 성공하면 True 이다.
    실패해도 예외를 던지지 않는다(커서는 앱이 활성일 때의 동작으로 남는다)."""
    global _bg_cursor_done
    if _bg_cursor_done:
        return True
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return False
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cg.CGSMainConnectionID.restype = ctypes.c_int
        cg.CGSSetConnectionProperty.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        cg.CGSSetConnectionProperty.restype = ctypes.c_int
        cid = cg.CGSMainConnectionID()
        key = cf.CFStringCreateWithCString(None, b"SetsCursorInBackground", 0x08000100)      # kCFStringEncodingUTF8
        true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
        _bg_cursor_done = cg.CGSSetConnectionProperty(cid, cid, key, true) == 0
        return _bg_cursor_done
    except Exception:  # noqa: BLE001
        return False


NORMAL_WINDOW_LEVEL = 0         # NSNormalWindowLevel (`Qt.Tool` 부동 패널은 3)


def window_level(widget):
    """`widget` 의 NSWindow 층(level)을 반환한다. cocoa 가 아니거나 실패하면 None."""
    try:
        from PySide6.QtGui import QGuiApplication
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return None
        objc = _objc()
        send = objc.objc_msgSend
        send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        win = send(int(widget.winId()), objc.sel_registerName(b"window"))
        if not win:
            return None
        send.restype = ctypes.c_long
        return int(send(win, objc.sel_registerName(b"level")))
    except Exception:  # noqa: BLE001
        return None


def set_window_level(widget, level: int):
    """`widget` 의 NSWindow 층을 `level` 로 바꾸고 바꾸기 전의 층을 반환한다(D-187, 결정 0173).
    cocoa 가 아니거나 실패하면 None 이며 아무것도 바꾸지 않는다. 예외를 내지 않는다."""
    try:
        before = window_level(widget)
        if before is None:
            return None
        objc = _objc()
        send = objc.objc_msgSend
        send.restype, send.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
        win = send(int(widget.winId()), objc.sel_registerName(b"window"))
        send.restype, send.argtypes = None, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        send(win, objc.sel_registerName(b"setLevel:"), int(level))
        return before
    except Exception:  # noqa: BLE001
        return None
