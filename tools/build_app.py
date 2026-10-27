"""`.app` 묶음을 만든다 (K-17, 묶기 도구 비교의 결과 PyInstaller).

사용: `uv run --with pyinstaller==6.16.0 python tools/build_app.py <출력 폴더>`
1. 보조 프로그램 둘을 미리 빌드한다: 시스템 사운드(`platform.audio.system_sound.build_helper`, 결정 0065 3항)와 음성 인식
   (`platform.stt.stt_speech.build_helper`, 결정 0162, `Contents/Frameworks/helper/stt_speech`).
2. PyInstaller 로 `ProfKangRAB.app` 을 만들고 `<출력 폴더>/Prof. Kang's RAB.app` 으로 이름을 바꾼다(결정 0095, 식별자 `app.profkangrab`, 표시 이름 "Prof. Kang's RAB"). 보조 프로그램은 `Contents/Frameworks/helper/sck_audio` · `stt_speech`,
   diagram-design 사본은 `Contents/Resources/third_party/diagram-design`(`Frameworks/third_party` 에서 연결)에 놓인다.
3. `Info.plist` 의 `LSMinimumSystemVersion` 을 26.0 으로 두고(SpeechAnalyzer 의 요구, 결정 0162) 만든 뒤 값을 확인한다.
   Whisper 계열(mlx · torch · numba)은 의존성에서 뺐으므로 묶지 않는다. `scipy` 는 `platform/audio/resampler.py` 가 가져온다.
4. 만든 뒤 `ProfKangRAB --self-check` 로 지연 import 모듈의 점검을 실행하고 실패하면 빌드를 실패로 끝낸다(D-080).
묶음에는 임시(ad-hoc) 서명이 붙는다. 배포용 서명 · 공증은 개발자 계정이 필요하며 이 도구가 하지 않는다.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "mac"))

APP_FILE_NAME = "ProfKangRAB"                  # 실행 파일 이름(결정 0095 2항: 그대로 둔다)
APP_BUNDLE_DIR = "Prof. Kang's RAB.app"        # 묶음(폴더) 이름(결정 0095, D-130: Dock · Finder · 권한 창이 이 이름을 쓴다)
BUNDLE_ID = "app.profkangrab"                  # 결정 0019 3항: 식별자 끝부분 profkangrab (앞부분은 임의로 정했다)
DISPLAY_NAME = "Prof. Kang's RAB"              # 메뉴 막대 · Dock 에 표시되는 이름(AC-NF-4)

MIN_MACOS = "26.0"                             # `Info.plist` 의 `LSMinimumSystemVersion`

LAUNCHER = "import sys\nfrom nsu_kangs_rab import main\nif __name__ == '__main__':\n    main()\n"


ICONSET_SIZES = (16, 32, 128, 256, 512)       # AC-NF-4 ①: 각 1x · 2x 10종


def make_icns(source_png: str, work: str) -> str:
    """결정 0043 4 · 5항: 후보 1024px 그림에서 iconset 10종을 만들어 `.icns` 로 묶는다(`sips` · `iconutil`)."""
    iconset = os.path.join(work, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for n in ICONSET_SIZES:
        for scale in (1, 2):
            name = "icon_%dx%d%s.png" % (n, n, "@2x" if scale == 2 else "")
            px = n * scale
            subprocess.run(["sips", "-z", str(px), str(px), source_png, "--out", os.path.join(iconset, name)],
                           check=True, stdout=subprocess.DEVNULL)
    icns = os.path.join(work, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    return icns


def self_check(app: str) -> int:
    """D-080 재발 방지: 묶은 앱의 Python 으로 지연 import 되는 모듈을 실제로 가져오고 만든다(`--self-check`)."""
    exe = os.path.join(app, "Contents", "MacOS", APP_FILE_NAME)
    with tempfile.TemporaryDirectory(prefix="rab-selfcheck-") as home:
        env = {"HOME": home, "PATH": "/usr/bin:/bin", "QT_QPA_PLATFORM": "offscreen"}
        r = subprocess.run([exe, "--self-check"], env=env, capture_output=True, text=True, timeout=300)
    fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL") or ln.startswith("자체 점검")]
    print("== 자체 점검 (--self-check): OK %d건" % sum(1 for ln in r.stdout.splitlines() if ln.startswith("OK ")))
    for ln in fails:
        print(ln)
    if r.returncode != 0 and r.stderr.strip():
        print(r.stderr.strip()[-2000:])
    return r.returncode


def bundle_path(out: str) -> str:
    return os.path.join(out, APP_BUNDLE_DIR)


def remove_onedir(out: str) -> bool:
    """PyInstaller 의 `--windowed` 빌드는 onedir 산출물 `<출력 폴더>/ProfKangRAB/`(COLLECT)를 묶음과 별도로 남긴다.
    묶음 안의 파일은 이 폴더와 별개의 복사본이고 묶음 안의 심볼릭 링크는 모두 묶음 안을 가리키므로(b28 실측) 지워도 묶음에 영향이 없다.
    묶음이 있을 때만, 실제 폴더일 때만 지운다. 지웠으면 True."""
    d = os.path.join(out, APP_FILE_NAME)
    if os.path.isdir(d) and not os.path.islink(d) and os.path.isdir(os.path.join(out, APP_FILE_NAME + ".app")):
        shutil.rmtree(d)
        return True
    return False


def rename_bundle(out: str) -> str:
    """PyInstaller 가 만든 `<APP_FILE_NAME>.app` 을 `APP_BUNDLE_DIR` 로 바꾼다(경로를 목록 · 함수 인수로만 다룬다). 새 경로를 반환한다."""
    src = os.path.join(out, APP_FILE_NAME + ".app")
    dst = bundle_path(out)
    if os.path.lexists(dst):
        shutil.rmtree(dst)
    os.rename(src, dst)
    return dst


def write_localized_names(app: str) -> None:
    """D-130: 지역화한 표시 이름(`<언어>.lproj/InfoPlist.strings`). Dock · Finder 는 이 파일이 없으면 `ProfKangRAB.app` 의 파일 이름을 쓴다(추정)."""
    for lang in ("ko", "en"):
        d = os.path.join(app, "Contents", "Resources", lang + ".lproj")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "InfoPlist.strings"), "w", encoding="utf-8") as f:
            f.write('"CFBundleName" = "%s";\n"CFBundleDisplayName" = "%s";\n' % (DISPLAY_NAME, DISPLAY_NAME))


def main(argv) -> int:
    if len(argv) != 2:
        print("사용: build_app.py <출력 폴더>", file=sys.stderr)
        return 2
    out = os.path.abspath(argv[1])
    os.makedirs(out, exist_ok=True)
    from nsu_kangs_rab.platform.audio.system_sound import build_helper
    from nsu_kangs_rab.platform.stt.stt_speech import build_helper as build_stt_helper
    with tempfile.TemporaryDirectory(prefix="rab-build-") as work:
        helper = build_helper(os.path.join(work, "sck_audio"))
        stt_helper = build_stt_helper(os.path.join(work, "stt_speech"))
        launcher = os.path.join(work, "launcher.py")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(LAUNCHER)
        from nsu_kangs_rab.core import resources
        icns = make_icns(str(resources.app_icon_source_path()), work)
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", APP_FILE_NAME, "--osx-bundle-identifier", BUNDLE_ID,
               "--icon", icns,
               "--paths", os.path.join(ROOT, "src", "mac"), "--collect-data", "nsu_kangs_rab",
               # D-080: scipy 가 `__import__(__package__ + ".fft")` 로 동적으로 가져오는 하위 모듈은 PyInstaller 가 찾지 못한다
               "--collect-submodules", "scipy._external",
               "--add-binary", "%s:helper" % helper,
               "--add-binary", "%s:helper" % stt_helper,      # 결정 0162: 음성 인식 보조 프로그램(`resources.bundled_stt_helper_path`)
               "--add-data", "%s:third_party/diagram-design" % os.path.join(ROOT, "third_party", "diagram-design"),
               "--distpath", out, "--workpath", os.path.join(work, "work"), "--specpath", work, launcher]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            return r.returncode
    remove_onedir(out)                                # 단계 4 C: 중간 폴더를 남기지 않는다
    app = rename_bundle(out)
    plist = os.path.join(app, "Contents", "Info.plist")
    import plistlib
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info["LSMinimumSystemVersion"] = MIN_MACOS        # 결정 0162: SpeechAnalyzer 는 macOS 26 이상
    info["CFBundleName"] = DISPLAY_NAME
    info["CFBundleDisplayName"] = DISPLAY_NAME
    info["CFBundleDevelopmentRegion"] = "ko"          # D-079: 운영체제가 만드는 표준 항목의 언어
    info["CFBundleLocalizations"] = ["ko", "en"]
    info["LSHasLocalizedDisplayName"] = True          # D-130: Dock 이름표가 파일 이름(ProfKangRAB) 대신 표시 이름을 쓰게 한다(추정)
    with open(plist, "wb") as f:
        plistlib.dump(info, f)
    write_localized_names(app)
    # 목록 파일을 고쳤으므로 임시(ad-hoc) 서명을 다시 한다
    r = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app])
    if r.returncode != 0:
        return r.returncode
    # 결정 0162: 보조 프로그램의 위치 · 실행 권한 · 최소 운영체제 값을 확인한다(AC-FR4-21 의 파일 검사 대상)
    stt_path = os.path.join(app, "Contents", "Frameworks", "helper", "stt_speech")
    with open(plist, "rb") as f:
        min_os = plistlib.load(f).get("LSMinimumSystemVersion")
    print("== stt_speech:", stt_path, "존재", os.path.isfile(stt_path), "실행 가능", os.access(stt_path, os.X_OK))
    print("== LSMinimumSystemVersion:", min_os)
    if not os.path.isfile(stt_path) or not os.access(stt_path, os.X_OK) or min_os != MIN_MACOS:
        print("묶음 검사 실패: stt_speech 또는 LSMinimumSystemVersion", file=sys.stderr)
        return 1
    rc = self_check(app)
    if rc != 0:
        print("자체 점검 실패(종료 코드 %d): 묶음에서 빠진 모듈이 있다" % rc, file=sys.stderr)
        return rc
    print(app, "크기(MB):", round(sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(app) for f in fs
                                      if not os.path.islink(os.path.join(d, f))) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
