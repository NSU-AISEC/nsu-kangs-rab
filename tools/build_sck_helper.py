"""시스템 사운드 수집 보조 프로그램(`sck_audio`)을 개발용으로 빌드한다 (결정 0065, 포장은 K-17).

사용: `uv run python tools/build_sck_helper.py [대상 경로]`
기본 대상은 앱 설정 폴더의 `helper/sck_audio` 이다. `swiftc` 가 필요하다(Xcode 명령줄 도구).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "mac"))

from nsu_kangs_rab.core import settings  # noqa: E402
from nsu_kangs_rab.platform.audio.system_sound import build_helper  # noqa: E402


def main(argv) -> int:
    dest = argv[1] if len(argv) > 1 else os.path.join(str(settings.default_config_dir()), "helper", "sck_audio")
    try:
        out = build_helper(dest)
    except (OSError, Exception) as e:  # swiftc 가 없거나 빌드가 실패한 경우
        print("오류: 보조 프로그램을 빌드하지 못했다: %s" % type(e).__name__, file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
