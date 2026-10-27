"""PDF 텍스트 추출 작업 프로세스 (A-06, K-05 후속 X3). 단독 실행 파일이며 이 패키지의 다른 모듈을 가져오지 않는다.

`python pdfworker.py <PDF 경로>` → 표준 출력에 JSON 한 줄:
  {"status": "ok", "text": "..."} | {"status": "encrypted"} | {"status": "no_text"} | {"status": "format", "detail": "<예외 이름>"}
  | {"status": "dependency", "detail": "pypdf" | "cryptography"}   (추출 부품 부재, 결정 0058 묶음의 D-033 제안)
앱(`core/context.py`)이 이 프로세스를 시작하고 시간 초과에 그 PID 로만 끝낸다. 쪽 하나의 추출 중에도 끊을 수 있다.
열기 암호가 없고 소유자 암호만 있는 PDF 는 빈 암호로 연다(AC-FR2-7, `pypdf` 의 `decrypt("")`).
"""
import json
import sys


def extract(path: str) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"status": "dependency", "detail": "pypdf"}
    try:
        from pypdf.errors import DependencyError
    except ImportError:   # 옛 pypdf: 이 예외가 없으면 아무것도 걸리지 않게 한다
        class DependencyError(Exception):
            pass
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except DependencyError:   # cryptography 가 없어 AES 를 풀지 못한다(D-033): 암호화가 아니라 부품 부재이다
                return {"status": "dependency", "detail": "cryptography"}
            except Exception:  # 알고리즘을 지원하지 않는 경우
                return {"status": "encrypted"}
            if not opened:     # 0: 열기 암호가 필요하다
                return {"status": "encrypted"}
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except DependencyError:
        return {"status": "dependency", "detail": "cryptography"}
    except Exception as e:  # pypdf 는 깨진 파일에서 다양한 예외를 낸다
        return {"status": "format", "detail": type(e).__name__}
    if not text.strip():
        return {"status": "no_text"}
    return {"status": "ok", "text": text}


def main(argv) -> int:
    if len(argv) != 2:
        sys.stdout.write(json.dumps({"status": "format", "detail": "usage"}) + "\n")
        return 2
    sys.stdout.write(json.dumps(extract(argv[1]), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
