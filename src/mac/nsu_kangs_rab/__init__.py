PDF_WORKER_FLAG = "--pdf-worker"
SELF_CHECK_FLAG = "--self-check"       # 묶음에서 지연 import 되는 모듈의 점검(D-080)


def _guard_multiprocessing(argv) -> None:
    """D-085: 묶은 앱에서 multiprocessing 이 같은 실행 파일을 다시 시작할 때 앱 전체가 실행되지 않게 한다.

    ① `freeze_support()` 로 `--multiprocessing-fork` 자식을 처리한다. ② resource tracker 는 `sys.executable -B -S -I -c
    "from multiprocessing.resource_tracker import main;main(<fd>)"` 로 시작되어 freeze_support 가 처리하지 못한다.
    이 형태의 인자이면 tracker 만 실행하고 끝난다.(tqdm 의 잠금 대체는 tqdm 을 의존성에서 뺀 M-3 에서 지웠다.)"""
    import multiprocessing
    multiprocessing.freeze_support()
    if "-c" in argv:
        i = argv.index("-c")
        code = argv[i + 1] if i + 1 < len(argv) else ""
        prefix = "from multiprocessing.resource_tracker import main;main("
        if code.startswith(prefix) and code.endswith(")") and code[len(prefix):-1].isdigit():
            from multiprocessing import resource_tracker
            resource_tracker.main(int(code[len(prefix):-1]))
            raise SystemExit(0)


def main() -> None:
    """진입점(`uv run nsu-kangs-rab`). Qt 는 실행할 때 가져온다.

    묶은 앱(PyInstaller 등)에서는 `sys.executable` 이 앱 자신이므로 PDF 추출 프로세스를 `python pdfworker.py` 로
    시작할 수 없다. 첫 인자가 `--pdf-worker` 이면 Qt 를 가져오지 않고 추출 작업만 하고 끝난다(K-17).
    """
    import sys
    _guard_multiprocessing(sys.argv)
    if len(sys.argv) > 1 and sys.argv[1] == PDF_WORKER_FLAG:
        from .core import pdfworker
        raise SystemExit(pdfworker.main([sys.argv[0]] + sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == SELF_CHECK_FLAG:
        from .app import selfcheck
        raise SystemExit(selfcheck.run())
    from .core import i18n
    i18n.init_from_argv(sys.argv[1:])          # 앱 언어는 시작할 때 한 번 정한다(결정 0131). 문구를 쓰는 모듈을 가져오기 전에 한다
    from .app.controller import run
    raise SystemExit(run())
