"""화면 밝기 적용 (FR-15, A-24).

선택(`시스템 설정 따르기` · `밝은 화면` · `어두운 화면`)을 `QStyleHints` 로 앱 전체에 적용하고,
스타일 시트를 바꾼다. 모델 호출 · 하위 프로세스 · 세션 상태에 영향을 주지 않는다(AC-FR15-4).
`QStyleHints.setColorScheme` 이 없는 판에서는 `unsupported` 로 알리고 스타일 시트만 바꾼다.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from ..core import appstate
from . import theme


class AppearanceApplier(QObject):
    """`apply(choice)` 로 바꾸고 `scheme` 으로 현재 값을 읽는다. 시스템 설정 변화는 `colorSchemeChanged` 로 받는다.
    `on_applied(scheme)` 는 적용 뒤에 호출한다(예: 열린 창의 다시 그리기)."""

    def __init__(self, app: QApplication, choice: str = appstate.APPEARANCE_SYSTEM,
                 on_applied: Optional[Callable] = None, emit: Optional[Callable] = None,
                 system_override: Optional[str] = None):
        super().__init__()
        self._app = app
        self._hints = app.styleHints()
        self._choice = appstate.normalize_appearance(choice)
        self._on_applied, self._emit = on_applied, emit
        self._scheme = appstate.SCHEME_LIGHT
        # 시험 연결점(`--dev-appearance light|dark`, 계획 5절): 운영체제 신호 대신 이 값을 시스템 외관으로 쓴다.
        self._override = system_override if system_override in ("light", "dark") else None
        self.supported = hasattr(self._hints, "setColorScheme") and hasattr(self._hints, "colorSchemeChanged")
        if self.supported:
            self._hints.colorSchemeChanged.connect(self._on_system_changed)
        self.apply(self._choice)

    @property
    def choice(self) -> str:
        return self._choice

    @property
    def scheme(self) -> str:
        return self._scheme

    def set_system_override(self, value: Optional[str]) -> None:
        """시험 연결점의 실행 중 변경(제어 파일). `None` 이면 운영체제 신호로 돌아간다."""
        self._override = value if value in ("light", "dark") else None
        if self._choice == appstate.APPEARANCE_SYSTEM:
            self._refresh()

    def _system_scheme(self) -> Optional[str]:
        if self._override is not None:
            return self._override
        if not self.supported:
            return None
        cs = self._hints.colorScheme()
        return {Qt.ColorScheme.Dark: "dark", Qt.ColorScheme.Light: "light"}.get(cs)

    def apply(self, choice: str) -> str:
        self._choice = appstate.normalize_appearance(choice)
        if self.supported:
            if self._choice == appstate.APPEARANCE_SYSTEM:
                self._hints.unsetColorScheme()
            else:
                self._hints.setColorScheme(Qt.ColorScheme.Dark if self._choice == appstate.APPEARANCE_DARK
                                           else Qt.ColorScheme.Light)
        self._refresh()
        return self._scheme

    def _refresh(self) -> None:
        self._scheme = appstate.resolve_scheme(self._choice, self._system_scheme())
        self._app.setProperty("rab_scheme", self._scheme)       # 전사 행 그리기가 같은 토큰을 쓰도록 알린다(D-096)
        self._app.setStyleSheet(theme.stylesheet(self._scheme))
        if self._emit is not None:
            try:
                self._emit("appearance_applied", choice=self._choice, scheme=self._scheme, supported=self.supported)
            except Exception:
                pass
        if self._on_applied is not None:
            self._on_applied(self._scheme)

    def _on_system_changed(self, *_args) -> None:
        if self._choice == appstate.APPEARANCE_SYSTEM:
            self._refresh()
