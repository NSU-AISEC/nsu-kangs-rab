---
kind: readme
---

# src/mac

macOS 용 소스를 둔다. 패키지는 `nsu_kangs_rab/` 이다.

- 빌드 대상은 `pyproject.toml` 의 `module-root` 가 정한다.
- 플랫폼에 의존하는 코드(음성 수집 · 음성 인식 · 화면 캡처)는 `nsu_kangs_rab/platform/` 에, 플랫폼에 의존하지 않는 코드는 `nsu_kangs_rab/core/` 와 `nsu_kangs_rab/app/` 에 있다.
- 설계 문서와 결정 기록은 이 저장소에 담지 않는다.
