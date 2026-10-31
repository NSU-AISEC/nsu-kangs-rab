"""앱 조립 (K-20; 기술 계획 2절 `app.py` 의 `AppController` · `main()`).

핵심 모듈(`core.runtime`)을 만들고 화면(`MainShell` · `MenuController`)과 연결한다. 이 모듈이 하는 일:

- 시작: 개발 옵션 파싱, 설정 · 이벤트 로그 · 고아 프로세스 정리, `claude` 탐색, 화면 구성.
- 세션 시작 화면의 값으로 세션 하나를 만들고(`runtime_builder`) 상주 프로세스를 시작한다. 시작은 모델 호출이 아니다.
- 단추 · 메뉴 · 입력 → `SessionRuntime.submit` · `trigger`. 입력창의 글은 `core.inputparse` 가 해석한다.
- 다른 스레드의 콜백(`on_card` · `on_notice` · STT 조각)은 `UiBridge` 의 큐 신호로만 화면에 넘긴다.
  `RequestManager` 의 콜백은 잠금 안에서 호출되므로 막는 연결을 쓰지 않고 그 안에서 매니저를 다시 호출하지 않는다(X6).
- 시험 연결점: `--dev-control` 제어 파일, `--dev-audio-file`(음성 파일 입력), `--dev-appearance`.

세션 종료 흐름(정리 문서, K-16)과 액자 창 · 폴더 감시(K-14)는 이 단계에 없다. 종료는 기록을 닫고 앱을 끝내는 최소 흐름이다.
"""
from __future__ import annotations
from ..core.i18n import t as _t
from ..core import i18n, labels, languages

import json
import os
import sys
import gc
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLayout, QVBoxLayout

from ..core import appstate, claude_locator, cleanup_doc, devopts, diagram, endflow, error_text, framegeom, imageinfo, inputparse, llm, resources, settings
from ..core import requests as R
from ..core.api_key_store import ApiKeyStore
from ..core.children import ChildRegistry, cleanup_orphans, remove_stale_prompt_files
from ..core.context import ContextStore, Limits
from ..core.eventlog import EventLog
from ..core.procs import Procs
from ..core.endflow import EndFlow
from ..core.oneshot import OneShot
from ..core.runtime import AUTH_BY_PROVIDER, build_runtime, source_display
from ..core.transcript import hms
from ..core.types import ERROR_KINDS
from ..core.types import SOURCE_CAPTURE, SOURCE_DROP, SOURCE_PASTE
from ..core.materials_view import MaterialsModel
from ..platform import hotkeys as hotkeys_mod
from ..platform import nswindow
from . import frame as frame_mod, keyspec, keytable, menus, screens
from . import shell as shell_mod
from .materials import MaterialsPanel
from .appearance import AppearanceApplier
from .enddialog import EndDialog
from .shell import MainShell

COLLECT_RUNNING, COLLECT_NO_INPUT, COLLECT_STOPPED = appstate.COLLECT_RUNNING, appstate.COLLECT_NO_INPUT, appstate.COLLECT_STOPPED
COLLECT_PAUSED, COLLECT_BEFORE = appstate.COLLECT_PAUSED, appstate.COLLECT_BEFORE
CONTROL_POLL_MS = 200          # 제어 파일 주기(계획 5절)
STATUS_REFRESH_MS = 1000
LEVEL_REFRESH_MS = 100       # 입력 레벨 막대만의 갱신 주기(AC-FR3-10: 1초 안에 따라가야 한다, D-069)
NOTICE_MS = 6000
CAPTURE_SETTLE_MS = 50           # 손잡이를 지운 모습이 화면에 반영되기를 기다리는 시간(후보, 3프레임 정도)
START_CHECK_MS = 30000        # init 의 인증 출처 확인을 기다리는 시간(후보)

# 다이어그램 실패 사유의 표시 문구(닫힌 집합)
DIAGRAM_FAIL_TEXT = {
    "timeout": _t("ctl.diagram_fail_text"),
    "no_file": _t("ctl.diagram_fail_text_2"),
    "auth": _t("ctl.diagram_fail_text_3"),
    "no_claude": _t("ctl.diagram_fail_text_4"),
    "process_exit": _t("ctl.diagram_fail_text_5"),
}

def diagram_fail_text(kind) -> str:
    """실패 사유 문구. 닫힌 표에 없는 오류 종류는 요청 카드와 같은 사유 문구를 쓴다(네트워크 · 사용 한도 등, D-050)."""
    k = kind or ""
    if k in DIAGRAM_FAIL_TEXT:
        return DIAGRAM_FAIL_TEXT[k]
    if k in error_text.ERROR_TEXT:
        return _t("ctl.diagram_fail_text_217") + error_text.reason_text(k)
    return _t("ctl.diagram_fail_text_218")


# 시스템 사운드 수집의 화면 기록 권한이 없을 때 오류 카드의 상세(권한 이름 + 허용하는 곳)
PERMISSION_SCREEN_TEXT = _t("ctl.permission_screen_text")      # 허용하는 곳과 조치는 FR-9 의 `permission` 조치 문장이 맡는다

# `RequestManager` · 제어 알림의 표시 문구. 닫힌 집합이며 본문 · 키는 담지 않는다.
NOTICE_TEXT = {
    "trigger_busy": _t("ctl.notice_text"),
    "history_compacting": _t("ctl.notice_text_2"),
    "history_compacted": _t("ctl.notice_text_3"),
    "restarted": _t("ctl.notice_text_4"),
}


def discard_session_folder(folder) -> bool:
    """앱이 막 만든 세션 폴더를 지운다. 앱이 만든 파일만 있을 때만 지우며 그 밖의 파일이 있으면 그대로 둔다."""
    f = Path(folder)
    own = {"session.jsonl"}      # 결정 0196: 앱은 이 파일만 만든다(옛 폴더의 session.md · transcript.txt 는 앱이 만든 것으로 보지 않아 지우지 않는다)
    try:
        names = set(os.listdir(f))
        cap = f / "captures"
        if cap.is_dir() and os.listdir(cap):
            return False
        if not names <= own | {"captures"}:
            return False
        for n in names & own:
            (f / n).unlink()
        if cap.is_dir():
            cap.rmdir()
        f.rmdir()
        return True
    except OSError:
        return False


@dataclass
class Deps:
    """바꿀 수 있는 외부 의존. 시험은 가짜를 주입하고, 운영은 기본값을 쓴다."""
    environ: Optional[Mapping] = None
    find_claude: Callable = claude_locator.find_claude
    login_shell: Optional[Callable] = None
    key_store_factory: Optional[Callable] = None        # (account) -> ApiKeyStore
    runtime_builder: Callable = build_runtime
    model_factory: Optional[Callable] = None            # `build_runtime(model_factory=)`
    stt_helper: Optional[Callable] = None               # () -> (앞에 붙일 명령 목록, 추가 인자). 음성 인식 보조 프로세스(`stt_speech`)를 시험이 가짜로 바꾼다(결정 0162)
    list_locales: Optional[Callable] = None             # (명령 목록, 시간 제한 초) -> 로캘 목록 | None. 설정의 지원 언어 조회(`--list-locales`)를 시험이 가로챈다
    mic_factory: Optional[Callable] = None              # (eventlog) -> 음성 소스
    system_sound_factory: Optional[Callable] = None     # (eventlog, helper_path) -> 음성 소스(시스템 사운드, 결정 0065)
    scaler: Optional[Callable] = None                   # 이미지 축소(`QtScaler`)
    open_url: Optional[Callable] = None                 # (QUrl) -> bool
    permission_status: Optional[Callable] = None        # () -> {screen_recording · system_audio · microphone: 상태 문구}. 읽기만 한다(AC-FR14-10)
    capture_runner: Optional[Callable] = None           # (cmd, timeout_s) -> (종료 코드, stderr). 액자 캡처의 `screencapture` 실행(없으면 `ProcsRunner`)
    screen_rects: Optional[Callable] = None             # () -> [framegeom.Rect]. 화면 가용 영역(첫째가 주 화면). 없으면 Qt 의 화면
    hotkeys_factory: Optional[Callable] = None          # (callback) -> 전역 키 등록기(`platform.hotkeys.GlobalHotkeys` 와 같은 `set` · `clear_all`). 시험은 가짜를 준다
    system_shortcuts: Optional[Callable] = None         # () -> {(가상 키 코드, Carbon 수식 키)} 또는 None. 켜진 macOS 시스템 단축키(결정 0141)


class _HotkeyBridge(QObject):
    """전역 키 눌림을 Carbon 콜백에서 Qt 이벤트 루프로 넘긴다."""
    fired = Signal(str)


class _EndBridge(QObject):
    """정리 문서의 완료를 작업 스레드에서 Qt 스레드로 넘긴다(X6)."""
    done = Signal(object)


class _DiagramBridge(QObject):
    """다이어그램 결과를 작업 스레드에서 Qt 스레드로 넘긴다(X6)."""
    done = Signal(object)


class _StartBridge(QObject):
    """세션 시작 확인(init 의 인증 출처)의 결과를 모델 스레드에서 Qt 스레드로 넘긴다(X6)."""
    ok = Signal(object)
    failed = Signal(str, str)


class _CaptureBridge(QObject):
    """액자 캡처의 결과를 작업 스레드에서 Qt 스레드로 넘긴다(X6)."""
    done = Signal(object)
    failed = Signal(str, str)


class _LocalesBridge(QObject):
    """설정의 지원 언어 조회(작업 스레드)의 결과를 Qt 스레드로 넘긴다."""
    done = Signal(object)


class _DeferredStartLog:
    """수집 소스의 이벤트 로그 앞에 둔다. `capture_start` 는 소스가 열 때 내지만 결정 0178(S10-26)은 첫 음성 블록을 받은 때 한 번 남기라고 하므로
    소스의 `capture_start` 를 붙들었다가 `flush()` 에서 낸다(권한 없음으로 첫 블록 전에 끝난 시도는 `discard()` 로 버린다). 다른 사건은 그대로 넘긴다."""

    def __init__(self, log):
        self._log = log
        self._pending: Optional[dict] = None
        self._logged = False

    def emit(self, type_: str, **fields) -> None:
        if type_ == "capture_start":
            if not self._logged:
                self._pending = fields
            return
        self._log.emit(type_, **fields)

    def flush(self) -> None:
        if self._pending is not None and not self._logged:
            self._logged = True
            f, self._pending = self._pending, None
            self._log.emit("capture_start", **f)

    def discard(self) -> None:
        self._pending = None


class _TapSource:
    """음성 소스를 감싸 상태 변화를 알리고, 시험 연결점으로 수집 오류를 주입한다(`audio_error` · `audio_recover`).
    결정 0178: 권한 없음으로 끝난 시도는 `retire()` 로 소스를 새것으로 바꾸고, 다음 [재생] 의 `resume()` 이 새 소스를 시작한다.
    옛 소스가 뒤늦게 내는 블록 · 상태는 세대(`_gen`)로 버린다. 첫 음성 블록을 받으면 `on_first_block` 을 한 번 호출한다."""

    def __init__(self, inner, on_state: Callable, new_inner: Optional[Callable] = None, on_first_block: Optional[Callable] = None):
        self._inner, self._tap = inner, on_state
        self._new_inner, self._on_first_block = new_inner, on_first_block
        self._downstream = lambda state, detail="": None
        self._on_block = None
        self._gen = 0
        self._fresh = False                       # 새로 바꾼 소스가 아직 시작되지 않았다
        self._seen_first = False

    def start(self, on_block, on_state=lambda state, detail="": None) -> None:
        self._downstream = on_state
        self._on_block = on_block
        self._begin()

    def _begin(self) -> None:
        gen, inner = self._gen, self._inner
        self._fresh = False
        self._seen_first = False
        inner.start(lambda b: self._block(gen, b), lambda state, detail="": self._state_from(gen, state, detail))

    def _block(self, gen: int, block) -> None:
        if gen != self._gen:
            return
        if not self._seen_first:
            self._seen_first = True
            if self._on_first_block is not None:
                try:
                    self._on_first_block()
                except Exception:  # noqa: BLE001
                    pass
        if self._on_block is not None:
            self._on_block(block)

    def _state_from(self, gen: int, state: str, detail: str = "") -> None:
        if gen == self._gen:
            self.state(state, detail)

    def state(self, state: str, detail: str = "") -> None:
        self._tap(state, detail)
        self._downstream(state, detail)

    def retire(self) -> None:
        """결정 0178: 옛 소스를 별도 스레드에서 정리하고(소스의 `stop()` 은 기다리므로 호출한 스레드를 막지 않는다) 새 소스로 바꾼다."""
        old = self._inner
        self._gen += 1
        threading.Thread(target=old.stop, name="retire-audio", daemon=True).start()
        if self._new_inner is not None:
            self._inner = self._new_inner()
            self._fresh = True

    def stop(self) -> None:
        self._inner.stop()

    def pause(self) -> None:
        """일시 정지: 소스를 닫는다(결정 0147). 소스가 지원하지 않으면 아무것도 하지 않는다."""
        fn = getattr(self._inner, "pause", None)
        if callable(fn):
            fn()

    def resume(self) -> bool:
        """[재생]: 소스를 다시 연다. 열었으면 True, 열지 못하면 False(소스가 `중단` 상태를 낸다). 새로 바꾼 소스는 처음처럼 시작한다."""
        if self._fresh:
            self._begin()
            return True
        self._seen_first = False                  # 재개한 시도도 첫 음성 블록으로 끝난다(일시 정지의 끝 기록, 결정 0178)
        fn = getattr(self._inner, "resume", None)
        return bool(fn()) if callable(fn) else True

    def level(self) -> float:
        return getattr(self._inner, "level", lambda: 0.0)()

    def level_dbfs(self) -> float:
        import math
        return max(-120.0, 20.0 * math.log10(max(self.level(), 1e-12)))


SHUTDOWN_LIMIT_S = 8.0     # 결정 0172 2항: 응하지 않는 보조 프로세스가 있어도 종료가 10초 안에 끝나도록 남은 PID 를 이 시각에 SIGKILL 한다


class _LayerFilter(QObject):
    """앱이 활성화되거나 다른 창이 활성화된 뒤에 정지 확인 창 · 종료 창의 층과 순서를 다시 맞춘다(D-187 · D-186, 결정 0173).
    Qt 는 앱이 활성화될 때 `Qt.Tool` 창(설정 창)의 층을 3 으로 되돌리고(실측: b51 진단 스크립트, ApplicationActivate 직후 0ms 에 3),
    운영체제는 Dock · 상태 아이콘으로 돌아올 때 메인 창을 두 창 위로 올린다. 그래서 활성화 이벤트마다 다음 차례에 다시 맞춘다."""

    def __init__(self, ctl):
        super().__init__(ctl)
        self._ctl = ctl

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt)
        t = ev.type()
        if t in (QEvent.Type.ApplicationActivate, QEvent.Type.WindowActivate) and self._ctl._modal_dialog_up():
            QTimer.singleShot(0, self._ctl._reassert_dialog_layer)
            QTimer.singleShot(150, self._ctl._reassert_dialog_layer)      # Qt 가 더 늦게 층을 되돌리는 경우의 안전장치
        return False


class _QuitFilter(QObject):
    """Dock 의 "종료" · 로그아웃 · 재시동의 종료 요청(`QEvent.Quit`)을 ⌘Q 와 같은 종료 흐름으로 돌린다(결정 0152).
    Qt 가 이 사건을 그대로 처리하면 열린 창만 닫고 앱이 끝나 세션의 종료 흐름(정리 문서 만들기)을 건너뛴다. 사건은 거부하고
    (운영체제의 종료는 취소된다) 앱이 `shell.request_quit()` 로 스스로 끝낸다.
    앱이 스스로 끝내는 `app.quit()` 도 같은 사건을 만든다(PySide6 6.12 실측). 종료가 이미 시작되었으면(`is_ending`) 사건을 통과시켜
    이벤트 루프가 끝나게 한다. 거부하면 `shutdown` 으로 되돌아와 앱이 끝나지 않는다(D-161)."""

    def __init__(self, request_quit, parent=None, is_ending=lambda: False):
        super().__init__(parent)
        self._request_quit = request_quit
        self._is_ending = is_ending

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt)
        if ev.type() == QEvent.Type.Quit and not self._is_ending():
            ev.ignore()
            QTimer.singleShot(0, self._request_quit)
            return True
        return False


_GC_LOCK = threading.Lock()
_GC_HOLDS = 0
_GC_WAS_ON = False


def _gc_hold() -> None:
    """가비지 수집을 끄고 끈 횟수를 센다. 처음 끈 쪽이 이전 상태를 기억한다(D-222 · D-223)."""
    global _GC_HOLDS, _GC_WAS_ON
    with _GC_LOCK:
        if _GC_HOLDS == 0:
            _GC_WAS_ON = gc.isenabled()
            gc.disable()
        _GC_HOLDS += 1


def _gc_release() -> None:
    """마지막으로 끈 쪽이 끝나면 처음 상태로 되돌린다."""
    global _GC_HOLDS
    with _GC_LOCK:
        _GC_HOLDS = max(0, _GC_HOLDS - 1)
        if _GC_HOLDS == 0 and _GC_WAS_ON:
            gc.enable()


