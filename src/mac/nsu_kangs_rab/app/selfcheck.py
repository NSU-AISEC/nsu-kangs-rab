"""묶은 앱의 자체 점검(D-080 재발 방지). `ProfKangRAB --self-check` 로 실행하며 Qt 창을 만들지 않는다.

세션을 시작한 뒤에야 지연 import 되는 모듈(시스템 사운드 소스 · 리샘플러 · 전사 파이프라인)과 `stt_speech` 보조 프로세스가 묶음에
들어갔는지, 앱 패키지의 모든 모듈을 가져올 수 있는지를 실제로 확인한다. 한 줄에 한 항목을 `OK <이름>` 또는
`FAIL <이름>: <예외>` 로 출력하고, 실패가 하나라도 있으면 종료 코드 1 이다. 개발 환경에서도 같은 점검이 된다.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import traceback
from typing import Callable, List, Optional, Tuple

# 세션 시작 뒤 지연 import 되는 외부 모듈(묶음에서 빠지기 쉬운 것). 이름이 바뀌면 이 목록을 고친다.
EXTERNAL_MODULES = ("numpy", "scipy.signal", "PySide6.QtWidgets", "PySide6.QtSvgWidgets")
# 앱 패키지 안에서 지연 import 되는 모듈(목록은 안전망이고, 아래의 전체 순회가 본체이다).
LAZY_APP_MODULES = (
    "platform.audio.system_sound", "platform.audio.mic_source", "platform.audio.resampler",
    "platform.stt.stt_speech", "platform.stt.pipeline",
)


def _app_modules() -> List[str]:
    import nsu_kangs_rab as pkg
    names = {pkg.__name__ + "." + m for m in LAZY_APP_MODULES}
    try:
        for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            names.add(info.name)
    except Exception:  # 순회를 지원하지 않는 묶음이면 목록만 쓴다
        pass
    return sorted(names)


def _construct() -> List[Tuple[str, Callable[[], object]]]:
    def resampler():
        import numpy as np
        from nsu_kangs_rab.platform.audio.resampler import Resampler
        out = Resampler(48000).process(np.zeros(4800, dtype=np.float32))
        return len(out)

    def system_sound():
        from nsu_kangs_rab.platform.audio.system_sound import SystemSoundSource
        return SystemSoundSource("/nonexistent/sck_audio")

    def stt_helper():
        # 결정 0162 · 2-8-6절: 묶은 앱은 `Contents/Frameworks/helper/stt_speech` 를 가져야 하고 `--list-locales` 가 로캘 목록을 반환해야 한다.
        # 묶음이 아닌 개발 환경에서는 `<설정 폴더>/helper/stt_speech` 가 있을 때만 같은 점검을 한다(없으면 건너뛴다).
        import subprocess
        from nsu_kangs_rab.core import resources, settings
        path = resources.bundled_stt_helper_path()
        frozen = path is not None
        if path is None:
            path = settings.default_config_dir() / "helper" / "stt_speech"
        if not path.is_file():
            if frozen:
                raise FileNotFoundError("묶음에 stt_speech 가 없다: %s" % path)
            return "건너뜀(개발 환경: %s 없음)" % path
        if not os.access(str(path), os.X_OK):
            raise PermissionError("stt_speech 에 실행 권한이 없다: %s" % path)
        from nsu_kangs_rab.platform.stt import stt_speech
        lst = stt_speech.list_locales([str(path)], 15.0, subprocess.Popen)
        if not lst:
            raise RuntimeError("stt_speech --list-locales 가 로캘 목록을 반환하지 않았다")
        return len(lst)

    def menubar_icons():
        # 결정 0085: 자원이 없으면 `_icon` 이 오류 없이 빈 아이콘을 반환해 메뉴 막대 아이콘이 소리 없이 사라진다
        from PySide6.QtGui import QImage
        from nsu_kangs_rab.core import resources
        for state in ("none", "session", "warn"):
            for px in (18, 36):
                path = resources.menubar_icon_path(state, px)
                if not path.is_file():
                    raise FileNotFoundError(str(path))
                img = QImage(str(path))
                if img.isNull() or (img.width(), img.height()) != (px, px):
                    raise RuntimeError("메뉴 막대 그림을 읽을 수 없거나 크기가 다르다: %s" % path)
        return 6

    return [("construct:resampler", resampler), ("resource:menubar_icons", menubar_icons), ("construct:system_sound_source", system_sound),
            ("stt_speech:helper", stt_helper)]


def run(out=None) -> int:
    out = out or sys.stdout
    failed = 0

    def report(name: str, fn: Callable[[], object]) -> None:
        nonlocal failed
        try:
            fn()
            print("OK %s" % name, file=out)
        except BaseException as e:  # noqa: BLE001 (점검은 어떤 실패도 목록으로 낸다)
            failed += 1
            print("FAIL %s: %s: %s" % (name, type(e).__name__, e), file=out)
            # 원인 사슬(__cause__ · __context__)과 traceback 을 함께 낸다(D-082)
            for ln in traceback.format_exc().rstrip().splitlines():
                print("  | " + ln, file=out)

    for m in EXTERNAL_MODULES:
        report("import:" + m, lambda m=m: importlib.import_module(m))
    for m in _app_modules():
        report("import:" + m, lambda m=m: importlib.import_module(m))
    for name, fn in _construct():
        report(name, fn)
    print("자체 점검: 실패 %d건" % failed, file=out)
    return 1 if failed else 0
