<p align="center"><img src="docs/assets/readme/about.png" width="320" alt="Prof. Kang's RAB 앱 정보 이미지"></p>

<h1 align="center">Prof. Kang's RAB</h1>

<p align="center">한국어 | <a href="README.en.md">English</a></p>

<p align="center"><strong>Retrieval-Augmented Brain</strong></p>

<p align="center">회의와 수업 중의 실시간 전사 · 사전 지식 · 화면을 모아 사용자의 두뇌와 지식을 증강하는 앱.</p>

이 앱은 AI 전문가 강장묵 교수가 2026년 9월 19일 강의에서 소개한, 실시간 녹음과 노트북으로 회의 중 두뇌의 기능을 증강하는 기법에서 영감을 받아 만들었습니다. 그 기법을 앱으로 옮겨, 회의와 수업 중에 실시간 전사 · 사전 지식 · 화면을 찾아 모아 사용자의 두뇌와 지식을 증강합니다.

<p align="center"><img src="docs/assets/readme/screens/main-window.png" width="800" alt="응답이 쓰이는 중인 메인 창: 왼쪽에 전사, 오른쪽에 답변 카드"></p>

<p align="center">모든 화면의 시안: <a href="https://claude.ai/artifact/SeosX2oTCiqQ6ctYebBzAW">https://claude.ai/artifact/SeosX2oTCiqQ6ctYebBzAW</a></p>

## 이 프로젝트가 제공하는 것

이 프로젝트의 핵심 가치는 외부세계에서 두뇌로 정보가 흐르는 채널을 확장하고, 컨텍스트를 뇌 외부로 확장하는 방법과 그 프로세스의 형태를 제시하는 것에 있습니다.

이 앱은 macOS 와 Claude 환경에서 동작하도록 만들어져 있습니다. 다른 운영체제나 모델 제공자를 쓰고 계신다면, 자신의 환경과 쓰임새에 맞게 포팅하여 사용해 보시기를 권합니다. 포팅에 필요한 구분은 [AGENT_INSTALL.md](AGENT_INSTALL.md#porting-to-another-environment)(영문)에 Windows 를 예로 적었습니다.

## 빠른 시작

AI 코딩 에이전트에게 설치를 맡길 수 있습니다. [Claude Code](https://code.claude.com/docs) 를 쓰는 맥에서 다음과 같이 말씀하시면 됩니다.

> 이 맥에 Prof. Kang's RAB 를 설치해 주세요. `https://github.com/NSU-AISEC/nsu-kangs-rab` 의 AGENT_INSTALL.md 를 따르고, 제 계정 · 키 · 권한 허용이 필요한 단계에서는 멈추고 저에게 물어봐 주세요.

에이전트는 [AGENT_INSTALL.md](AGENT_INSTALL.md)(영문)의 절차를 따라 도구를 확인하고 앱을 만듭니다. 사용자만 할 수 있는 단계에서는 멈춥니다: Claude Code 로그인(`/login`), API 키 방식이면 앱에 키를 입력하는 일, 언어를 처음 쓸 때 macOS 가 음성 인식 언어 모델을 준비하는 동안의 기다림, macOS 권한 허용(화면 기록 · 시스템 사운드). 에이전트는 Claude Code 의 자격 증명과 사용자의 API 키를 다루지 않습니다. 설치 · 사용법 · 문제 해결 · 포팅에 관한 질문도 에이전트가 이 문서를 읽고 답합니다. 직접 설치하려면 이 문서의 절차를 따르시면 됩니다. 이 앱은 모델 호출에 Claude Code CLI(`claude -p`)를 쓰므로 구독 방식에는 Claude Code 와 그 로그인이 필요하고, API 키 방식에는 앱에 입력한 키가 필요합니다.

## 출처와 라이선스

이 프로젝트는 MIT 라이선스로 공개합니다. 라이선스 전문은 저장소 루트의 `LICENSE` 에 있습니다.

다른 프로젝트의 자료는 `third_party/` 에 두며, 각각 자기 라이선스 파일을 가집니다.

- `third_party/diagram-design/`: 다이어그램 기능이 쓰는 diagram-design(MIT 라이선스, <https://github.com/cathrynlavery/diagram-design>)의 특정 판입니다. 그 폴더에 `LICENSE` 와 `THIRD_PARTY_LICENSES.md` 가 있습니다.
- `third_party/awesome-design-md/`: awesome-design-md(MIT 라이선스, <https://github.com/voltagent/awesome-design-md>)의 설계 문서 한 편의 사본이며 그 `LICENSE` 를 함께 둡니다.

화면은 PySide6(Qt for Python)를 라이브러리로 쓰며, PySide6 는 LGPL v3 라이선스입니다(<https://doc.qt.io/qtforpython-6/licenses.html>). 앱은 `uv sync` 로 이것을 의존성으로 설치하며 수정하지 않습니다.