class AppController(QObject):
    def __init__(self, app: QApplication, argv: Sequence[str] = (), deps: Optional[Deps] = None):
        super().__init__()
        self.app = app
        self.deps = deps or Deps()
        self.dev = devopts.parse(list(argv))
        self.environ = dict(self.deps.environ if self.deps.environ is not None else os.environ)
        self.config_dir = Path(self.dev.get("config_dir") or settings.default_config_dir())
        self.settings_path = settings.settings_path(self.config_dir)
        loaded = settings.load_settings(self.settings_path)
        self.data = dict(loaded.data)
        self.settings_notices = list(loaded.notices)
        self.eventlog = EventLog(self.config_dir)
        for name, why in self.dev.errors:    # 값은 남기지 않는다
            self.eventlog.emit("dev_option_error", option=name, reason=why)
        self.registry = ChildRegistry(self.config_dir)
        self.procs = Procs(on_change=self.registry.on_change)
        cleanup_orphans(self.config_dir, emit=self.eventlog.emit)
        remove_stale_prompt_files(self.config_dir)
        self.found = self._find_claude(self.data.get("claude_path"))
        self.claude_path: Optional[str] = self.found.path if self.found else None       # 설정의 경로(다음 세션부터 적용)
        auto = self._find_claude(None)
        self.claude_auto_path: Optional[str] = auto.path if auto else None              # 설정 값을 빼고 자동으로 찾은 경로(설정 창의 기본 경로, 결정 0176 3항)
        self._session_claude: Optional[tuple] = None                                    # 세션이 시작 때 정한 (경로, 탐색 결과)
        self._session_key: Optional[str] = None                                         # 세션이 시작 때 읽은 API 키(메모리에만 둔다, AC-FR1-26 ⑤)
        self._session_prompt: Optional[str] = None                                      # 세션이 시작 때의 프롬프트(AC-FR1-26 ⑥)
        self._start_banner_kind: Optional[str] = None                                   # 시작 불가 띠의 종류(5번 절로 한 번만 이동하기 위한 기억)
        self._scaler = self.deps.scaler
        self.limits = Limits.from_devopts(self.dev)
        self.context = ContextStore(self.limits, shrink=imageinfo.ImageShrinker(self._get_scaler()),
                                    emit=self.eventlog.emit, procs=self.procs)
        self._key_store: Optional[ApiKeyStore] = None
        # 화면
        save_default = str(Path.home() / "Documents" / "ProfKangRAB")
        self.shell = MainShell(self.data, save_default, self.claude_path, first_run=appstate.first_run_required(self.data),
                               emit=self.eventlog.emit)
        if self.dev.get("save_dir"):      # 5-1절 연결점: 이 실행 동안만 저장 위치를 바꾼다(설정에 저장하지 않는다, D-045)
            self.shell.start_page.save_dir.setText(str(self.dev.get("save_dir")))
        self.materials_model = MaterialsModel(self.context)
        self.materials_panel = MaterialsPanel(self.materials_model)
        self.shell.start_page.add_section(self.materials_panel)
        self.materials_panel.changed.connect(lambda: self.refresh_status())
        self._hk_bridge = _HotkeyBridge(self)
        self._hk_bridge.fired.connect(self._on_global_fired, Qt.ConnectionType.QueuedConnection)
        self._hk = None                      # 전역 키 등록기(처음 필요할 때 만든다)
        self._hk_registered: set = set()
        self._hk_failed: dict = {}           # 행 번호 → 키 글(등록에 실패한 전역 행)
        self._sanitize_keys()
        trig = self.data.get("trigger_key")
        trig = "F2" if trig is None else str(trig)
        self.menu = menus.MenuController(trig, "")
        self.appearance = AppearanceApplier(app, self.data.get("appearance") or appstate.APPEARANCE_SYSTEM,
                                            emit=self.eventlog.emit, system_override=self.dev.get("appearance"))
        self.reopen = menus.ReopenFilter(self)
        app.installEventFilter(self.reopen)
        self._layer_filter = _LayerFilter(self)
        app.installEventFilter(self._layer_filter)
        self.click_activate = menus.ClickActivateFilter(self.shell)         # D-131
        app.installEventFilter(self.click_activate)
        # 세션 상태
        self.runtime = None
        self._last_stt_language: Optional[str] = None
        self.pipeline = None
        self._tap: Optional[_TapSource] = None
        self._params: dict = {}
        self._capture_state: Optional[str] = None
        self._capture_detail: str = ""
        self._pause_mono: Optional[float] = None       # 일시 정지를 시작한 monotonic 시각(구간 길이 계산)
        self._pause_start_ts: Optional[str] = None
        self._start_fail_armed = False                 # 시험 주입: 다음 [재생] 을 시작 실패로 끝낸다(수집 전 · 일시 정지 중)
        self._cap_log: Optional[_DeferredStartLog] = None   # 수집 소스의 이벤트 로그(`capture_start` 를 첫 음성 블록까지 붙든다, 결정 0178 S10-26)
        self._attempt_no = 0                           # 수집 시도 번호(세션 안의 누적, 결정 0178 S10-30)
        self._attempt_pending = False                  # [재생] 로 시작한 시도의 결과(첫 음성 블록 또는 종료)를 기다린다
        self._attempt_prev: Optional[str] = None       # 이 시도를 시작하기 전의 수집 상태(수집 전 · 일시 정지)
        self._play_denied = False                      # 이 [재생] 의 시도가 권한 없음으로 끝났다
        self._permission_band: Optional[tuple] = None  # 권한 안내 띠의 (제목, 설명). 없으면 None
        self._pause_finish_pending = False             # 일시 정지의 끝 기록을 첫 음성 블록까지 미뤘다(권한 없음이면 쓰지 않는다)
        self._ever_played = False                      # [재생] 로 시도한 적이 있다(권한 없음으로 실패한 것 포함, AC-FR3-22)
        self._stop_dialog = None
        self._settings_level = None             # 정지 확인 창 · 종료 창이 떠 있는 동안 내려 둔 설정 창의 원래 층(D-187)
        self._set_window_level = nswindow.set_window_level
        self._stt_errors = 0
        self._stt_gen = 0                              # 음성 인식 보조 프로세스의 세대(옛 세대의 늦은 사건을 버린다)
        self._stt_ready = False                        # 현재 세대가 `ready` 를 받았는가
        self._stt_prep: Optional[str] = None           # 준비 칩의 글(NEW-47 · 48). 준비하는 동안에만 값이 있다
        self._stt_prep_pct = -1                        # 칩의 퍼센트는 줄어들지 않는다
        self._stt_exit: Optional[str] = None           # 종료 사유(처리표). 다시 시도가 준비를 마칠 때까지 남는다
        self._stt_band = None                          # 수집 중 종료의 띠 (제목, 조치, [다시 시도] 보임)
        self._stt_exit_paused = False                  # 일시 정지 중에 종료했는가(다시 시도의 [재생] 이 구간을 끝낸다)
        self._stt_retrying = False
        self._stt_retry_timer = QTimer(self)
        self._stt_retry_timer.setSingleShot(True)
        self._stt_retry_timer.timeout.connect(self._on_retry_timeout)
        self._stt_locales: Optional[set] = None        # 지원하는 로캘(조회에 성공한 뒤의 캐시)
        self._stt_locales_loading = False
        self._locales_bridge = _LocalesBridge(self)
        self._locales_bridge.done.connect(self._on_locales)
        self._stt_fallback_text = ""
        self._captures = 0
        self._capture_bridge = _CaptureBridge(self)
        self._capture_bridge.done.connect(self._on_frame_captured)
        self._capture_bridge.failed.connect(self._on_frame_capture_failed)
        self._capturing = False
        self._settings_form = None
        self._started_mono: Optional[float] = None
        self._attached: dict = {}            # 칩 키 → (AttachedImage, 상대 경로, 출처)
        self._chip_seq = 0
        self._local_card = 0                 # 카드 번호가 없는 오류 카드(음수)
        self._settings_dialog: Optional[QDialog] = None
        self._settings_hidden_by_minimize = False
        self._settings_saved_pos = None      # D-112: 최소화로 숨기기 전의 설정 창 위치
        self._about_dialog: Optional[QDialog] = None
        self._about_view = None
        self._notice_dialog: Optional[QDialog] = None
        self._control_pos: Optional[int] = None
        self._control_line = 0
        self._ended = False
        self._end_flow = None
        self._cleanup_finished = False       # D-132: 정리 문서 만들기가 끝났다(완료 · 실패). 끝난 뒤에는 상태 표시줄에 '만드는 중' 을 쓰지 않는다
        self._end_dialog = None
        self._rebuild_mode = False
        self._quit_after_rebuild = False     # D-229: 다시 만들기를 취소한 결과(CANCELLED)가 오면 앱을 끝낸다
        self._end_bridge = _EndBridge()
        self._end_bridge.done.connect(self._on_done_signal)
        self._starting = None                # init 의 인증 출처를 확인하는 중인 런타임(결정 0056, AC-FR1-14)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(lambda: self._abort_start("process_exit", _t("ctl.init___224")))
        self._start_bridge = _StartBridge()
        self._start_bridge.ok.connect(self._on_start_ok)
        self._start_bridge.failed.connect(self._abort_start)
        self._diagram_pool = None
        self._diagram_results: dict = {}     # 카드 번호 → DiagramResult(완료 · 위반)
        self._diagram_bridge = _DiagramBridge()
        self._diagram_bridge.done.connect(self._on_diagram_done)
        self._wire()
        self._setup_frame()
        self._timers()

    # ------------------------------------------------------------------ 연결
    @property
    def view(self):
        return self.shell.session_page

    @property
    def view_start(self):
        return self.shell.start_page

    def _wire(self) -> None:
        sh, v = self.shell, self.view
        sh.session_start_requested.connect(self.start_session)
        sh.quit_requested.connect(self.quit_now)
        self._quit_filter = _QuitFilter(sh.request_quit, self, lambda: self._ended)
        self.app.installEventFilter(self._quit_filter)
        sh.end_flow_requested.connect(self.end_session)
        sh.ending_quit_requested.connect(self.quit_during_ending)
        sh.first_run_page.acknowledged.connect(self._ack_first_run)
        sh.first_run_page.open_settings_requested.connect(self._open_screen_recording_settings)
        sh.first_run_page.set_permissions(self._permission_values())
        self.menu.command.connect(self.on_command)
        self.shell.on_state_change = self._on_machine_state
        self.shell.on_minimized_changed = self._on_main_minimized      # D-111
        sp = sh.start_page
        sp.provider.currentIndexChanged.connect(lambda _i: self.refresh_start_check())
        sp.default_prompt_saved.connect(self._on_default_prompt)         # 결정 0179: 시작 화면으로 옮긴 설정
        sp.app_language_changed.connect(self._on_app_language)
        sp.claude_path_changed.connect(self._on_claude_path)
        sp.api_key_submitted.connect(self._on_key_submitted)
        sp.api_key_delete_requested.connect(self._on_key_delete)
        sp.set_claude_auto(self.claude_auto_path)
        sp.set_key_saved(self._key_saved())
        self._check_saved_stt_language()
        QTimer.singleShot(0, self._sync_language_settings)         # 시작 화면을 열 때 지원 로캘을 확인한다(AC-FR16-2)
        QTimer.singleShot(0, self.refresh_start_check)        # 시작 화면이 처음 보일 때(키 없음 · claude 없음)
        self.reopen.reopen_requested.connect(sh.show_main_window)
        v.input.submitted.connect(self.on_submit)
        v.reflect_clicked.connect(lambda: self.on_command("request.trigger"))      # AI 창 머리 행의 [고찰] 단추(결정 0157)
        v.capture_clicked.connect(lambda: self.on_command("request.capture"))      # 카메라 단추 = 액자 캡처
        self.menu.attach_shortcuts(sh)           # 메뉴에 없는 두 동작의 키(앱 창 안 고찰 키 · 액자 캡처 키)가 창에서 동작하게 한다
        self._refresh_request_keys()
        v.input.chip_removed.connect(self._on_chip_removed)
        v.input.files_dropped.connect(self._on_files_dropped)
        v.input.files_pasted.connect(self._on_files_pasted)
        v.input.image_pasted.connect(lambda data: self.attach([(_t("ctl.wire_225"), data)], SOURCE_PASTE))
        v.ai.card_delete_requested.connect(self.delete_card)
        v.ai.diagram_requested.connect(self.make_diagram)
        v.ai.diagram_open_requested.connect(self.open_diagram)
        v.ai.gate_provider = self._diagram_gate
        v.bridge.notice.connect(self._show_notice)
        v.bridge.capture.connect(self._apply_capture_banner)
        v.bridge.stt.connect(self._on_stt_ui)
        v.banner.retry_clicked.connect(self.retry_stt)
        v.guide_retry_clicked.connect(self.retry_stt)
        v.transport.play_clicked.connect(self.play_capture)
        v.transport.pause_clicked.connect(self.pause_capture)
        v.transport.stop_clicked.connect(self.request_stop)

    def _timers(self) -> None:
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.refresh_status)
        self._status_timer.start(STATUS_REFRESH_MS)
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._refresh_level)
        self._level_timer.start(LEVEL_REFRESH_MS)
        self._control_timer: Optional[QTimer] = None
        path = self.dev.get("control")
        if path:
            try:
                self._control_pos = os.path.getsize(path) if os.path.exists(path) else 0
            except OSError:
                self._control_pos = 0
            self._control_timer = QTimer(self)
            self._control_timer.timeout.connect(self._poll_control)
            self._control_timer.start(CONTROL_POLL_MS)

    def show(self) -> None:
        self.shell.show()
        self.menu.show_tray()
        self.refresh_status()
        for n in self.settings_notices:
            self._notice_text(n.detail)

    # ------------------------------------------------------------------ 설정 · 키
    def _get_scaler(self):
        if self._scaler is None:
            from ..platform.capture.shrink import QtScaler
            self._scaler = QtScaler()
        return self._scaler

    def key_store(self) -> ApiKeyStore:
        if self._key_store is None:
            account = self.dev.get("key_account")
            if self.deps.key_store_factory is not None:
                self._key_store = self.deps.key_store_factory(account)
            else:
                self._key_store = ApiKeyStore(account=account) if account else ApiKeyStore()
        return self._key_store

    def _save(self, **changes) -> None:
        ok, why = settings.update_settings(self.settings_path, changes)
        if not ok:
            self.eventlog.emit("error", module="settings", kind="io", detail=_t("ctl.save_226") % why)
            self._notice_text(_t("ctl.save_227"))
        else:
            self.data.update(changes)

    def _on_default_prompt(self, text: str) -> None:
        """설정에서 기본 문구를 바꿨다: 저장하고, 시작 화면의 칸이 고쳐지지 않았으면 바뀐 문구를 넣는다(AC-FR2-5)."""
        self._save(default_session_prompt=text)
        self.shell.start_page.reload_default_prompt(self.data)

    def _ack_first_run(self) -> None:
        self._save(first_run_ack=appstate.FIRST_RUN_NOTICE_VERSION)

    # ------------------------------------------------------------------ 액자 (K-14, 결정 0010 · 0077)
    def _screens(self) -> list:
        """화면 전체의 사각형(경계). 시험은 `deps.screen_rects` 로 바꾼다."""
        return (self.deps.screen_rects or (lambda: frame_mod.screen_rects(True)))()

    def _avails(self) -> list:
        """가용 영역의 사각형(기본 위치 계산용)."""
        return (self.deps.screen_rects or frame_mod.screen_rects)()

    def _setup_frame(self) -> None:
        """앱이 실행되는 동안 액자 창을 둔다. 위치 · 크기는 설정에서 복원하고(결정 0077 4항), 저장된 좌표가 화면 밖이면
        주 화면의 기본값으로 복원하고 알린다(AC-FR12-12)."""
        self.frame = frame_mod.FrameWindow(lambda: self.appearance.scheme)
        self.frame.pretend_method_missing = self.dev.get("frame_method_missing") == "on"
        self.frame.on_native_created = self._on_frame_native_created
        self.frame._screens = self._screens
        self.frame._avails = self._avails
        rect, source, reason = framegeom.restore_info(self.data.get("frame"), self._screens(), self._avails())
        off_screen = reason in ("off_screen", "invalid")
        self.frame.set_frame(rect)
        inner = framegeom.inner_region(rect)
        self.eventlog.emit("frame_restore", source=source, reason=reason, x=rect.x, y=rect.y, w=rect.w, h=rect.h,
                           inner_w=inner.w, inner_h=inner.h)          # 개인 자료가 아닌 좌표만
        self.frame.committed.connect(self._on_frame_committed)
        self.frame.hide_requested.connect(self.hide_frame)
        self._frame_wanted = True                  # 사용자가 숨기지 않았으면 보인다
        self._frame_notice = framegeom.OFF_SCREEN_NOTICE if off_screen else None
        self._sync_frame(self.shell.machine.state, "start")

    def _on_frame_committed(self, rect) -> None:
        self._save(frame=rect.as_dict())
        inner = framegeom.inner_region(rect)
        self.eventlog.emit("frame_geometry_saved", x=rect.x, y=rect.y, w=rect.w, h=rect.h, inner_w=inner.w, inner_h=inner.h)

    def _on_frame_native_created(self, info: dict) -> None:
        """액자의 네이티브 창이 만들어질 때마다(결정 0112, 기능 정의 5-1절 이벤트 로그 "액자 창 만들기"): 비활성화 메서드의 유무 · 적용 여부 · 가장 여부."""
        self.eventlog.emit("frame_window_created", native=bool(info.get("native")), window_class=info.get("class", ""),
                           is_panel=bool(info.get("is_panel")), has_method=bool(info.get("has_method")),
                           applied=bool(info.get("applied")), pretended=bool(info.get("pretended")))

    def _sync_frame(self, state, reason: str = "state") -> None:
        """상태 ① 에서는 띄우지 않고 ② 로 넘어갈 때 띄우며, ④ 에서는 숨긴다(숨김을 저장하지 않으므로 `_frame_wanted` 는
        그대로이다). ② 에서 사용자가 숨겼으면 세션 시작이 다시 띄우지 않는다. 숨김은 다음 실행에 유지하지 않는다
        (AC-FR12-3 · 11 · 19, 9차 개정 3차 초안)."""
        show = self._frame_wanted and state not in (appstate.State.FIRST_RUN, appstate.State.ENDING)
        was = self.frame.isVisible()
        if show and not was:
            self.frame.show()
        elif not show and was:
            self.frame.hide()
        if self.frame.isVisible() != was or reason == "start":
            self.eventlog.emit("frame_visibility", visible=self.frame.isVisible(), reason=reason)
        self.menu.set_frame_visible(self.frame.isVisible())
        if self.frame.isVisible() and self._frame_notice:
            self._notice_text(self._frame_notice)
            self._frame_notice = None

    def hide_frame(self) -> None:
        self._frame_wanted = False
        self._sync_frame(self.shell.machine.state, "hide_button")

    def toggle_frame(self, reason: str = "menu") -> None:
        """"액자 보이기" · "액자 숨기기"(창 메뉴 · 상태 아이콘 메뉴). 같은 위치와 크기로 다시 보인다(AC-FR12-15)."""
        self._frame_wanted = not self._frame_wanted
        self._sync_frame(self.shell.machine.state, reason)

    def set_frame_rect(self, rect) -> None:
        """바깥 사각형을 지정한다(시험 제어 C2). 한 화면 안으로 보정하고 저장한다."""
        rect = framegeom.clamp(rect, self._screens(), None, self._avails())
        self.frame.set_frame(rect)
        self._on_frame_committed(rect)

    def drop_frame(self, rect, pointer) -> None:
        """끌기를 놓은 것과 같은 처리(시험 제어 C2 `frame_drop`): 놓은 바깥 사각형과 포인터 위치를 받아 창에 그대로 두었다가
        `FrameWindow` 가 놓을 때 하는 것과 같이 포인터가 있는 화면 안으로 보정하고(높이 제한 · 비율 축소 포함) 저장한다."""
        self.frame.set_frame(rect)
        self.frame.set_frame(framegeom.clamp(self.frame.frame_rect(), self._screens(), pointer, self._avails()))
        self._on_frame_committed(self.frame.frame_rect())

    def frame_rects(self) -> dict:
        """바깥 · 안쪽 · 손잡이 네 개의 화면 좌표(C2). 창 사각형은 바깥 사각형과 같다(이름표 띠가 없다, 결정 0080)."""
        f = self.frame
        g = f.geometry()

        def scr(r) -> dict:
            return {"x": g.x() + r.x(), "y": g.y() + r.y(), "w": r.width(), "h": r.height()}
        return {"outer": f.frame_rect().as_dict(), "inner": f.capture_region().as_dict(),
                "window": {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()},
                "handles": {k: scr(r) for k, r in f.handle_rects().items()},
                "visible": f.isVisible(), "tooltip": f.tooltip_state()}

    def capture_frame(self) -> None:
        """[액자 캡처]: 액자 안쪽 영역을 `screencapture -R` 로 찍어 화면메모 요청으로 등록한다(AC-FR12-1 · 10 · 11).
        액자를 숨긴 동안에도 같은 영역을 캡처한다. `screencapture` 의 대기는 작업 스레드에서 한다."""
        rt = self.runtime
        if rt is None or self._capturing or self._ended:
            return
        from ..platform import permissions as P
        from ..platform.capture.screenshotter import CaptureError, ProcsRunner, Screenshotter
        from ..platform.capture.types import FrameRegion
        if self._permission_values().get("screen_recording") == P.DENIED:
            # AC-FR12-7: 안내를 표시하고 종료하지 않는다. 처음 [재생] 전이면 NEW-45 한 줄을 덧붙인다(결정 0161 5항)
            self._post_error("permission", PERMISSION_SCREEN_TEXT, permission="screen_recording", source="capture",
                             guided=self._capture_state == COLLECT_BEFORE and not self._ever_played)   # 권한 없음으로 실패한 [재생] 도 처음 [재생] 이다(AC-FR3-22)
            return
        region = self.frame.capture_region()
        captures = str(rt.folder / "captures")
        try:
            os.makedirs(captures, exist_ok=True)
        except OSError:
            self._post_error("io", _t("ctl.capture_frame_228"))
            return
        self._capturing = True
        self.frame.begin_capture()                 # 손잡이를 지우고 테두리를 3 으로 한다(D-118 · D-119)
        self.eventlog.emit("frame_capture", region="%d,%d,%d,%d" % (region.x, region.y, region.w, region.h),
                           frame_visible=self.frame.isVisible(), flashing=self.frame.is_flashing())      # C1: 실행 시점의 상태(강조는 시작 때 멈춘다)
        rt.manager.set_capture_busy(True)          # AC-FR12-4: screencapture 실행부터 화면 메모 요청이 끝날 때까지 트리거를 보류한다
        runner = self.deps.capture_runner or self._fake_capture_runner() or ProcsRunner(self.procs, captures)
        bridge = self._capture_bridge

        def work() -> None:
            try:
                item = Screenshotter(runner, captures).capture(FrameRegion(region.x, region.y, region.w, region.h))
            except CaptureError as e:
                bridge.failed.emit(e.kind, e.detail)
            except Exception as e:                         # 작업 스레드의 예외가 앱을 멈추지 않게 한다
                bridge.failed.emit("exit", type(e).__name__)
            else:
                bridge.done.emit(item)

        t = threading.Thread(target=work, name="frame-capture", daemon=True)
        if self.frame.isVisible():                 # 지운 모습이 화면에 반영된 뒤에 캡처한다
            QTimer.singleShot(CAPTURE_SETTLE_MS, lambda: None if self._ended else t.start())
        else:
            t.start()

    def _fake_capture_runner(self):
        """`--dev-capture-fake <PNG>`: `screencapture` 대신 명령을 기록하고 PNG 를 출력 경로에 쓴다(C1)."""
        src = self.dev.get("capture_fake")
        if not src:
            return None

        def run(cmd, timeout_s):
            import shutil
            try:
                with open(src + ".commands.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(list(cmd), ensure_ascii=False) + "\n")
                shutil.copyfile(src, cmd[-1])
            except OSError:
                return 1, ""
            return 0, ""
        return run

    def _on_frame_captured(self, item) -> None:
        from ..platform.capture import shrink, store
        self._capturing = False
        self.frame.end_capture()                   # 손잡이를 다시 그린다. 강조는 등록한 뒤에 시작한다(D-119)
        rt = self.runtime
        if rt is None or self._ended:
            return
        try:
            self._register_capture(item, rt)
        finally:
            rt.manager.set_capture_busy(False)     # 화면 메모가 끝날 때까지는 `track_capture` 가 보류를 이어 간다

    def _register_capture(self, item, rt) -> None:
        from ..platform.capture import shrink, store
        try:
            with open(item.path, "rb") as fh:
                data = fh.read()
            pr = shrink.prepare(data, self._get_scaler(), max_bytes=self.limits.image_bytes_cap)
            path = item.path
            if pr.data != data:                              # 줄였거나 형식을 바꾼 것만 다시 쓴다(captures/ 안에서만, AC-FR12-6)
                path = store.write_bytes(pr.data, pr.fmt, os.path.dirname(item.path),
                                         os.path.splitext(os.path.basename(item.path))[0])
                os.remove(item.path)
        except (OSError, imageinfo.ImageTooLarge, shrink.ImageError):
            self._notice_text(_t("ctl.register_capture_229"))
            return
        media = "image/jpeg" if pr.fmt == "jpg" else "image/%s" % pr.fmt
        img = R.AttachedImage(source=SOURCE_CAPTURE, t_wall=item.t_wall, media_type=media, data=pr.data,
                              name=os.path.basename(path))
        card = rt.submit("화면메모", images=[img], capture_paths=[("captures/%s" % os.path.basename(path), SOURCE_CAPTURE)])
        rt.manager.track_capture(card.n)
        self.view.ai.set_card_images(card.n, [(img.data, SOURCE_CAPTURE)])
        self._captures += 1
        self.frame.flash()

    def _on_frame_capture_failed(self, kind: str, detail: str) -> None:
        self._capturing = False
        self.frame.end_capture()                              # 실패해도 손잡이와 테두리를 다시 그린다
        if self.runtime is not None:
            self.runtime.manager.set_capture_busy(False)      # 보류한 트리거를 실행한다(D-114)
        self.eventlog.emit("error", module="capture", kind=kind, detail=detail)
        self._notice_text(_t("ctl.on_frame_capture_failed_230") % (detail or kind))

    def _on_main_minimized(self, minimized: bool) -> None:
        """D-111 · 결정 0074 2항: 메인 창이 최소화되면 보이던 설정 창을 숨기고, 복원되면 그때만 다시 보인다.
        사용자가 닫은 설정 창은 복원 때 다시 열지 않는다."""
        dlg = self._settings_dialog
        if dlg is None:
            return
        if minimized:
            if dlg.isVisible():
                self._settings_hidden_by_minimize = True
                self._settings_saved_pos = dlg.pos()       # D-112 · 결정 0076: 숨기기 전 위치를 기억한다
                dlg.hide()
        elif self._settings_hidden_by_minimize:
            self._settings_hidden_by_minimize = False
            self._show_settings_dialog()

    def _show_settings_dialog(self) -> None:
        """설정 창을 보인다. 최소화로 숨겼던 창이면 숨기기 전 위치로 되돌린다(D-112 · 결정 0076 1항).
        닫았다 다시 여는 창은 기억한 위치가 없으므로 기본 위치이다(결정 0073)."""
        dlg = self._settings_dialog
        pos = self._settings_saved_pos
        self._settings_hidden_by_minimize = False
        self._settings_saved_pos = None
        dlg.show()
        if pos is not None:
            dlg.move(pos)
        dlg.raise_()

    def _forget_settings_position(self) -> None:
        """설정 창을 닫으면 옮긴 위치를 버린다. 같은 QDialog 를 다시 쓰므로 WA_Moved 를 지워야 Qt 가
        다시 열 때 부모 기준의 기본 위치에 놓는다(결정 0073 1항 · 0076 2항)."""
        self._settings_saved_pos = None
        self._settings_hidden_by_minimize = False
        if self._settings_dialog is not None:
            self._settings_dialog.setAttribute(Qt.WA_Moved, False)

    def open_settings(self) -> None:
        if self._settings_dialog is None:
            dlg = QDialog(self.shell)
            # D-110 · 결정 0070 1항: 부모(메인 창) 앞에 남는다. macOS 의 Qt 는 도구 창을 부모 위의 부동 패널로 둔다.
            # 앱이 비활성이 되어도 숨지 않도록 WA_MacAlwaysShowToolWindow 를 켠다(없으면 다른 앱으로 전환할 때 사라진다).
            dlg.setWindowFlags(dlg.windowFlags() | Qt.Tool)
            dlg.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
            dlg.setWindowTitle(_t("ctl.open_settings_231"))
            form = screens.SettingsForm(self.data, dlg, other_menu_items=self._other_menu_items,
                                        system_conflict=self._system_conflict)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(form)
            avail = shell_mod.fit_to_screen((form.WIDTH, 100000), screen=self.shell.screen())[1]       # 결정 0068 5항: 폭 고정, 높이는 내용과 가용 높이 − 80
            dlg.setMinimumSize(form.WIDTH, shell_mod.DIALOG_MIN_HEIGHT)
            dlg.setMaximumWidth(form.WIDTH)
            dlg.resize(form.WIDTH, max(shell_mod.DIALOG_MIN_HEIGHT, min(form.content_height(), avail)))
            form.close_requested.connect(dlg.close)
            dlg.finished.connect(lambda _r: self.refresh_start_check())      # 설정 창을 닫을 때(D-101)
            dlg.finished.connect(lambda _r: self._forget_settings_position())      # D-112 · 결정 0076 2항
            form.template_changed.connect(self._on_template)
            form.key_row_changed.connect(self._on_key_row_changed)
            form.key_table.capturing_changed.connect(lambda _c: self._apply_globals())
            dlg.finished.connect(lambda _r: form.key_table.dismiss_reset_notices())
            form.appearance_changed.connect(self._on_appearance)
            self._settings_form = form
            self._settings_dialog = dlg
        else:
            self._settings_form.sync(self.data)       # D-077: 다시 열 때 현재 설정으로 맞춘다
        self._show_key_notices()
        self._settings_form.key_table.set_session_registration(self._hk_registered, set(self._hk_failed))
        self._show_settings_dialog()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()          # AC-FR14-12: 이미 열려 있으면 앞으로 가져온다
        self._sync_dialog_layer()

    def _modal_dialog_up(self) -> bool:
        d = self._end_dialog
        try:
            return self._stop_dialog is not None or (d is not None and d.isVisible())
        except RuntimeError:
            return self._stop_dialog is not None            # 종료 창이 이미 삭제되었다

    def _sync_dialog_layer(self) -> None:
        """정지 확인 창 · 종료 창이 떠 있는 동안 설정 창의 층을 일반 창(0)으로 내리고, 닫히면 원래 층(부동 패널 3)으로 되돌린다
        (D-187, 결정 0173). 부동 패널은 일반 창보다 항상 앞에 그려지므로 두 창의 `raise_()` 가 닿지 않는다.
        일반 창의 층으로 내리므로 앱이 비활성일 때 다른 앱의 창 앞에 나오지 않는다. 설정 창은 닫거나 숨기지 않는다."""
        dlg = self._settings_dialog
        if dlg is None:
            return
        up = self._modal_dialog_up()
        if up and self._settings_level is None and dlg.isVisible():
            before = self._set_window_level(dlg, nswindow.NORMAL_WINDOW_LEVEL)
            if before is not None:
                self._settings_level = before
            for w in (self._stop_dialog, self._end_dialog):
                try:
                    if w is not None and w.isVisible():
                        w.raise_()
                except RuntimeError:
                    pass
        elif not up and self._settings_level is not None:
            level, self._settings_level = self._settings_level, None
            if dlg.isVisible():
                self._set_window_level(dlg, level)

    def _reassert_dialog_layer(self) -> None:
        """앱 활성화 · 창 활성화 뒤: 설정 창의 층을 다시 0 으로 내리고 두 창을 위로 올린다. 앱이 활성일 때만 한다(다른 앱의 앞을 빼앗지 않는다)."""
        try:
            if not self._modal_dialog_up() or QApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
                return
            dlg = self._settings_dialog
            if self._settings_level is not None and dlg is not None and dlg.isVisible():
                self._set_window_level(dlg, nswindow.NORMAL_WINDOW_LEVEL)
            for w in (self._stop_dialog, self._end_dialog):
                if w is not None and w.isVisible():
                    if not w.isActiveWindow():            # 이미 활성인 창은 다시 올리지 않는다(D-189: 불필요한 순서 변경을 줄인다)
                        w.raise_()
                        w.activateWindow()
                    self._notify_accessibility(w)
        except RuntimeError:
            pass                                          # 예약한 사이에 창이 삭제되었다

    @staticmethod
    def _notify_accessibility(w) -> None:
        """창의 손쉬운 사용 트리를 갱신하도록 알린다(D-189: 정지 확인 창의 단추 · 본문이 트리에서 빠지는 경우의 대비).
        창의 순서 · 활성 상태가 바뀐 뒤 Qt 가 자식 목록을 다시 만들지 않는 경우가 있어 변경 알림을 보낸다."""
        try:
            from PySide6.QtGui import QAccessible, QAccessibleEvent
            QAccessible.updateAccessibility(QAccessibleEvent(w, QAccessible.Event.ObjectReorder))
        except Exception:                                 # noqa: BLE001 (손쉬운 사용이 꺼진 환경 · 버전 차이는 무시한다)
            pass

    def _on_template(self, kind: str, text: str) -> None:
        """정리 문서 템플릿(AC-FR13-9). 빈 글은 앱 기본 템플릿이다."""
        key = "lecture" if kind == "수업" else "meeting"
        tpl = dict(self.data.get("templates") or {})
        tpl[key] = text or None
        self._save(templates=tpl)

    def _find_claude(self, configured):
        """`claude` 를 찾는다. `--dev-claude-search none`(5-1절 연결점)이면 PATH · 로그인 셸 · 알려진 위치를 비워 자동으로는 찾지 못하게 한다(설정 값은 그대로 쓴다)."""
        if self.dev.get("claude_search") == "none":
            return self.deps.find_claude(configured, {"PATH": ""}, login_shell=None, known_dirs=())
        return self.deps.find_claude(configured, self.environ, login_shell=self.deps.login_shell)

    def _on_claude_path(self, path) -> None:
        """claude 실행 파일: 직접 지정(경로) 또는 자동(None). 저장하고 다시 찾아 이후의 세션 시작에 반영한다."""
        self._save(claude_path=path)
        self.found = self._find_claude(self.data.get("claude_path"))
        self.claude_path = self.found.path if self.found else None
        self.eventlog.emit("claude_path_changed", mode="manual" if path else "auto")
        self.refresh_start_check()

    def _on_trigger_key(self, key: str) -> None:
        """트리거 키(앱 창 안): 메뉴 단축키와 입력창 표시에 즉시 반영하고 저장한다. 빈 글은 키로는 트리거하지 않는다."""
        self._save(trigger_key=key)
        self.menu.set_trigger_key(key)
        self._refresh_request_keys()
        self.eventlog.emit("trigger_key_changed")

    def _refresh_request_keys(self) -> None:
        """[고찰] 단추의 글과 두 단추의 도움말에 보이는 키를 저장된 키에서 다시 정한다(결정 0157)."""
        def shown(setting: str) -> str:
            return keyspec.display(str(self.data.get(setting) or ""))
        trig = self.data.get("trigger_key")
        local = keyspec.display("F2" if trig is None else str(trig))
        self.view.set_request_keys(local, shown(keytable.SETTING_KEY["global_trigger"]), shown(keytable.SETTING_KEY["global_capture"]))

    # ------------------------------------------------------------------ 키 설정 표 (결정 0141 · 0142)
    def _sanitize_keys(self) -> None:
        """저장되어 있던 글자 키(수식 키 없는 A 등)는 기본값으로 되돌리고 안내(KEY-9)를 설정에 남긴다(AC-FR7-31)."""
        notices = dict(self.data.get("key_reset_notice") or {})
        changes: dict = {}
        for rid, _n, skey, dflt in keytable.ROWS:
            saved = str(self.data.get(skey) or "")
            if saved and keyspec.typing_key_without_modifier(saved):
                changes[skey] = dflt
                notices[rid] = saved
        if changes:
            changes["key_reset_notice"] = notices
            self._save(**changes)

    def _show_key_notices(self) -> None:
        """되돌린 키의 안내를 설정 창을 처음 열 때 한 번 보인다. 보인 뒤에는 설정에서 지운다."""
        notices = self.data.get("key_reset_notice") or {}
        if not notices or self._settings_form is None:
            return
        for rid, saved in notices.items():
            self._settings_form.key_table.set_reset_notice(rid, saved)
        self._save(key_reset_notice=None)

    def _other_menu_items(self) -> dict:
        """키 글 → 메뉴 항목 이름. 두 트리거 항목은 이 표의 행이므로 뺀다."""
        out: dict = {}
        for cid, a in self.menu.actions.items():
            if cid in ("request.trigger", "request.capture"):
                continue
            seq = a.shortcut()
            if seq.isEmpty():
                continue
            parsed = keyspec.parse(seq.toString(QKeySequence.SequenceFormat.PortableText))
            if parsed is not None:
                out[keyspec.to_text(*parsed)] = a.text().replace("&", "").rstrip("…")
        return out

    def _system_conflict(self, text: str) -> Optional[str]:
        """켜진 macOS 시스템 단축키와 겹치면 KEY-3 의 이름. 읽기에 실패했을 때만 닫힌 목록을 쓴다."""
        cv = keyspec.carbon(text)
        if cv is None:
            return None
        live = (self.deps.system_shortcuts or hotkeys_mod.system_shortcuts)()
        fixed = hotkeys_mod.FIXED_SYSTEM_SHORTCUTS.get(cv)
        if live is not None and cv not in live:
            return None
        if live is None and fixed is None:
            return None
        return _t("keyset.key3n_" + (fixed or "system"))

    def _on_key_row_changed(self, row_id: str, text: str) -> None:
        if row_id == "trigger":
            self._on_trigger_key(text)
        else:
            self._save(**{keytable.SETTING_KEY[row_id]: text})
            self._refresh_request_keys()
            self.eventlog.emit("global_key_changed", row=row_id, empty=not text)
            self._apply_globals()

    def _get_hotkeys(self):
        if self._hk is None:
            cb = lambda name: self._hk_bridge.fired.emit(name)          # noqa: E731
            if self.deps.hotkeys_factory is not None:
                self._hk = self.deps.hotkeys_factory(cb)
            elif sys.platform == "darwin" and QGuiApplication.platformName() == "cocoa":
                self._hk = hotkeys_mod.GlobalHotkeys(cb)
        return self._hk

    def _globals_wanted(self) -> bool:
        """세션이 진행되는 동안(종료 흐름 전)이고 키 지정 중이 아닐 때만 등록한다."""
        capturing = self._settings_form is not None and self._settings_form.key_table.capturing() is not None
        return (self.runtime is not None and self.shell.machine.state is appstate.State.IN_SESSION
                and not self._ended and self._end_flow is None and not capturing)

    def _apply_globals(self) -> None:
        """전역 키의 등록 상태를 지금 상황에 맞춘다(세션 시작 · 종료 흐름 · 행 변경 · 지정 중 · 지정 끝)."""
        hk = self._get_hotkeys()
        in_session = (self.runtime is not None and self.shell.machine.state is appstate.State.IN_SESSION
                      and not self._ended and self._end_flow is None)
        if hk is None:
            return
        if not self._globals_wanted():
            hk.clear_all()
            self._hk_registered = set()
            if not in_session:
                self._hk_failed = {}
        else:
            registered, failed = set(), {}
            for rid in keytable.GLOBAL_ROWS:
                text = str(self.data.get(keytable.SETTING_KEY[rid]) or "")
                if not text:
                    hk.clear(rid)
                    continue
                cv = keyspec.carbon(text)
                st = hk.set(rid, cv[0], cv[1]) if cv is not None else -1
                if st == 0:
                    registered.add(rid)
                else:
                    failed[rid] = text
                    self.eventlog.emit("global_key_register_failed", row=rid, status=int(st))
            self._hk_registered, self._hk_failed = registered, failed
        self._show_key_band()
        if self._settings_form is not None:
            self._settings_form.key_table.set_session_registration(self._hk_registered, set(self._hk_failed))

    def _show_key_band(self) -> None:
        """등록에 실패한 전역 키가 있으면 AI 창 위에 띠를 보인다(KEY-7 · KEY-8). 모두 등록되거나 비면 거둔다."""
        band = self.view.key_banner
        if not self._hk_failed:
            band.clear_banner()
            return
        keys = " · ".join(keyspec.display(self._hk_failed[r]) for r in keytable.GLOBAL_ROWS if r in self._hk_failed)
        band.show_banner(_t("keyset.key7"), _t("keyset.key8").format(key=keys))

    def _on_global_fired(self, name: str) -> None:
        """전역 키가 눌렸다: [트리거] · [액자 캡처] 단추와 똑같이 동작한다(FR-7 키 설정 표 ⑦)."""
        if not self._globals_wanted():
            return
        self.eventlog.emit("global_key_fired", row=name)
        self.on_command("request.trigger" if name == "global_trigger" else "request.capture")

    def open_about(self) -> None:
        """앱 정보 창(AC-NF-4, 결정 0043): 이미지는 해시를 기록한 앱 자원이다."""
        if self._about_dialog is None:
            from ..core import resources
            dlg = QDialog(self.shell)
            dlg.setWindowTitle(screens.ABOUT_TITLE)
            view = screens.AboutView(resources.about_image_path(), dlg)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(view)
            lay.setSizeConstraint(QLayout.SetFixedSize)   # D-064: 창이 내용(이미지)보다 작아져 잘리지 않게 한다
            self._about_view = view
            self._about_dialog = dlg
        self._about_dialog.show()
        self._about_dialog.raise_()

    def _on_appearance(self, choice: str) -> None:
        applied = self.appearance.apply(choice)
        self._save(appearance=choice)
        self.eventlog.emit("appearance_changed", choice=choice, scheme=applied)

    def _session_stt_language(self) -> str:
        """세션의 음성 인식 언어 코드: 진행 중인 세션이 시작할 때 정한 값, 세션이 없으면 설정의 값(없거나 목록 밖이면 `ko`)."""
        from ..core import languages
        rt = self.runtime
        if rt is not None and getattr(rt, "stt_language", None):
            return rt.stt_language
        if rt is None and self._last_stt_language:
            return self._last_stt_language
        return languages.normalize_stt(self.data.get("stt_language"))

    def _on_app_language(self, choice: str) -> None:
        """설정의 앱 언어(FR-16). 저장만 하고 화면은 다시 시작할 때 바뀐다(결정 0131)."""
        self._save(app_language=choice)
        self.eventlog.emit("app_language_changed", choice=choice)

    NO_KEY_BANNER = (_t("ctl.no_key_banner"), _t("ctl.no_key_banner_2"))
    # 점검 상태 줄(AC-FR1-23 원문). 시작 전에 확인한 것만 적고 "확인됨" 이라고 쓰지 않는다.
    CHECK_LINE_SUBSCRIPTION = _t("ctl.check_line_subscription")
    CHECK_LINE_API = _t("ctl.check_line_api")
    NO_CLAUDE_BANNER = (_t("label.claude_not_found"), _t("ctl.no_claude_banner_2"))

    def refresh_start_check(self, provider: Optional[str] = None, models: bool = True) -> None:
        """시작 가능 여부를 다시 점검한다(D-101). 원인이 있으면 띠를 두고 [세션 시작] 을 끄고, 없으면 띠를 지운다.
        점검 시점: 키 저장 · 삭제, claude 경로 변경, 제공자 변경, 설정 창을 닫을 때, 시작 화면이 다시 보일 때."""
        if self._ended or self.runtime is not None:
            return
        try:
            sp = self.shell.start_page
            sp.reload_default_prompt(self.data)
            if not self.claude_path:
                sp.show_check_line("")
                sp.show_problem(*self.NO_CLAUDE_BANNER, blocking=True)
                self._reveal_for_banner("claude")
                return
            provider = provider or sp.values().get("provider") or settings.DEFAULT_PROVIDER
            if provider == "claude_api" and not self._key_saved():
                sp.show_check_line("")
                sp.show_problem(*self.NO_KEY_BANNER, blocking=True)
                self._reveal_for_banner("key")
                return
            self._start_banner_kind = None
            line = self.CHECK_LINE_API if provider == "claude_api" else self.CHECK_LINE_SUBSCRIPTION
            sp.show_check_line(line)
            if sp.blocked:                  # 이 점검이 둔 띠만 지운다(시작 시도 뒤의 실패 띠는 다음 시도 때 새로 평가한다)
                sp.show_problem("")
        except RuntimeError:                # 종료 중에 위젯이 이미 지워진 경우
            pass

    def _reveal_for_banner(self, kind: str) -> None:
        """조치가 5. claude 실행 파일 절 안에 있는 띠(API 키 없음 · claude 없음 · 지정 경로 없음)가 새로 나타날 때 한 번 그 절로 스크롤하고
        초점을 옮긴다(AC-FR1-32). 사용자가 초점이나 스크롤을 옮긴 뒤에는 같은 띠가 다시 나타나기 전에는 옮기지 않는다
        (띠가 사라지면 `_start_banner_kind` 를 비우므로 같은 사유로 다시 나타나면 다시 옮긴다)."""
        if getattr(self, "_start_banner_kind", None) != kind:
            self._start_banner_kind = kind
            self.shell.start_page.reveal_banner_target(kind)

    # ------------------------------------------------------------------ 음성 인식 언어 · 보조 프로세스 (FR-4 · FR-16, 결정 0162 · 0167)
    def _stt_command(self) -> tuple:
        """(앞에 붙일 명령 목록, 추가 인자). 시험 주입(`Deps.stt_helper`) → 개발 옵션(`--dev-stt-helper`) → 묶은 앱 → 설정 폴더 순이다."""
        if self.deps.stt_helper is not None:
            prefix, extra = self.deps.stt_helper()
            return list(prefix), list(extra)
        dev = self.dev.get("stt_helper")
        if dev:
            extra = ["--scenario", str(self.dev.get("stt_helper_scenario"))] if self.dev.get("stt_helper_scenario") else []
            return [str(dev)], extra
        bundled = resources.bundled_stt_helper_path()      # 묶은 앱: 묶음 안의 미리 빌드한 실행 파일
        return [str(bundled) if bundled is not None else str(Path(self.config_dir) / "helper" / "stt_speech")], []

    def _check_saved_stt_language(self) -> None:
        """저장된 음성 인식 언어가 표 밖이면 한국어로 읽고 안내 글을 정한다(NEW-59 · 59N). 사건은 앱을 한 번 실행하는 동안 한 번이다."""
        self._stt_fallback_text = ""
        if "stt_language" not in self.data:
            return
        v = self.data.get("stt_language")
        if languages.is_saved_value_valid(v):
            return
        name = languages.retired_name(v, i18n.language())
        if name is None and isinstance(v, str) and v:
            name = '"%s"' % v
        self._stt_fallback_text = _t("newlang.new59").format(language=name) if name else _t("newlang.new59n")
        if not getattr(self, "_stt_fallback_logged", False):
            self._stt_fallback_logged = True
            self.eventlog.emit("stt_language_fallback", saved_value=v if isinstance(v, str) else repr(v)[:40])

    def _sync_language_settings(self) -> None:
        """설정의 음성 인식 언어 칸: 세션 중 비활성, 지원하지 않는 언어의 회색 항목(NEW-58), 저장된 언어 안내(NEW-59)."""
        form = self.shell.start_page
        self._check_saved_stt_language()
        try:
            form.set_stt_fallback_notice(self._stt_fallback_text)
        except RuntimeError:                # 종료 중에 위젯이 이미 지워진 경우
            return
        if self._stt_locales is not None:
            self._apply_unsupported()
        else:
            self._load_locales()

    def _load_locales(self) -> None:
        if self._stt_locales_loading:
            return
        self._stt_locales_loading = True
        prefix, extra = self._stt_command()
        cmd = list(prefix) + list(extra)
        fn = self.deps.list_locales
        bridge = self._locales_bridge

        _gc_hold()      # 작업 스레드가 모듈을 불러오는 동안 순환 쓰레기의 수집이 이 스레드에서 실행되어 주 스레드의 Qt 객체를 지우지 않게 한다(D-222)

        def work():
            try:
                try:
                    if fn is not None:
                        lst = fn(cmd, 5.0)
                    else:
                        from ..platform.stt import stt_speech
                        lst = stt_speech.list_locales(cmd, 5.0)
                except Exception:  # noqa: BLE001
                    lst = None
            finally:
                _gc_release()   # 수집 상태는 제어기의 수명이나 완료 신호의 처리와 상관없이 불러오기가 끝나면 되돌린다(D-223)
            try:
                bridge.done.emit(lst)
            except RuntimeError:        # 제어기가 이미 지워진 뒤(종료 중)이면 알릴 곳이 없다. 예외가 스레드 밖으로 나가 종료 중 stderr 에 쓰지 않게 한다(D-213)
                pass
        threading.Thread(target=work, name="stt-locales", daemon=True).start()

    def _on_locales(self, lst) -> None:
        self._stt_locales_loading = False
        if lst is not None:
            self._stt_locales = set(str(x) for x in lst)
        try:
            self._apply_unsupported()
        except RuntimeError:
            pass

    def _apply_unsupported(self) -> None:
        form = self.shell.start_page
        if self._stt_locales is None:                    # 조회에 실패했으면 어느 항목도 회색으로 하지 않는다
            form.set_unsupported_locales(set())
            return
        form.set_unsupported_locales({c for c in languages.CODES if languages.locale(c) not in self._stt_locales})

    def _key_saved(self):
        """키가 저장되어 있는지(값은 보관하지 않는다). 읽지 못하면 None."""
        try:
            return self.key_store().get() is not None
        except Exception:
            return None

    def _on_key_submitted(self, key: str) -> None:
        self.eventlog.register_secret(key)
        try:
            self.key_store().set(key)
            self._notice_text(_t("ctl.on_key_submitted_240"))
            self.shell.start_page.set_key_saved(True)
            self.refresh_start_check()
        except Exception as e:      # 키 · 사유 본문을 남기지 않는다
            self.eventlog.emit("error", module="api_key_store", kind="io", detail=type(e).__name__)
            self._notice_text(_t("ctl.on_key_submitted_241"))
            self.shell.start_page.show_key_error(_t("ctl.on_key_submitted_242"))

    def _on_key_delete(self) -> None:
        try:
            self.key_store().delete()
            self._notice_text(_t("ctl.on_key_delete_243"))
            self.shell.start_page.set_key_saved(False)
            self.refresh_start_check()
        except Exception as e:
            self.eventlog.emit("error", module="api_key_store", kind="io", detail=type(e).__name__)
            self._notice_text(_t("ctl.on_key_delete_244"))
            self.shell.start_page.show_key_error(_t("ctl.on_key_delete_244"))

    # ------------------------------------------------------------------ 세션 시작
    def start_session(self, params: dict) -> bool:
        """세션 시작 화면의 [세션 시작]. 성공하면 세션 화면으로 바꾼다. 실패하면 시작 화면에 남고 사유를 표시한다."""
        if self.runtime is not None:
            return False
        if not self.claude_path:
            self.eventlog.emit("error", module="app", kind="no_claude", detail="claude 를 찾지 못했다")
            self.refresh_start_check()
            return False
        self._session_claude = (self.claude_path, self.found)     # 세션 중 설정의 경로 변경은 다음 세션부터 적용한다(AC-FR1-26)
        provider = params.get("provider") or settings.DEFAULT_PROVIDER
        api_key = None
        if provider == "claude_api":
            try:
                api_key = self.key_store().get()
            except Exception as e:
                self.eventlog.emit("error", module="api_key_store", kind="io", detail=type(e).__name__)
            if not api_key:
                self.refresh_start_check(provider)
                return False
            self.eventlog.register_secret(api_key)
        self._params = dict(params)
        self._session_key = api_key                    # 세션 동안 메모리에만 둔다(일회성 호출이 시작 때의 값을 쓴다, AC-FR1-26 ⑤). 로그 · 파일에 쓰지 않는다
        self._session_prompt = settings.resolve_session_prompt(self.data, params.get("session_prompt"), resources.default_session_prompt())[1]
        from ..core import languages as _langs
        changes = dict(provider=provider, model=params.get("model"), effort=params.get("effort"), source=params.get("source"))
        if params.get("stt_language") is not None:
            changes["stt_language"] = _langs.normalize_stt(params.get("stt_language"))      # 음성 인식 언어도 시작할 때 저장한다(AC-FR1-29 ③)
        self._save(**changes)      # 저장 위치는 세션 폴더를 만든 뒤에 기억한다(D-044 관찰)
        bridge = self.view.bridge
        try:
            rt = self.deps.runtime_builder(
                params=params, data=self.data, devopts=self.dev, config_dir=self.config_dir,
                save_base=params.get("save_dir") or str(Path.home() / "Documents" / "ProfKangRAB"),
                claude_path=self._session_claude[0], claude_is_script=self._session_claude[1].is_script if self._session_claude[1] else None,
                parent_env=self.environ, procs=self.procs, eventlog=self.eventlog, context=self.context,
                api_key=api_key, on_card=bridge.post_card, on_notice=bridge.post_notice,
                on_error=self._post_error, model_factory=self.deps.model_factory)
        except OSError as e:
            self.eventlog.emit("error", module="session", kind="io", detail=type(e).__name__)
            # 시작 화면의 사유란에 사유와 조치를 표시한다(AC-FR9-21 의 `io`, D-044). 세션 화면으로 가지 않는다
            self.view_start.show_problem(_t("ctl.abort_start_245") + error_text.card_text("io", _t("ctl.start_session_246")))
            self._notice_text(_t("ctl.start_session_247"))
            self._session_key = self._session_prompt = None
            return False
        if not self.dev.get("save_dir"):
            self._save(save_dir=params.get("save_dir") or None)
        self.view_start.show_problem("")
        self.runtime, self._starting = rt, rt
        self._last_stt_language = getattr(rt, "stt_language", None)     # 세션이 끝난 뒤의 정리 문서 요청도 이 값을 쓴다
        rt.set_init_hook(self._start_bridge.ok.emit)
        if not rt.start():
            self.runtime = self._starting = None
            rt.close()
            self._session_key = self._session_prompt = None
            self._notice_text(_t("ctl.start_session_248"))
            return False
        if self.runtime is not rt:               # 시작 확인이 실패하여 이미 취소되었다(`_abort_start`)
            return False
        if self._starting is rt:
            if getattr(getattr(rt.model, "config", None), "effort", None):
                # 첫 `/effort` 의 init 이 오면 인증 출처를 확인한 뒤에 세션 화면으로 간다(질의는 그때까지 보내지 않는다)
                self.view_start.show_checking(True)
                self._start_timer.start(START_CHECK_MS)
            else:
                self._enter_session(rt)       # effort 가 없으면 첫 요청의 init 이 확인한다(결정 0056 의 질의 차단)
        return True

    def _on_start_ok(self, _init) -> None:
        rt = self._starting
        if rt is not None and rt is self.runtime:
            self._enter_session(rt)

    def _enter_session(self, rt) -> None:
        self._starting = None
        self._start_timer.stop()
        self.view_start.show_checking(False)
        params = self._params
        self._diagram_results.clear()
        self._diagram_pool = diagram.DiagramPool(
            folder=rt.folder, plugin_dir=self.dev.get("diagram_plugin_dir") or resources.diagram_plugin_dir(),
            oneshot_factory=lambda cwd, purpose="diagram", **kw: self._make_oneshot(cwd, purpose, **kw),
            eventlog=self.eventlog, session_log=rt.log,
            timeout_s=float(self.dev.get("diagram_timeout_s") or diagram.TIMEOUT_S))
        self.view.ai.refresh_gates()
        self._started_mono = time.monotonic()
        self.view.set_source_note(_t("ctl.m_249") % (source_display(params.get("source")) or _t("ctl.enter_session_250"),
                                                     languages.app_name(self._session_stt_language(), i18n.language())))
        self.view.start_clock()               # 머리 행의 "세션 hh:mm:ss": 수집 전에는 00:00:00 에서 멈춰 있다(결정 0164)
        self.view.set_clock_source(self._clock_source())
        self.shell.session_started()
        # D-081: 시작 단계마다 따로 보호한다. 한 단계가 실패해도 오류를 표시하고 나머지 단계를 계속한다.
        try:
            self._start_audio(params)
        except Exception as e:  # noqa: BLE001
            detail = _t("ctl.detail") % (type(e).__name__, e)
            self.eventlog.emit("error", module="audio", kind="start_failed", detail=detail)
            self._on_audio_state(COLLECT_STOPPED, detail)
        self._apply_globals()                 # 전역 키는 세션이 진행되는 동안만 등록한다(결정 0141 4항)
        self.refresh_status()

    def _abort_start(self, kind: str, detail: str = "") -> None:
        """시작 확인이 실패했다: 세션을 시작하지 않는다(AC-FR1-14). 시작한 프로세스만 PID 로 종료하고, 앱이 만든 빈 세션
        폴더를 지우며, 시작 화면에 사유와 조치를 표시한다. 앱은 종료하지 않는다."""
        rt = self._starting
        if rt is None:
            return
        self._starting = None
        self._start_timer.stop()
        self.runtime = None
        self.view_start.show_checking(False)
        try:
            rt.close()
        except Exception:
            pass
        discard_session_folder(rt.folder)
        self._session_key = self._session_prompt = None
        text = error_text.card_text(kind if kind in ERROR_KINDS else "process_exit")
        self.view_start.show_problem(_t("ctl.abort_start_245") + text)
        self.eventlog.emit("session_start_aborted", kind=kind)
        self.refresh_status()

    def _make_audio_source(self, params: dict):
        """세션의 음성 소스(시험 입력 파일 · 마이크 · 시스템 사운드). 반환: (소스, 입력 파일 경로 | None)."""
        source = params.get("source") or "system_sound"
        path = self.dev.get("audio_file")
        if path:
            from ..platform.audio.file_source import FileSource
            return FileSource(path, 1.0 if self.dev.get("speed") is None else self.dev.get("speed"), eventlog=self._source_log()), path
        if source == "system_mic":
            if self.deps.mic_factory is not None:
                return self.deps.mic_factory(self._source_log()), None
            from ..platform.audio.mic_source import MicSource
            return MicSource(eventlog=self._source_log()), None
        return self._system_sound_source(), None

    def _source_log(self):
        """수집 소스에 주는 이벤트 로그. `capture_start` 는 첫 음성 블록을 받은 때 남긴다(결정 0178 S10-26)."""
        if self._cap_log is None:
            self._cap_log = _DeferredStartLog(self.eventlog)
        return self._cap_log

    def _new_audio_source(self):
        """권한 없음으로 끝난 시도 뒤의 새 수집 소스(결정 0178 3항: [재생] 을 누를 때마다 보조 프로그램을 새로 시작한다)."""
        return self._make_audio_source(self._params)[0]

    def _on_first_block(self) -> None:
        """수집 소스가 첫 음성 블록을 냈다(소스 스레드). 시도가 끝나고 `capture_start` 를 남긴다. 화면에 할 일이 있으면 주 스레드로 넘긴다."""
        if self._cap_log is not None:
            self._cap_log.flush()
        self.view.bridge.post_capture("수집 시작", "")           # 수집 상태는 주 스레드가 바꾼다(결정 0178 · b56 M1)

    def _on_capture_started(self) -> None:
        """주 스레드: 첫 음성 블록을 받았다. 시도 중에는 바꾸지 않던 수집 상태를 "수집 중" 으로 바꾸고(S10-26), 권한 안내 띠를 지우고
        미룬 일시 정지의 끝을 쓴다."""
        if not self._attempt_pending or self._capture_state not in (COLLECT_BEFORE, COLLECT_PAUSED) or self._ended:
            return                                    # 시도가 이미 끝났거나(정지 · 종료 · 중단) 늦게 온 블록이다
        self._attempt_pending = False
        self._permission_band = None
        self._capture_state, self._capture_detail = COLLECT_RUNNING, ""
        if self._pause_finish_pending:
            self._pause_finish_pending = False
            self._finish_pause(True)
        self._apply_capture_banner(COLLECT_RUNNING, "")
        self.refresh_status()

    def _on_permission_denied(self) -> None:
        """주 스레드: [재생] 의 시도가 권한 없음으로 끝났다(결정 0178). 수집 상태는 이미 누르기 전으로 되돌렸다. 권한 안내 띠를 표시하고
        사건 `permission_band` 를 남기며, 소스를 새것으로 바꿔 다음 [재생] 이 새 시도가 되게 한다."""
        self._attempt_pending = False
        key = "microphone" if self._params.get("source") == "system_mic" else "screen_recording"
        if key == "microphone":
            self._permission_band = (_t("newlang.new69"), _t("newlang.new70"))
        else:
            self._permission_band = (_t("newlang.new67"), _t("newlang.new68"))
        self.view.set_permission_guide("")
        self.eventlog.emit("permission_band", permission=key, attempt=self._attempt_no,
                           **{"from": "paused" if self._attempt_prev == COLLECT_PAUSED else "idle"})
        if self._cap_log is not None:
            self._cap_log.discard()
        if self._tap is not None:
            self._tap.retire()
        self._apply_capture_banner(self._capture_state, self._capture_detail)
        self.refresh_status()

    def _start_audio(self, params: dict) -> None:
        source = params.get("source") or "system_sound"
        replay = self.dev.get("replay")
        self._stt_exit, self._stt_band, self._stt_prep, self._stt_prep_pct = None, None, None, -1
        self._stt_retrying, self._stt_exit_paused, self._stt_ready = False, False, False
        self._attempt_no, self._attempt_pending, self._attempt_prev, self._play_denied = 0, False, None, False
        self._permission_band, self._pause_finish_pending, self._ever_played = None, False, False
        self._cap_log = _DeferredStartLog(self.eventlog)
        self._set_stt_blocked(False)
        self.view.set_stt_guide("normal")
        if replay:
            self._start_replay(replay)       # D-066: 음성 수집 · STT 를 대신해 전사 조각을 주입한다
            return
        audio, path = self._make_audio_source(params)
        # 결정 0150: 세션은 수집 전 상태로 열린다. 소스(장치)는 처음 [재생] 에서 연다. 보조 프로세스는 지금 시작해 모델을 준비한다(결정 0167)
        self._set_stt_blocked(True)
        self._launch_stt(audio, 1)
        self._capture_state = COLLECT_BEFORE
        self._apply_capture_banner(COLLECT_BEFORE, "")
        self._check_permission_at_start(source, path)

    def _launch_stt(self, audio, start_n: int) -> None:
        """`stt_speech` 보조 프로세스를 시작한다(`SttPipeline`, 기술 계획 2-8절). `start_n`: [다시 시도] 때 이어서 매길 조각 번호."""
        from ..platform.stt.pipeline import SttPipeline
        prefix, extra = self._stt_command()
        locale = languages.locale(self._session_stt_language())
        bridge, rt = self.view.bridge, self.runtime
        self._stt_gen += 1
        gen = self._stt_gen
        self._stt_ready = False
        self._tap = _TapSource(audio, self._on_audio_state, self._new_audio_source, self._on_first_block)
        wall0, mono0 = datetime.now().astimezone(), time.monotonic()

        def iso(m: float) -> str:
            return (wall0 + timedelta(seconds=m - mono0)).isoformat(timespec="milliseconds")

        def on_segment(seg):                           # 읽기 스레드에서 곧바로 이력에 넣는다(`wait_final` 이 기다리는 값이다)
            if rt.on_segment(seg):
                bridge.post_segment(seg)

        def on_partial(pt):
            if gen != self._stt_gen or self._capture_state not in (COLLECT_RUNNING, COLLECT_NO_INPUT):
                return                                 # 일시 정지 · 중단 뒤의 잠정은 쓰지 않는다(Q-48)
            sw, ew = iso(pt.start_mono), iso(pt.end_mono)
            rt.on_partial(pt, sw, ew)
            bridge.post_stt("partial", (gen, pt.text, hms(sw)))

        def on_error(err):                             # 구간 하나의 실패: 잠정 행을 지우고 오류 횟수에 더한다
            rt.close_open()
            bridge.post_stt("clear_partial", gen)
            self._on_stt_error(err)

        def on_dropped(_n):                            # 구간이 조각 없이 끝났다(본문이 빈 final, 결정 0166): 열린 구간과 잠정 행을 닫는다
            rt.close_open()
            bridge.post_stt("clear_partial", gen)

        pl = SttPipeline(prefix, locale, start_n, self.eventlog, extra_args=extra)
        self.pipeline = pl
        rt.stt_cut = pl.cut
        pl.start(self._tap, on_segment, None, on_error, on_dropped, on_partial, begin=False,
                 on_asset=lambda d: bridge.post_stt("asset", (gen, d)),
                 on_ready=lambda: bridge.post_stt("ready", gen),
                 on_exit=lambda reason, detail: bridge.post_stt("exit", (gen, reason, detail)))
        self._register_stt_pid(pl, prefix)

    def _register_stt_pid(self, pl, prefix) -> None:
        """시작한 보조 프로세스의 PID 를 기록한다(비정상 종료 뒤의 고아 정리 · 종료는 그 PID 로만)."""
        pid = pl.pid
        if pid is None:
            return
        self._stt_pid = pid
        try:
            self.registry.add(pid, "stt_speech", str(prefix[-1]))
        except Exception:  # noqa: BLE001
            pass
        self.eventlog.emit("process_start", role="stt_speech", pid=pid)

    def _release_stt_pid(self) -> None:
        pid, self._stt_pid = getattr(self, "_stt_pid", None), None
        if pid is not None:
            try:
                self.registry.remove(pid)
            except Exception:  # noqa: BLE001
                pass
            self.eventlog.emit("process_exit", role="stt_speech", pid=pid)

    # ---- 보조 프로세스의 사건(주 스레드) ----
    def _set_stt_blocked(self, blocked: bool) -> None:
        try:
            self.view.set_play_blocked(blocked)
        except RuntimeError:
            pass

    def _on_stt_ui(self, kind: str, payload) -> None:
        if self._ended:
            return
        gen = payload if kind in ("ready", "clear_partial") else payload[0]
        if gen != self._stt_gen:
            return                                     # 옛 세대(다시 시도 전)의 늦은 사건
        try:
            if kind == "partial":
                if self._capture_state in (COLLECT_RUNNING, COLLECT_NO_INPUT):
                    self.view.transcript.set_partial(payload[1], payload[2])
            elif kind == "clear_partial":
                self.view.transcript.clear_partial()
            elif kind == "asset":
                self._on_stt_asset(payload[1])
            elif kind == "ready":
                self._on_stt_ready()
            elif kind == "exit":
                self._on_stt_exit(payload[1], payload[2])
        except RuntimeError:
            pass

    def _on_stt_asset(self, d: dict) -> None:
        """`asset` 줄: `downloading` 이면 준비 칩을 보이고, `checking` · `installed` 이면 칩 없이 [재생] 만 끈다(결정 0167 3항)."""
        if self._stt_ready or self._stt_exit is not None and not self._stt_retrying:
            return
        state = d.get("state")
        if state == "downloading":
            frac = d.get("fraction")
            if isinstance(frac, (int, float)) and not isinstance(frac, bool):
                f = float(frac)
                pct = 100 if f >= 1.0 else min(99, max(0, int(f * 100)))       # 0.999 → 99%: 100% 는 보조 프로세스가 1.0 을 알린 때에만(AC-FR4-18 ⑥)
                self._stt_prep_pct = max(self._stt_prep_pct, pct)
                self._stt_prep = _t("newlang.new47").format(pct=self._stt_prep_pct)
            else:
                self._stt_prep = _t("newlang.new48")
            if self._capture_state == COLLECT_BEFORE:
                self.view.set_stt_guide("preparing")
        else:
            self._stt_prep = None
        self._set_stt_blocked(True)
        self.refresh_status()

    def _on_stt_ready(self) -> None:
        self._stt_ready = True
        self._stt_prep = None
        self._stt_prep_pct = -1
        self._stt_retry_timer.stop()
        was_exit = self._stt_exit is not None
        band = self._stt_band
        self._stt_exit = None
        self._stt_retrying = False
        self._stt_band = None
        self._set_stt_blocked(False)
        if band is not None and self._capture_state == COLLECT_STOPPED:
            # 수집 중에 끝났다가 다시 시도로 살아났다: 띠를 지우고 소스를 다시 연다
            self._capture_state = COLLECT_PAUSED if self._stt_exit_paused else COLLECT_BEFORE
            self._stt_exit_paused = False
            self._apply_capture_banner(self._capture_state, "")
            self.play_capture()
        else:
            if was_exit or self._capture_state == COLLECT_BEFORE:
                self.view.set_stt_guide("normal")
        self.refresh_status()

    _STT_EXIT_TEXT = {
        "unsupported_locale": ("newlang.new50", "newlang.new51", False),
        "os_too_old": ("newlang.new56", "newlang.new57", False),
        "asset_failed": ("newlang.new52", "newlang.new53", True),
        "analyzer_error": ("newlang.new54", "newlang.new55", True),
    }

    def _on_stt_exit(self, reason: str, detail: str) -> None:
        """보조 프로세스가 스스로 끝났다(2-8-4절 5항 처리표). `ready` 뒤의 사유는 모두 `analyzer_error` 로 본다."""
        if self._stt_ready or reason not in self._STT_EXIT_TEXT:
            reason = "analyzer_error"
        self._release_stt_pid()
        k1, k2, retry = self._STT_EXIT_TEXT[reason]
        title, body = _t(k1), _t(k2)
        self._stt_exit = reason
        self._stt_ready = False
        self._stt_retrying = False
        self._stt_retry_timer.stop()
        self._stt_prep = None
        self._stt_prep_pct = -1
        rt = self.runtime
        if rt is not None:
            rt.close_open()
        self.view.transcript.clear_partial()
        was_band = self._stt_band is not None and self._capture_state == COLLECT_STOPPED     # D-179: 띠의 [다시 시도] 로 시작한 프로세스가 ready 전에 끝났다
        if was_band or self._capture_state in (COLLECT_RUNNING, COLLECT_NO_INPUT, COLLECT_PAUSED):
            if not was_band:
                self._stt_exit_paused = self._capture_state == COLLECT_PAUSED
            self._capture_state = COLLECT_STOPPED
            self._capture_detail = ""
            self._stt_band = (title, body, retry)
            p = self.pipeline
            if p is not None:
                try:
                    p.stop()                           # 소스를 닫는다(보조 프로세스는 이미 끝났다)
                except Exception:  # noqa: BLE001
                    pass
            self._apply_capture_banner(COLLECT_STOPPED, "")
        else:
            self._stt_band = None
            self.view.set_stt_guide("error", title, body, retry=retry, retry_enabled=True)
            self._set_stt_blocked(True)
        self.eventlog.emit("stt_exit_handled", reason=reason, in_session=self._stt_band is not None)
        self.refresh_status()

    def retry_stt(self) -> None:
        """[다시 시도]: 보조 프로세스를 `--start-n` = 이어서 매길 번호로 다시 시작하고 `ready` 를 30초까지 기다린다. 기다리는 동안 단추는 꺼진다."""
        if self._ended or self.runtime is None or self._stt_retrying or self._stt_exit is None:
            return
        if self._stt_exit in ("unsupported_locale", "os_too_old"):
            return
        old = self.pipeline
        start_n = getattr(old, "next_n", 1) if old is not None else 1
        if old is not None:
            try:
                old.stop()
                old.join(2.0)
            except Exception:  # noqa: BLE001
                pass
        try:
            audio, _path = self._make_audio_source(self._params)
            self._stt_retrying = True
            self._show_retry_state(enabled=False)
            self._launch_stt(audio, start_n)
        except Exception as e:  # noqa: BLE001
            self.eventlog.emit("error", module="stt", kind="stt_fail", detail=type(e).__name__)
            self._stt_retrying = False
            self._show_retry_state(enabled=True)
            return
        self._stt_retry_timer.start(30000)
        self.eventlog.emit("stt_retry", start_n=start_n)

    def _show_retry_state(self, enabled: bool) -> None:
        try:
            if self._stt_band is not None:
                t, b, r = self._stt_band
                self.view.banner.show_banner(t, b, retry=r, retry_enabled=enabled)
            else:
                reason = self._stt_exit or "analyzer_error"
                k1, k2, r = self._STT_EXIT_TEXT[reason]
                self.view.set_stt_guide("error", _t(k1), _t(k2), retry=r, retry_enabled=enabled)
        except RuntimeError:
            pass

    def _on_retry_timeout(self) -> None:
        """30초 안에 `ready` 도 종료도 없으면 단추를 다시 켠다."""
        if self._stt_retrying and not self._stt_ready:
            self._stt_retrying = False
            self._show_retry_state(enabled=True)

    def _check_permission_at_start(self, source: str, audio_file) -> None:
        """세션을 시작할 때의 운영체제 권한 조회(결정 0150 ⑤ → 결정 0161): 보조 프로그램을 실행하지 않고 장치도 열지 않는다.
        "허용되지 않음" 이어도 수집 상태를 "중단" 으로 하지 않고 [재생] 을 끄지 않는다(화면 기록의 조회는 묻지 않은 상태와 거부를
        구별하지 못한다). 처음 [재생] 에서 보조 프로그램을 실행해 운영체제의 권한 요청을 받고, 권한 없음으로 끝나면 기존 오류 카드
        (`no_permission`)를 쓴다. 안내 표시는 명세가 오면 붙이며, 그때까지 `permission_hint` 에 해당 소스의 권한 키를 둔다.
        시험용 소스를 주입한 세션에서는 조회하지 않는다."""
        self.permission_hint = None
        self.view.set_permission_guide("")
        if audio_file:
            return
        injected = self.deps.mic_factory if source == "system_mic" else self.deps.system_sound_factory
        if self.deps.permission_status is None and injected is not None:
            return
        from ..platform import permissions as P
        key = "microphone" if source == "system_mic" else "screen_recording"
        try:
            denied = self._permission_values().get(key) == P.DENIED
        except Exception:  # noqa: BLE001
            denied = False
        self._start_permission_key = key
        if denied:
            self.permission_hint = key
            self.view.set_permission_guide(_t("newlang.new46") if key == "microphone" else _t("newlang.new45"))
            self.eventlog.emit("permission_guide", permission=key, check="denied")   # 본문 · 경로 · 이름은 남기지 않는다

    def _start_replay(self, path: str) -> None:
        from ..core import replay as replay_mod
        rt, bridge = self.runtime, self.view.bridge
        try:
            items, errors = replay_mod.load(path)
        except OSError as e:
            items, errors = [], ["읽을 수 없다: %s" % type(e).__name__]
        for why in errors:
            self.eventlog.emit("dev_option_error", option="--dev-replay", reason=why)
        speed = self.dev.get("speed")

        def on_segment(seg):
            if self._capture_state == COLLECT_PAUSED:
                return                      # 전사 재생은 소스가 없으므로 일시 정지 중에 도착한 조각을 버린다(임의)
            if rt.on_segment(seg):
                bridge.post_segment(seg)

        feeder = replay_mod.ReplayFeeder(items, 1.0 if speed is None else speed)
        self.pipeline = feeder
        self._on_audio_state("수집 중", "전사 재생")
        feeder.start(on_segment)

    def _system_sound_source(self):
        """시스템 사운드 수집(ScreenCaptureKit 보조 프로그램, 결정 0065). 보조 프로그램이 없거나 권한이 없으면 소스가
        `중단` 상태와 상세를 낸다(`_on_audio_state` 가 오류 카드로 표시한다)."""
        from ..core import resources
        bundled = resources.bundled_helper_path()      # 묶은 앱: 묶음 안의 미리 빌드한 실행 파일(결정 0065 3항)
        # 개발 환경: `tools/build_sck_helper.py` 가 설정 폴더에 만든다
        helper = str(bundled) if bundled is not None else str(Path(self.config_dir) / "helper" / "sck_audio")
        if self.deps.system_sound_factory is not None:
            return self.deps.system_sound_factory(self._source_log(), helper)
        from ..platform.audio.system_sound import SystemSoundSource
        return SystemSoundSource(helper, eventlog=self._source_log())

    def _on_audio_state(self, state: str, detail: str = "") -> None:
        if state == COLLECT_STOPPED and self._attempt_pending:
            from ..platform.audio.system_sound import REASON_TEXT
            if REASON_TEXT["no_permission"] in (detail or ""):
                # 결정 0178: [재생] 의 시도가 권한 없음으로 끝났다. 시도 중에는 수집 상태를 바꾸지 않았으므로 그대로 두고,
                # 오류 카드 · 수집 중단 띠를 쓰지 않는다. 시도의 끝은 주 스레드가 정리한다(`_on_permission_denied`).
                if not self._play_denied:
                    self._play_denied = True
                    self._capture_detail = ""
                    self.view.bridge.post_capture("권한 없음", detail or "")
                return
        if self._attempt_pending:
            if state not in (COLLECT_STOPPED, "종료"):
                return              # 시도 중: 첫 음성 블록(`_on_first_block`)이 수집 상태를 바꾼다. 소스가 먼저 내는 `수집 중` 은 버린다
            if state == COLLECT_STOPPED:
                # 시도의 끝을 알린 것이다. 시작 실패(S10-31 · AC-FR3-11 ⑩, 띠 UI-288 · UI-289, audio_start_failed)인지는 소스가
                # 붙인 접두어(`START_FAILED_PREFIX`)만으로 가른다. 접두어가 없는 "중단"(장치 열기 예외 등 소스가 스스로 다시 여는 경우)은
                # 수집 중단(audio_lost, UI-306)이며, 소스가 다시 열려 "수집 중" 을 알리면 수집 중으로 돌아온다(D-195).
                self._attempt_pending = False
        elif self._capture_state == COLLECT_PAUSED and state != "종료" or (
                self._capture_state == COLLECT_BEFORE and state in (COLLECT_RUNNING, COLLECT_NO_INPUT)):
            return                  # 일시 정지 중에는 수집 오류를 감시하지 않고(결정 0147 ⑦), 수집 전에는 소스가 열리지 않았다
        prev, self._capture_state = self._capture_state, state if state != "종료" else self._capture_state
        if state == COLLECT_RUNNING:
            self._permission_band = None            # 수집이 시작되면 권한 안내 띠는 사라진다(결정 0178, D-196): 시도의 첫 블록이 아닌 복구 경로도 같다
        if state != "종료":
            self._capture_detail = detail or ""
            self._capture_banner_post(state, detail or "")
        if state == COLLECT_STOPPED and prev != COLLECT_STOPPED:
            from ..platform.audio.system_sound import REASON_TEXT
            if REASON_TEXT["no_permission"] in (detail or ""):
                # 권한이 없어 끝난 것이다(종료 코드 3): `permission` 의 사유 · 조치와 권한 이름 · 허용 위치를 표시한다(D-056)
                self._post_error("permission", PERMISSION_SCREEN_TEXT,
                                 permission=getattr(self, "_start_permission_key", "screen_recording"), source="play")
            elif (detail or "").startswith(appstate.START_FAILED_PREFIX):
                # 시작 실패(D-083): 장치 끊김과 달리 스스로 이어지지 않는다. 예외 이름 · 메시지는 카드의 상세로만 붙인다
                self._post_error("audio_start_failed", detail.split(": ", 1)[1] if ": " in detail else "")
            else:
                self._post_error("audio_lost", detail or _t("ctl.on_audio_state_253"))

    def _capture_banner_post(self, state: str, detail: str) -> None:
        """수집 상태를 UI 스레드의 띠로 넘긴다(다른 스레드에서 부른다). 세션 화면이 없으면 건너뛴다."""
        v = getattr(self, "view", None)
        if v is not None:
            v.bridge.post_capture(state, detail)

    def _clock_source(self):
        """화면 시계의 시각 원천. 기본은 단조 시계이다. `--dev-clock-file` 이면 그 파일의 실수 한 줄을 읽는다(읽지 못하면 단조 시계).
        표시에만 쓰며 session.jsonl 의 사건 시각에는 적용하지 않는다."""
        path = self.dev.get("clock_file")
        if not path:
            return time.monotonic

        def src() -> float:
            try:
                return float(Path(path).read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                return time.monotonic()
        return src

    def _sync_clock(self) -> None:
        """세션 시계를 수집 상태에 맞춘다: 수집 중 · 입력 없음에만 센다(정지 확인 창이 떠 있어도 수집은 계속된다).
        일시 정지 · 중단 · 수집 전, 그리고 종료 처리 중(모든 종료 경로)에는 멈춘다."""
        running = (self._capture_state in (COLLECT_RUNNING, COLLECT_NO_INPUT) and not self._ended
                   and self.shell.machine.state is appstate.State.IN_SESSION)
        try:
            self.view.set_clock_running(running)
        except RuntimeError:
            pass

    def _apply_capture_banner(self, state: str, detail: str) -> None:
        if state == "권한 없음":                 # 소스 스레드가 넘긴 사건(`_on_audio_state`): 주 스레드에서 처리한다
            self._on_permission_denied()
            return
        if state == "수집 시작":
            self._on_capture_started()
            return
        from ..platform.audio.system_sound import REASON_TEXT
        if state == COLLECT_STOPPED and self._pause_finish_pending:
            self._pause_finish_pending = False          # 재개 시도가 중단으로 끝났다: 일시 정지의 끝은 실패한 시각이다(결정 0147 ⑦)
            self._finish_pause(False)
        self._sync_clock()
        denied = state == COLLECT_STOPPED and REASON_TEXT["no_permission"] in (detail or "")
        self._refresh_level()                 # 중단 · 재개 때 막대를 곧바로 맞춘다(D-069 LVL-3)
        try:
            self.view.set_capture_state(self._capture_state, self.shell.machine.state is appstate.State.ENDING)
        except RuntimeError:
            pass
        b = appstate.capture_banner(state, detail, denied)
        try:
            if state == COLLECT_STOPPED and self._stt_band is not None:
                t, bd, r = self._stt_band
                self.view.banner.show_banner(t, bd, retry=r, retry_enabled=not self._stt_retrying)
            elif self._permission_band is not None and state in (COLLECT_BEFORE, COLLECT_PAUSED):
                t, bd = self._permission_band                    # 권한 안내 띠(정보 색, 단추 없음, 결정 0178)
                self.view.banner.show_banner(t, bd, tone="info")
            elif b is None:
                self.view.banner.clear_banner()
            else:
                self.view.banner.show_banner(b.title, b.description)
        except RuntimeError:        # 종료 중에 화면이 이미 지워졌다
            pass

    # ------------------------------------------------------------------ 재생 · 일시 정지 · 정지 (결정 0147 · 0149 · 0150)
    def capture_state(self) -> Optional[str]:
        """수집 상태(수집 전 · 수집 중 · 입력 없음 · 일시 정지 · 중단). 세션 밖에서는 None 이다. 시험이 읽는다."""
        return self._capture_state if self.runtime is not None else None

    def _can_control_capture(self) -> bool:
        return (self.runtime is not None and not self._ended and self.shell.machine.state is appstate.State.IN_SESSION)

    def play_capture(self) -> bool:
        """[재생] · 세션 메뉴 "재생": 수집 전이면 처음 수집을 시작하고, 일시 정지 중이면 수집과 전사를 다시 시작한다.
        그 밖의 상태에서는 아무 일도 없다. 반환: 수집을 시작 · 재개했는지."""
        if not self._can_control_capture() or self._capture_state not in (COLLECT_BEFORE, COLLECT_PAUSED):
            return False
        if self.view.transport.play_blocked():             # 준비 중 · 준비 실패 · 보조 프로세스 종료 중에는 [재생] 이 꺼져 있다(결정 0167)
            return False
        if self._attempt_pending:                          # 시도 중의 [재생] 은 무시한다(S10-28)
            return False
        rt = self.runtime
        resuming = self._capture_state == COLLECT_PAUSED
        pipeline = self.pipeline
        self._play_denied = False
        self._attempt_prev = self._capture_state          # 권한 없음으로 끝나면 이 상태로 되돌린다(결정 0178 1항)
        self._ever_played = True
        tapped = pipeline is not None and self._tap is not None and getattr(pipeline, "_source", None) is self._tap
        if not tapped:
            self._capture_state = COLLECT_RUNNING          # 소스가 없는 입력(전사 재생 · 시작 실패 주입)은 시도가 없다
            self._capture_detail = ""
        ok = True
        try:
            if self._start_fail_armed:                 # 시험 주입(AC-FR3-12 · 16): 이 [재생] 이 시작 실패로 끝난다
                self._start_fail_armed = False
                ok = False
                self._capture_state = COLLECT_RUNNING      # 시작 실패는 수집 시작 실패와 같다: 일시 정지 · 수집 전에서도 중단으로 간다(S10-31)
                self._on_audio_state(COLLECT_STOPPED, "%s: 시험 주입" % appstate.START_FAILED_PREFIX)
            elif pipeline is not None and hasattr(pipeline, "resume"):
                if tapped:                              # 새 시도: 결과(첫 음성 블록 또는 종료)가 나올 때까지 기다린다(결정 0178 · S10-28)
                    self._attempt_no += 1
                    self._attempt_pending = True
                    self.eventlog.emit("capture_attempt", source=self._params.get("source") or "system_sound", attempt=self._attempt_no)
                ok = bool(pipeline.resume())
            else:
                self._on_audio_state(COLLECT_RUNNING, "전사 재생")      # 전사 재생 입력은 이미 흐르고 있다
        except Exception as e:  # noqa: BLE001
            ok = False
            detail = _t("ctl.detail") % (type(e).__name__, e)
            self.eventlog.emit("error", module="audio", kind="start_failed", detail=detail)
            self._attempt_pending = False
            self._capture_state = COLLECT_RUNNING
            self._on_audio_state(COLLECT_STOPPED, "%s: %s" % (appstate.START_FAILED_PREFIX, detail))
        if self._play_denied:                             # 권한 없음으로 끝났다(결정 0178): 수집 상태는 이미 되돌렸고 일시 정지 구간은 이어진다
            self.refresh_status()
            return False
        if not ok:
            self._attempt_pending = False
        if not ok and self._capture_state != COLLECT_STOPPED:
            self._capture_state = COLLECT_RUNNING
            self._on_audio_state(COLLECT_STOPPED, "%s: %s" % (appstate.START_FAILED_PREFIX, type(self).__name__))
        if resuming:
            if ok and tapped:                             # 일시 정지의 끝은 첫 음성 블록을 받은 때 쓴다(권한 없음이면 쓰지 않는다, AC-FR3-11 ③)
                self._pause_finish_pending = True
                if not self._attempt_pending:             # 첫 블록이 벌써 왔다
                    self._pause_finish_pending = False
                    self._finish_pause(True)
            else:
                self._finish_pause(ok)
        self.refresh_status()
        return ok

    def pause_capture(self) -> bool:
        """[일시 정지] · 세션 메뉴 "일시 정지": 수집 중 · 입력 없음일 때만. 소스를 닫고 진행 중인 구간을 그 시점에서 끝낸다."""
        if not self._can_control_capture() or self._capture_state not in (COLLECT_RUNNING, COLLECT_NO_INPUT):
            return False
        rt = self.runtime
        if self._pause_finish_pending:                      # 이전 일시 정지의 끝을 아직 쓰지 않았다: 지금 쓴다
            self._pause_finish_pending = False
            self._finish_pause(True)
        self._attempt_pending = False
        ts = rt.pause_begin()
        rt.abandon_open()                               # D-177: 끊긴 구간의 잠정은 확정이 없으면 요청에 쓰지 않는다
        self._pause_mono = time.monotonic()
        self._pause_start_ts = ts
        self._capture_state = COLLECT_PAUSED            # 닫는 소스가 늦게 알리는 상태는 무시한다(`_on_audio_state`)
        self._capture_detail = ""
        try:
            p = self.pipeline
            if p is not None and hasattr(p, "pause"):
                p.pause()
        except Exception as e:  # noqa: BLE001
            self.eventlog.emit("error", module="audio", kind="pause_failed", detail=type(e).__name__)
        self.eventlog.emit("capture_pause", ts=ts)
        try:
            self.view.transcript.clear_partial()           # Q-48: 누른 시점에 잠정 행을 지운다. 끊기(`C`)로 오는 확정은 조각이 된다
            self.view.transcript.add_pause(ts)
        except RuntimeError:
            pass
        self._apply_capture_banner(COLLECT_PAUSED, "")
        self.refresh_status()
        return True

    def _finish_pause(self, ok: bool) -> None:
        """일시 정지의 끝: `pause` `끝` 줄과 전사 문서의 구간 블록을 쓰고 전사 창의 구간 줄을 끝 시각이 붙은 모양으로 바꾼다.
        재생에 실패한 경우에도 실패한 시각이 끝이다(결정 0147 ⑦)."""
        rt = self.runtime
        if rt is not None:
            rt.resume_open()                    # 권고 62: 끊긴 구간은 [재생] 뒤에 진행 중이 아니다
        res = rt.pause_end() if rt is not None else None
        secs = int(max(0.0, time.monotonic() - self._pause_mono)) if self._pause_mono is not None else 0
        self._pause_mono = None
        if res is not None:
            start, end = res
            self.eventlog.emit("capture_resume", ts=end, ok=ok)
            try:
                self.view.transcript.close_pause(start, end, secs)
            except RuntimeError:
                pass

    def request_stop(self) -> None:
        """[정지]: 종료 흐름에 들어가기 전에 확인 창을 연다(결정 0149). 창이 떠 있는 동안 수집 · 전사는 계속된다."""
        if not self._can_control_capture():
            return
        if self._stop_dialog is not None:
            self._stop_dialog.raise_()
            return
        from .stopconfirm import MainInputBlock, StopConfirm
        collecting = self._capture_state in (COLLECT_RUNNING, COLLECT_NO_INPUT)
        dlg = StopConfirm(self.shell, _t("stopc.new29") if collecting else _t("stopc.new30"))
        self._stop_dialog = dlg
        dlg.end_chosen.connect(self._on_stop_confirmed)
        dlg.finished.connect(lambda _r=0, d=dlg: self._on_stop_dialog_closed(d))
        block = MainInputBlock(self.shell, dlg, block_all=True)   # 창이 떠 있는 동안 메인 창과 설정 창 등의 조작을 막는다(FR-11 ③, 결정 0173 2항)
        dlg._input_block = block
        block.install()
        dlg.show()
        self._sync_dialog_layer()

    def _on_stop_dialog_closed(self, dlg) -> None:
        block = getattr(dlg, "_input_block", None)
        if block is not None:
            block.remove()
        if self._stop_dialog is dlg:
            self._stop_dialog = None
        dlg.deleteLater()
        self._sync_dialog_layer()

    def _on_stop_confirmed(self) -> None:
        self.shell.request_quit()              # ⌘Q 와 같은 종료 흐름(AC-FR13-5)

    def _dismiss_stop_dialog(self) -> None:
        dlg, self._stop_dialog = self._stop_dialog, None
        if dlg is not None:
            try:
                dlg.dismiss()
            except RuntimeError:
                pass

    def _on_stt_error(self, err) -> None:
        self._stt_errors += 1
        self._post_error(err.kind, err.detail)

    # ------------------------------------------------------------------ 요청
    def on_command(self, cid: str) -> None:
        rt = self.runtime
        v = self.view
        if cid == "app.about":
            self.open_about()
        elif cid == "app.settings":
            self.open_settings()
        elif cid == "app.quit":
            self.shell.request_quit()
        elif cid == "session.pause":
            self.pause_capture()
        elif cid == "session.play":
            self.play_capture()
        elif cid == "session.open_folder":
            if rt is not None:
                (self.deps.open_url or self._open_url)(QUrl.fromLocalFile(str(rt.folder)))
        elif cid == "session.rebuild_summary":
            self.rebuild_summary()
        elif cid.startswith("request.") and self.shell.machine.state is not appstate.State.IN_SESSION:
            return                  # 종료 처리 중(④)에는 요청을 받지 않는다(D-071, FR-14 표 ④)
        elif cid == "request.trigger":
            if rt is not None:
                rt.trigger("button")
        elif cid == "request.capture":
            self.capture_frame()
        elif cid == "window.main":
            self.shell.show_main_window()
        elif cid == "window.frame":
            self.toggle_frame()
        elif cid == "window.minimize":
            self.shell.showMinimized()
        elif cid == "window.zoom":
            self.shell.showNormal() if self.shell.isMaximized() else self.shell.showMaximized()
        elif cid == "help.first_run_notice":
            self._show_first_run_notice()
        elif cid == "help.permissions":
            self._show_permissions()

    def _open_url(self, url) -> bool:
        from PySide6.QtGui import QDesktopServices
        return QDesktopServices.openUrl(url)

    def _show_permissions(self) -> None:
        """도움말 > 필요한 권한 확인…(AC-FR14-10): 세 권한의 상태를 읽어서 보인다. 권한을 요청하지 않는다."""
        from PySide6.QtWidgets import QLabel
        from ..platform import permissions as P
        try:
            st = dict((self.deps.permission_status or P.query_status)())
        except Exception:
            st = {}
        names = (("screen_recording", _t("ctl.names")), ("system_audio", _t("label.source_system_sound")), ("microphone", _t("ctl.names_3")))
        dlg = QDialog(self.shell)
        dlg.setWindowTitle(_t("ctl.show_permissions_035"))
        lay = QVBoxLayout(dlg)
        lines = {}
        for key, label in names:
            w = QLabel("%s: %s" % (label, st.get(key) or P.UNKNOWN))
            w.setObjectName("perm_" + key)
            lay.addWidget(w)
            lines[key] = w
        hint = QLabel(_t("ctl.hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._permission_dialog, self._permission_lines = dlg, lines
        self.eventlog.emit("permissions_viewed")
        dlg.show()
        dlg.raise_()

    def _show_first_run_notice(self) -> None:
        dlg = QDialog(self.shell)
        dlg.setWindowTitle(screens.APP_NAME)
        page = screens.FirstRunNotice(dlg)
        page.set_review_mode()
        page.set_permissions(self._permission_values())
        page.open_settings_requested.connect(self._open_screen_recording_settings)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        avail = shell_mod.fit_to_screen((page.WIDTH, 100000), screen=self.shell.screen())[1]
        dlg.setFixedWidth(page.WIDTH)
        def fit() -> None:                  # 같은 규칙 max(420, min(내용, 가용 − 80)) 을 표시 전과 표시 뒤에 적용한다(D-227)
            dlg.resize(page.WIDTH, max(shell_mod.DIALOG_MIN_HEIGHT, min(page.content_height(), avail)))

        fit()
        page.acknowledged.connect(dlg.close)
        self._notice_dialog = dlg
        dlg.show()
        QTimer.singleShot(0, dlg, fit)      # 표시된 뒤의 실제 폭으로 다시 맞춘다(문맥 객체: 창이 지워지면 호출하지 않는다)

    def _permission_values(self) -> dict:
        from ..platform import permissions as P
        try:
            return dict((self.deps.permission_status or P.query_status)())
        except Exception:
            return {}

    def _open_screen_recording_settings(self) -> None:
        url = QUrl("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")
        try:
            (self.deps.open_url or self._open_url)(url)
        except Exception:
            pass

    def on_submit(self, raw: str) -> None:
        if self.shell.machine.state is not appstate.State.IN_SESSION:
            return                  # D-071
        if not raw.strip() and self._attached:
            self._submit_images_only()          # D-125: 글 없이 이미지만 보내면 화면 메모 요청으로 처리한다(FR-7, 결정 0015 3항)
            return
        parsed = inputparse.parse(raw)
        if parsed is None:
            return
        if parsed.unknown:
            self._notice_text(inputparse.UNKNOWN_COMMAND_NOTICE)
            return
        if parsed.kind == "트리거":
            self.on_command("request.trigger")      # `/고찰` · `/reflect` = [고찰] 단추(결정 0157 3항): 진행 중이면 무시 · 캡처 처리 중이면 보류
        elif parsed.kind == "자유질의":
            self._submit("자유질의", text=parsed.text)
        elif parsed.kind == "답변":
            self._submit("답변", selected=self.view.transcript.selected_numbers())
        else:
            self._submit(parsed.kind)

    def _submit(self, kind: str, *, text: str = "", selected: Sequence[int] = ()) -> Optional[R.Card]:
        rt = self.runtime
        if rt is None:
            return None
        items = list(self._attached.values()) if kind == "자유질의" else []
        card = rt.submit(kind, text=text, selected=selected, images=[i[0] for i in items],
                         capture_paths=[(i[1], i[2]) for i in items])
        if items:
            self.view.ai.set_card_images(card.n, [(i[0].data, i[2]) for i in items])
            self._captures += len(items)
            self.view.input.clear_chips()
            self._attached.clear()
        return card

    def _submit_images_only(self) -> None:
        """칩의 이미지를 `화면메모` 요청으로 보낸다. 요청 하나가 이미지 전부를 싣고, 처리가 끝날 때까지 트리거를 보류한다(AC-FR7-17)."""
        rt = self.runtime
        if rt is None:
            return
        items = list(self._attached.values())
        card = rt.submit("화면메모", images=[i[0] for i in items], capture_paths=[(i[1], i[2]) for i in items])
        rt.manager.track_capture(card.n)
        self.view.ai.set_card_images(card.n, [(i[0].data, i[2]) for i in items])
        self._captures += len(items)
        self.view.input.clear_chips()
        self._attached.clear()

    def delete_card(self, n: int) -> None:
        if n < 0 or self.runtime is None:
            self.view.ai.apply_card(R.Card(n, "오류", R.STATE_ERROR), "removed")
            return
        if self._diagram_pool is not None:
            self._diagram_pool.cancel(n)        # 그 카드의 PID 만 종료한다. 이미 만든 파일은 둔다(AC-FR9-17)
        self._diagram_results.pop(n, None)
        self.runtime.delete_card(n)

    # ------------------------------------------------------------------ 다이어그램(FR-9, K-15)
    def _diagram_gate(self, n: int) -> tuple:
        pool = self._diagram_pool
        if pool is None:
            return False, _t("ctl.diagram_gate_256")
        if self._end_flow is not None or self._ended:
            return False, _t("ctl.diagram_gate_257")
        if pool.is_busy(n):
            return True, ""
        return pool.can_start(n)

    def _diagram_input(self, n: int):
        rt = self.runtime
        card = next((c for c in (rt.manager.cards() if rt else []) if c.n == n), None)
        if card is None or card.state != R.STATE_DONE or not card.text:
            return None
        if not diagram.can_diagram(card.kind, card.judgment):
            return None
        meta = rt._meta.get(n)
        # 질문: 트리거 카드는 판단의 주제, 그 밖은 요청 입력(임의: 입력이 비면 종류 이름)
        question = card.judgment_subject or (meta.input if meta and meta.input else card.kind)
        ts = hms(card.t_wall) if card.t_wall else time.strftime("%H:%M:%S")
        kind = diagram.prompt_kind(card.kind, card.judgment)       # AC-FR9-23: 판단별 `[카드] 종류=`
        return diagram.DiagramInput(n, kind, ts, question, card.text, self._session_stt_language())

    def make_diagram(self, n: int) -> bool:
        pool = self._diagram_pool
        if pool is None or self.runtime is None or self._end_flow is not None or self._ended:
            return False
        inp = self._diagram_input(n)
        w = self.view.ai.card(n)
        if inp is None or w is None:
            return False
        job = pool.submit(inp, self._diagram_bridge.done.emit)
        if job is None:
            ok, why = pool.can_start(n)
            if not ok:
                self._notice_text(why)
            return False
        w.diagram_progress()
        self.view.ai.refresh_gates()
        self.refresh_status()
        return True

    def _on_diagram_done(self, res) -> None:
        if self._ended:
            return                      # 앱을 끝내는 중이면 화면을 갱신하지 않는다
        ai = self.view.ai
        w = ai.card(res.card_n)
        if res.status == diagram.CANCELLED:
            if w is not None:
                w.diagram_idle()
        elif res.status == diagram.DONE:
            self._diagram_results[res.card_n] = res
            if w is not None and not w.diagram_done(str(res.svg)):
                pass
        elif w is not None:
            if res.status == diagram.VIOLATION:
                self._diagram_results[res.card_n] = res
                reason = diagram.REASON_VIOLATION
            elif res.status == diagram.OUTSIDE:
                reason = diagram.REASON_OUTSIDE
            else:
                reason = diagram_fail_text(res.error_kind)
            w.diagram_failed(reason)
        ai.refresh_gates()
        self.refresh_status()

    def open_diagram(self, n: int) -> bool:
        """완료한 카드의 SVG 를 눌렀을 때 원본 HTML(없으면 SVG)을 연다(AC-FR9-8)."""
        res = self._diagram_results.get(n)
        if res is None or res.status != diagram.DONE:
            return False
        target = res.html or res.svg
        if target is None:
            return False
        return bool((self.deps.open_url or self._open_url)(QUrl.fromLocalFile(str(target))))

    # ------------------------------------------------------------------ 첨부
    def _on_files_dropped(self, paths: list) -> None:
        self._attach_paths(paths, SOURCE_DROP)

    def _on_files_pasted(self, paths: list) -> None:       # D-133: Finder 에서 복사한 파일의 ⌘V 는 붙여넣기이다
        self._attach_paths(paths, SOURCE_PASTE)

    def _attach_paths(self, paths: list, source: str) -> None:
        files = []
        for p in paths:
            try:
                with open(p, "rb") as fh:
                    files.append((os.path.basename(p), fh.read()))
            except OSError:
                self._notice_text(_t("ctl.attach_paths_258") % os.path.basename(p))
        self.attach(files, source)

    def attach(self, files: Sequence, source: str) -> int:
        """`(이름, 바이트)` 목록을 판정 · 축소해 칩으로 붙인다. 반환: 붙인 장수."""
        from ..platform.capture import attach as A, shrink, store
        rt = self.runtime
        if rt is None:
            self._notice_text(_t("ctl.attach_259"))
            return 0
        ok, bad = A.judge_attachments(list(files), already=len(self._attached))
        for r in bad:
            self._notice_text("%s: %s" % (r.name, r.message))
        n = 0
        for a in ok:
            try:
                pr = shrink.prepare(a.data, self._get_scaler(), max_bytes=self.limits.image_bytes_cap)
            except imageinfo.ImageTooLarge:
                self._notice_text(_t("ctl.attach_260") % a.name)
                continue
            except shrink.ImageError:
                self._notice_text(_t("ctl.attach_261") % a.name)
                continue
            try:
                stem = os.path.splitext(a.name)[0] or "image"
                saved = store.write_bytes(pr.data, pr.fmt, str(rt.folder / "captures"), stem)
            except OSError:
                self._notice_text(_t("ctl.attach_262") % a.name)
                continue
            self._chip_seq += 1
            key = self._chip_seq
            media = "image/jpeg" if pr.fmt == "jpg" else "image/%s" % pr.fmt
            img = R.AttachedImage(source=source, t_wall=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                                  media_type=media, data=pr.data, name=a.name)
            self._attached[key] = (img, "captures/%s" % os.path.basename(saved), source)
            self.view.input.add_chip(key, a.name, pr.data)
            n += 1
        return n

    def _on_chip_removed(self, key) -> None:
        self._attached.pop(key, None)       # 칩을 뺀 이미지는 요청에 싣지 않는다(파일은 세션 폴더에 남는다)

    # ------------------------------------------------------------------ 표시
    def _notice_text(self, text: str) -> None:
        self.shell.statusBar().showMessage(text, NOTICE_MS)
        self.eventlog.emit("notice_shown", chars=len(text))

    def _show_notice(self, kind: str, info) -> None:
        text = NOTICE_TEXT.get(kind)
        if text:
            self._notice_text(text)

    def _post_error(self, kind: str, detail: str = "", permission: str = "", source: str = "", guided: bool = False) -> None:
        """카드가 없는 오류(시작 실패 · 수집 중단 · 전사 실패)를 AI 창의 오류 카드로 표시한다. 어느 스레드에서도 부른다."""
        if self._starting is not None:           # 세션이 성립하기 전의 오류는 카드가 아니라 시작 화면에 표시한다
            self._start_bridge.failed.emit(kind, detail)
            return
        self._local_card -= 1
        if kind == "permission":                 # 권한 오류 카드를 표시할 때마다 한 건(FS AC-FR3-22). 본문 · 경로 · 이름은 남기지 않는다
            self.eventlog.emit("permission_card", permission=permission or "screen_recording", source=source or "play",
                               guided=bool(guided))
        err = (kind, detail, "guided") if guided else (kind, detail)
        card = R.Card(self._local_card, "오류", R.STATE_ERROR, text="", error=err,
                      t_wall=datetime.now().astimezone().isoformat(timespec="milliseconds"))
        self.view.bridge.post_card(card, "new_app")      # 앱이 만든 카드는 따라가기 규칙을 따른다(D-168)

    def refresh_status(self) -> None:
        state = self.shell.machine.state
        rt = self.runtime
        p = self._params or {}
        sel = settings.resolve_selection(self.data)
        queue = 0
        activity = None
        if rt is not None:
            try:
                cards = rt.manager.cards()
                queue = sum(1 for c in cards if c.state == R.STATE_WAITING)
                if any(c.state == R.STATE_ACTIVE for c in cards):
                    activity = _t("ctl.activity_2")
            except Exception:
                pass
        if activity is None and self._diagram_pool is not None and self._diagram_pool.active_count():
            activity = _t("ctl.activity")
        if self._end_flow is not None and not self._cleanup_finished:
            activity = _t("ctl.activity_3")
        s = appstate.StatusInputs(
            provider=p.get("provider") or sel.provider, family=str(p.get("model") or sel.family),
            effort=p.get("effort") if p else sel.effort, source=source_display(p.get("source")) if p else None,
            capture_state=self._capture_state if rt is not None else None, materials=len(self.context.materials()),
            captures=self._captures, stt_errors=self._stt_errors, queue_waiting=queue,
            activity=activity, stt_prep=self._stt_prep if rt is not None else None)
        self.shell.status.show_inputs(s)
        try:
            self.view.set_capture_state(self._capture_state if rt is not None else None, state is appstate.State.ENDING)
        except RuntimeError:
            pass
        self._refresh_level()
        elapsed = int(time.monotonic() - self._started_mono) if self._started_mono is not None else None
        self.menu.set_status(state, elapsed, self._capture_state if rt is not None else None)

    def _on_machine_state(self, _old, new) -> None:
        """상태 전이 때 메뉴 · 입력창을 곧바로 맞춘다(D-072). 종료 처리 중에는 메인 창의 요청 입력을 끈다(D-071)."""
        self._sync_frame(new)
        try:
            self.view.input.setEnabled(new is not appstate.State.ENDING)
            self.refresh_status()
            if new is appstate.State.BEFORE_SESSION:
                self.refresh_start_check()
            self._sync_language_settings()
        except RuntimeError:
            pass

    def _refresh_level(self) -> None:
        """입력 레벨 막대만 갱신한다(짧은 주기 · 수집 상태가 바뀔 때). 수집이 중단이면 곧바로 0칸이 된다(AC-FR3-10)."""
        if self._ended:
            return
        rt, tap = self.runtime, self._tap
        try:
            self.shell.status.set_level(tap.level_dbfs() if (tap is not None and rt is not None) else None,
                                        self._capture_state if rt is not None else None)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------ 종료
    def end_session(self) -> None:
        """종료 흐름(FR-13, K-16): 수집을 멈추고 `end` 를 기록한 뒤 정리 문서를 만들고 앱을 끝낸다.

        정리 문서는 상주 프로세스에 보내고(이력 경로), 상주 프로세스가 없거나 바쁘면 일회성 프로세스에 보낸다(이력 없는 경로).
        실패해도 `session.jsonl` 은 남는다. 사용자가 [취소] 하면 문서 없이 끝낸다.
        """
        if self._ended or self._end_flow is not None:
            return
        self._dismiss_stop_dialog()           # 종료 요청이 오면 확인 창을 닫고 종료 흐름에 들어간다(FR-11 ⑥)
        self._cancel_diagrams()
        m = self.shell.machine
        if m.state is appstate.State.IN_SESSION:
            m.begin_ending()
        self._sync_clock()                    # 종료 처리 중에는 시계가 멈춘다([끝내기] · ⌘Q · Dock · 로그아웃 모두 이 경로)
        self._apply_globals()                 # 종료 흐름에 들어가면 전역 키를 해제한다
        if self._pause_finish_pending:        # 미룬 일시 정지의 끝을 쓴다(결정 0178)
            self._pause_finish_pending = False
            self._finish_pause(True)
        self._stop_audio()
        if self._capture_state == COLLECT_PAUSED:
            try:
                self.view.transcript.close_pause(self._pause_start_ts or "", time.strftime("%H:%M:%S"),
                                                 int(time.monotonic() - self._pause_mono) if self._pause_mono else 0)
            except RuntimeError:
                pass
        rt = self.runtime
        if rt is None:
            self._finish_quit()
            return
        rt.mark_end()
        if not self._begin_cleanup(rt):
            self._finish_quit()

    def quit_during_ending(self) -> None:
        """종료 창이 떠 있는 동안의 종료 요청(⌘Q · Dock · 로그아웃 · 재시동, 결정 0169 1항): 완료 · 실패 화면은 [닫기] 와,
        정리 문서를 만드는 중은 [취소] 와 같다. 종료 창이 없으면(종료 흐름이 이미 끝나 가는 중) 아무것도 하지 않는다."""
        if self._ended or self._end_dialog is None:
            return
        if self._end_flow is not None and not self._cleanup_finished:
            self._end_flow.cancel()          # 결과(CANCELLED)가 `_on_cleanup_done` 에서 종료로 이어진다
        else:
            self._finish_quit()

    def _arm_shutdown_deadline(self) -> None:
        """종료 동작(보조 프로세스 정리)이 시작되었다. `SHUTDOWN_LIMIT_S` 뒤에도 남은 기록된 PID 를 SIGKILL 한다(한 번만 건다)."""
        if getattr(self, "_deadline_timer", None) is not None:
            return
        t = threading.Timer(SHUTDOWN_LIMIT_S, self._deadline_kill)
        t.daemon = True
        self._deadline_timer = t
        t.start()

    def _deadline_kill(self) -> None:
        try:
            pids = self.registry.kill_all()
        except Exception:  # noqa: BLE001
            return
        if pids:
            self.eventlog.emit("shutdown_forced", pids=pids, limit_s=SHUTDOWN_LIMIT_S)

    def terminate_by_signal(self, reason: str = "sigterm") -> None:
        """앱이 SIGTERM 을 받았다(결정 0169 2항): 정리 문서 없이 보조 프로세스를 PID 로 끝내고(B-06) `end` 와 종료 사건을 기록하고 끝낸다."""
        if self._ended or self._quit_after_rebuild:
            return
        self.eventlog.emit("app_quit", reason=reason)
        self._arm_shutdown_deadline()
        if self._rebuild_mode and self._end_flow is not None and not self._cleanup_finished:
            self._wait_cancel_then_quit(self._end_flow)      # D-229: 응하지 않는 일회성 프로세스가 남지 않게 취소 결과를 기다린다
            return
        self._dismiss_stop_dialog()
        flow = self._end_flow
        if flow is not None and not self._cleanup_finished:
            try:
                flow.cancel()                # 정리 문서의 일회성 프로세스를 끝낸다
            except Exception:
                pass
        self._cancel_diagrams()
        self._stop_audio()
        self._finish_quit()                  # `end` 기록 · 세션 프로세스 종료 · 앱 종료

    def _convert_to_jpeg(self, src: str, dest: str) -> None:
        """정리 문서의 이미지 링크에 쓰는 JPEG 사본 변환(단계 18). 변환기는 `platform/capture/jpeg.save_jpeg` 이다. 사본은 화소 수를 줄이지 않는다(`limit` 을 크게 준다)."""
        from ..platform.capture import jpeg
        jpeg.save_jpeg(src, dest, jpeg.CAPTURE_JPEG_QUALITY, limit=1 << 30)

    def _new_end_flow(self, folder, doc_kind: str) -> EndFlow:
        """정리 문서를 만드는 모든 경로(세션 종료 · 다시 만들기 · [정리 문서 다시 만들기] 재시도)가 같은 변환을 쓰게 한다(결정 0194)."""
        return EndFlow(folder=folder, doc_kind=doc_kind, template=endflow.template_for(self.data, doc_kind),
                       eventlog=self.eventlog, to_jpeg=lambda s, d: self._convert_to_jpeg(s, d))

    def _begin_cleanup(self, rt) -> bool:
        """정리 문서를 만들기 시작한다. 만들 것이 없거나 시작하지 못하면 False(바로 끝낸다)."""
        view = endflow.view_of(rt.folder, self.eventlog.emit)
        if view is None or not view.segments:
            return False                    # 전사 조각이 없으면 정리할 것이 없다(임의)
        doc_kind = (view.header.kind if view.header else None) or self._params.get("kind") or "수업"
        flow = self._new_end_flow(rt.folder, doc_kind)
        self._end_flow = flow
        self._cleanup_finished = False
        self._end_dialog = EndDialog(self.shell)
        self._end_dialog.cancel_requested.connect(flow.cancel)
        self._end_dialog.open_folder_requested.connect(lambda: self._open_folder(rt.folder))
        self._end_dialog.close_requested.connect(self._finish_quit)
        self._end_dialog.retry_requested.connect(self._retry_cleanup)
        self._end_dialog.set_progress_provider(flow.progress.snapshot)
        self._end_dialog.visibility_changed.connect(self.menu.set_dialog_block)
        self._end_dialog.visibility_changed.connect(lambda _v: self._sync_dialog_layer())
        self._cleanup_ctx = (rt.folder, view, doc_kind)
        self._fill_end_info(view, rt.folder)
        self._end_dialog.open()
        self.refresh_status()
        on_done = self._end_bridge.done.emit
        started = False
        model_alive = getattr(rt.model, "pid", 1) is not None
        if model_alive and flow.can_use_resident(rt):
            started = flow.run_resident(rt, view, self._params.get("effort"), on_done)
        if not started:
            started = flow.run_history_less(view, self._make_oneshot(rt.folder, "cleanup_doc"), on_done)
        # 시작하지 못해도 종료 창은 열려 있다. 일회성 프로세스의 시작 실패는 `on_done` 으로 FAILED 결과가 오므로
        # (`OneShot._finish`) 앱을 끝내지 않고 그 안내(`enddialog.FAILED_TEXT`)를 기다린다(D-047).
        return True

    def _make_oneshot(self, cwd, purpose: str, **over) -> OneShot:
        p = self._params or {}
        sel = settings.resolve_selection(self.data)
        provider = p.get("provider") or sel.provider
        auth = llm.Auth.API if AUTH_BY_PROVIDER.get(provider) == "api" else llm.Auth.SUBSCRIPTION
        api_key = getattr(self, "_session_key", None) if auth is llm.Auth.API else None      # 세션 시작 때의 키(AC-FR1-26 ⑤): 호출마다 키체인을 다시 읽지 않는다
        if api_key:
            self.eventlog.register_secret(api_key)
        prompt = getattr(self, "_session_prompt", None)                                       # 세션 시작 때의 프롬프트(AC-FR1-26 ⑥)
        if prompt is None:
            _src, prompt = settings.resolve_session_prompt(self.data, p.get("session_prompt"), resources.default_session_prompt())
        kw = dict(claude_path=(self._session_claude[0] if getattr(self, "_session_claude", None) else self.claude_path),
                  model=str(p.get("model") or sel.family), auth=auth,
                  parent_env=self.environ, procs=self.procs, cwd=str(cwd),
                  run_dir=str(Path(self.config_dir) / "run"), effort="high", api_key=api_key,
                  eventlog=self.eventlog, system_prompt=self.context.system_prompt(resources.app_rules(), prompt),
                  purpose=purpose, model_factory=self.deps.model_factory)
        kw.update(over)             # 다이어그램: 시스템 프롬프트 없음 · effort · 도구 · 플러그인 · 권한 · 시간 제한
        return OneShot(**kw)

    def _on_done_signal(self, r) -> None:
        self._cleanup_finished = True        # D-132
        self.refresh_status()
        if self._rebuild_mode:
            if self._quit_after_rebuild:            # D-230: 종료 요청 뒤에는 결과(CANCELLED · DONE · FAILED)와 관계없이 끝낸다. 저장된 문서는 남는다
                self._close_rebuild_dialog()
                self.shutdown()
                return
            d = self._end_dialog
            if d is None:
                return
            if r.status == endflow.DONE:
                d.show_done(r.path.name if r.path else "")
            elif r.status == endflow.CANCELLED:
                self._close_rebuild_dialog()
            else:
                d.show_failed(r.kind or "")
            return
        self._on_cleanup_done(r)

    def _on_cleanup_done(self, r) -> None:
        d = self._end_dialog
        if d is None:
            return
        if r.status == endflow.CANCELLED:
            self._finish_quit()
        elif r.status == endflow.DONE:
            d.show_done(r.path.name if r.path else "")
        else:
            d.show_failed(r.kind or "")

    def _fill_end_info(self, view, folder) -> None:
        """종료 창의 파일 줄 설명에 쓰는 값: 조각 · 캡처 · 질의응답 수, 저장 위치, 정리 문서 이름."""
        d = self._end_dialog
        if d is None:
            return
        qa = len([n for n in view.responses if n not in view.deleted_ns])
        kind = (view.header.kind if view.header else None) or "수업"
        d.set_info(segments=len(view.segments), captures=len(view.captures), qa=qa, folder=str(folder),
                   doc_name="lecture.md" if kind == "수업" else "meeting.md",
                   title=labels.title_label((view.header.title if view.header else "") or ""))

    def _retry_cleanup(self) -> None:
        """종료 창의 [정리 문서 다시 만들기]: 같은 세션 폴더로 정리 문서를 다시 요청한다(이력 없는 경로, 임의)."""
        ctx = getattr(self, "_cleanup_ctx", None)
        d = self._end_dialog
        if ctx is None or d is None:
            return
        folder, view, doc_kind = ctx
        flow = self._new_end_flow(folder, doc_kind)
        self._end_flow = flow
        self._cleanup_finished = False
        self.refresh_status()
        try:
            d.cancel_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        d.cancel_requested.connect(flow.cancel)
        d.set_progress_provider(flow.progress.snapshot)
        ok = flow.run_history_less(view, self._make_oneshot(folder, "cleanup_doc"), self._end_bridge.done.emit)
        if not ok:
            d.show_failed("process_exit")

    def _finish_quit(self) -> None:
        if self._ended:
            return
        self._arm_shutdown_deadline()
        rt = self.runtime
        if rt is not None:
            rt.finish()
            self.runtime = None
        m = self.shell.machine
        if m.state is appstate.State.ENDING:
            m.finish()
        d, self._end_dialog = self._end_dialog, None
        if d is not None:
            d.dismiss()
        self.shutdown()

    def _open_folder(self, folder) -> None:
        (self.deps.open_url or self._open_url)(QUrl.fromLocalFile(str(folder)))

    # ---- 정리 문서 다시 만들기(세션 메뉴, 8-3-1절) ----
    def rebuild_summary(self, folder=None, kind: Optional[str] = None, title: Optional[str] = None) -> bool:
        """세션 폴더의 `session.jsonl` 로 정리 문서를 다시 만든다. 세션을 시작하기 전에만 쓴다."""
        if self.runtime is not None or self._end_flow is not None:
            return False
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self.shell, _t("ctl.folder"), "")
            if not folder:
                return False
        view = endflow.view_of(folder, self.eventlog.emit)
        if view is None:
            self._notice_text(_t("ctl.rebuild_summary_266"))
            return False
        if not view.segments:
            self._notice_text(_t("ctl.rebuild_summary_267"))
            return False
        if view.header is None:                  # 머리가 없으면 종류만 받는다(임의: 종류는 수업을 기본으로 한다)
            view.header = cleanup_doc.Header(kind=kind or "수업", title=title or cleanup_doc.UNNAMED)
        doc_kind = view.header.kind
        flow = self._new_end_flow(folder, doc_kind)
        self._end_flow = flow
        self._cleanup_finished = False
        self._end_dialog = EndDialog(self.shell)
        self._end_dialog.cancel_requested.connect(flow.cancel)
        self._end_dialog.open_folder_requested.connect(lambda: self._open_folder(folder))
        self._end_dialog.close_requested.connect(self._close_rebuild_dialog)
        self._end_dialog.retry_requested.connect(self._retry_cleanup)
        self._end_dialog.set_progress_provider(flow.progress.snapshot)
        self._end_dialog.visibility_changed.connect(self.menu.set_dialog_block)
        self._end_dialog.visibility_changed.connect(lambda _v: self._sync_dialog_layer())
        self._cleanup_ctx = (folder, view, doc_kind)
        self._fill_end_info(view, folder)
        self._end_dialog.open()
        self._rebuild_mode = True
        ok = flow.run_history_less(view, self._make_oneshot(folder, "cleanup_doc"), self._end_bridge.done.emit)
        return ok

    def _close_rebuild_dialog(self) -> None:
        d, self._end_dialog = self._end_dialog, None
        self._end_flow = None
        self._rebuild_mode = False
        self._cleanup_ctx = None
        if d is not None:
            d.dismiss()

    def _stop_audio(self) -> None:
        p, self.pipeline = self.pipeline, None
        self._stt_retry_timer.stop()
        rt = self.runtime
        if rt is not None:
            rt.stt_cut = None
        if p is not None:
            p.stop()
            p.join(10.0)
            self._release_stt_pid()
        if rt is not None:
            rt.close_open()

    def _cancel_diagrams(self) -> None:
        """세션 종료: 진행 중인 다이어그램의 프로세스를 PID 로 끝내고 덜 만든 파일을 지운다(AC-FR11-4)."""
        pool = self._diagram_pool
        if pool is not None:
            try:
                pool.cancel_all()
            except Exception:
                self.eventlog.emit("error", module="diagram", kind="io", detail="취소 중 오류")

    def quit_now(self) -> None:
        """세션을 시작하기 전의 종료 요청(⌘Q · 앱 메뉴 · 운영체제 · 첫 실행 고지의 [종료], D-229). 정리 문서 다시 만들기가 진행 중이면
        생성을 취소하고 그 결과(일회성 프로세스의 종료까지)를 기다린 뒤 끝낸다. 완료 · 실패 화면이면 창을 닫고 바로 끝낸다."""
        if self._ended:
            return
        if self._rebuild_mode:
            flow = self._end_flow
            if flow is not None and not self._cleanup_finished:
                self._wait_cancel_then_quit(flow)
                return
            self._close_rebuild_dialog()
        self.shutdown()

    def _wait_cancel_then_quit(self, flow) -> None:
        self._quit_after_rebuild = True
        self._arm_shutdown_deadline()
        try:
            flow.cancel()                    # 결과(CANCELLED)가 `_on_done_signal` 에서 종료로 이어진다
        except Exception:
            self._close_rebuild_dialog()
            self.shutdown()

    def shutdown(self) -> None:
        if self._ended:
            return
        self._ended = True
        d, self._end_dialog = self._end_dialog, None
        if d is not None:
            d.dismiss()                      # 열린 창이 closeEvent 를 거부하면 app.quit() 이 취소된다(D-229)
        self._cancel_diagrams()
        self._stop_audio()
        self.frame.close()
        self.frame.deleteLater()
        rt, self.runtime = self.runtime, None
        if rt is not None:
            rt.close()
        t, self._deadline_timer = getattr(self, "_deadline_timer", None), None
        if t is not None:
            t.cancel()
        self._status_timer.stop()
        self._level_timer.stop()
        if self._control_timer is not None:
            self._control_timer.stop()
        self.eventlog.close()
        self.app.quit()

    # ------------------------------------------------------------------ 시험 제어 파일
    def _poll_control(self) -> None:
        path = self.dev.get("control")
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        pos = self._control_pos or 0
        if size < pos:
            pos = 0
        if size == pos:
            return
        try:
            with open(path, "rb") as fh:
                fh.seek(pos)
                chunk = fh.read(size - pos)
        except OSError:
            return
        nl = chunk.rfind(b"\n")
        if nl < 0:
            return               # 줄이 아직 끝나지 않았다
        self._control_pos = pos + nl + 1
        for raw in chunk[:nl].split(b"\n"):
            self._control_line += 1
            self._run_control(self._control_line, raw.decode("utf-8", "replace").strip())

    def _run_control(self, line_no: int, text: str) -> None:
        if not text:
            return
        cmd = None
        value = None
        try:
            obj = json.loads(text)
            cmd, value = obj.get("cmd"), obj.get("value")
        except (ValueError, AttributeError):
            pass
        handled = True
        if cmd == "appearance" and value in ("light", "dark"):
            self.appearance.set_system_override(value)
        elif cmd == "audio_error" and self._tap is not None:
            self._tap.state(COLLECT_STOPPED, "시험 주입")
        elif cmd == "audio_start_failed" and self._tap is not None:       # 수집 오류 주입의 시작 실패 모드(결정 0069, AC-FR3-12)
            if self._capture_state in (COLLECT_BEFORE, COLLECT_PAUSED):    # 수집 전 · 일시 정지 중: 다음 [재생] 이 실패한다(결정 0150)
                self._start_fail_armed = True
            else:
                self._tap.state(COLLECT_STOPPED, "%s: 시험 주입" % appstate.START_FAILED_PREFIX)
        elif cmd == "elapsed_shift":                                       # 정리 문서 경과 시간의 기준 시각을 앞당긴다(결정 0154)
            try:
                sec = float(json.loads(text).get("seconds", value))
            except (TypeError, ValueError, AttributeError):
                sec = None
            if sec is not None and self._end_flow is not None:
                self._end_flow.progress.shift(sec)
                if self._end_dialog is not None:
                    self._end_dialog.refresh_progress()
        elif cmd == "audio_recover" and self._tap is not None:
            self._tap.state(COLLECT_RUNNING, "시험 주입")
        elif cmd in ("frame_show", "frame_hide"):                       # C2: 액자 보이기 · 숨기기
            self._frame_wanted = cmd == "frame_show"
            self._sync_frame(self.shell.machine.state, "dev_control")
        elif cmd == "frame_set" and isinstance(value, dict):             # C2: 바깥 사각형 지정
            r = framegeom.Rect(*[int(value.get(k, 0)) for k in ("x", "y", "w", "h")]) if all(
                isinstance(value.get(k), int) for k in ("x", "y", "w", "h")) else None
            if r is None:
                handled = False
            else:
                self.set_frame_rect(r)
        elif cmd == "frame_drop" and isinstance(value, dict):            # C2: 끌기를 놓은 것과 같은 처리
            keys = ("x", "y", "w", "h", "pointer_x", "pointer_y")
            if all(isinstance(value.get(k), int) and not isinstance(value.get(k), bool) for k in keys):
                self.drop_frame(framegeom.Rect(value["x"], value["y"], value["w"], value["h"]),
                                (value["pointer_x"], value["pointer_y"]))
            else:
                handled = False
        elif cmd == "frame_capture":                                     # C2: 캡처 실행
            self.capture_frame()
        elif cmd == "frame_query":                                       # C2: 사각형의 화면 좌표 조회(이벤트 로그에 남긴다)
            self.eventlog.emit("frame_query", **self.frame_rects())
        else:
            handled = False
        fields = dict(cmd=str(cmd) if isinstance(cmd, str) else None, line=line_no, t_mono=time.monotonic())
        if not handled:
            fields["ignored"] = True
        self.eventlog.emit("dev_command", **fields)


def run(argv: Optional[Sequence[str]] = None) -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(screens.APP_NAME)
    menus.install_mac_menu_translator(app)        # D-079: 메뉴 막대를 만들기 전에 설치한다
    menus.install_text_menu_translator(app)       # D-160: 입력 칸의 오른쪽 클릭 메뉴 항목 이름이 앱 언어를 따른다
    try:
        from PySide6.QtGui import QIcon
        from ..core import resources
        app.setWindowIcon(QIcon(str(resources.app_icon_source_path())))
    except Exception:
        pass
    ctl = AppController(app, list(sys.argv[1:] if argv is None else argv))
    ctl.show()
    _install_sigterm(ctl)
    return app.exec()


def _install_sigterm(ctl) -> None:
    """SIGTERM 을 종료 요청으로 받는다(결정 0169 2항). 핸들러는 플래그만 세우고, 이벤트 루프의 타이머가 처리한다."""
    import signal
    flag = []

    def handler(_sig, _frm):
        flag.append(1)

    try:
        signal.signal(signal.SIGTERM, handler)
    except (ValueError, OSError):
        return
    timer = QTimer(ctl)
    timer.setInterval(100)

    def poll():
        if flag:
            flag.clear()
            ctl.terminate_by_signal("sigterm")
    timer.timeout.connect(poll)
    timer.start()
    ctl._sigterm_timer = timer
