"""Claude API 키의 보관 (AC-FR1-11 · 16 · 17, B-13).

- 키체인 접근은 이 모듈에서만 한다. 서비스 이름은 앱 전용 하나로 고정한다.
- Claude Code 의 키체인 항목과 자격 증명 파일에는 접근하지 않는다(인증 원칙 1항).
- 키는 반환값 외의 어디에도 쓰지 않는다: 예외 문구 · repr · 로그에 넣지 않는다.
- 백엔드 생성 지점은 `ApiKeyStore(backend=...)` 의 주입이다. 주입하지 않으면 macOS 키체인 백엔드를 직접 만든다.
"""
from __future__ import annotations

from typing import Callable, Optional

SERVICE = "ProfKangRAB.ClaudeAPIKey"
DEFAULT_ACCOUNT = "default"


def _caused_by_not_found(e: BaseException) -> bool:
    """원인이 `NotFound` 이거나, 원인이 없을 때(백엔드가 이유를 덧붙이지 않은 "없음")만 True.
    macOS 백엔드는 항상 원인을 붙이므로 거부 · 잠김 · 기타는 여기서 False 가 된다."""
    c = e.__cause__
    return c is None or any(k.__name__ == "NotFound" for k in type(c).__mro__)


class ApiKeyStoreError(Exception):
    """키체인 접근 실패(거부 · 백엔드 없음 · 평문 백엔드 선택). 메시지에 키가 들어가지 않는다."""


def macos_backend():
    """`keyring.backends.macOS.Keyring` 을 직접 만든다. 환경 · 설정 파일의 백엔드 선택은 따르지 않는다."""
    try:
        from keyring.backends import macOS  # type: ignore
        backend = macOS.Keyring()
    except Exception as e:  # ImportError · RuntimeError(macOS 가 아님) 등
        raise ApiKeyStoreError("macOS 키체인 백엔드를 만들 수 없다: %s" % type(e).__name__) from None
    return backend


def _is_macos_keychain(backend) -> bool:
    return type(backend).__module__.startswith("keyring.backends.macOS")


class ApiKeyStore:
    def __init__(self, backend=None, account: str = DEFAULT_ACCOUNT,
                 backend_factory: Callable[[], object] = macos_backend, require_macos: Optional[bool] = None):
        """`backend` 를 주입하면 그대로 쓴다(시험의 기록 백엔드). 주입하지 않으면 `backend_factory()` 를 처음 쓸 때 만들고,
        macOS 키체인이 아니면 `ApiKeyStoreError` 로 멈춘다."""
        if not isinstance(account, str) or not account.strip():
            raise ApiKeyStoreError("계정 이름이 비어 있다")
        self._backend = backend
        self._factory = backend_factory
        self._require_macos = (backend is None) if require_macos is None else require_macos
        self.account = account

    def __repr__(self) -> str:
        return "ApiKeyStore(service=%r, account=%r)" % (SERVICE, self.account)

    def _b(self):
        if self._backend is None:
            b = self._factory()
            if self._require_macos and not _is_macos_keychain(b):
                raise ApiKeyStoreError("키체인 백엔드가 macOS 키체인이 아니다")
            self._backend = b
        return self._backend

    def get(self) -> Optional[str]:
        """저장된 키. 없으면 None. 접근이 거부되면 `ApiKeyStoreError`."""
        try:
            v = self._b().get_password(SERVICE, self.account)
        except ApiKeyStoreError:
            raise
        except Exception as e:
            raise ApiKeyStoreError("키체인 읽기 실패: %s" % type(e).__name__) from None
        return v if isinstance(v, str) and v else None

    def has(self) -> bool:
        return self.get() is not None

    def set(self, key: str) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ApiKeyStoreError("빈 키는 저장하지 않는다")
        try:
            self._b().set_password(SERVICE, self.account, key.strip())
        except ApiKeyStoreError:
            raise
        except Exception as e:
            raise ApiKeyStoreError("키체인 쓰기 실패: %s" % type(e).__name__) from None

    def delete(self) -> bool:
        """지웠으면 True, 원래 없었으면 False."""
        try:
            self._b().delete_password(SERVICE, self.account)
            return True
        except ApiKeyStoreError:
            raise
        except Exception as e:
            # keyring 의 macOS 백엔드는 SecItemDelete 의 모든 오류를 PasswordDeleteError 로 감싼다(D-031).
            # 항목이 없을 때(원인이 NotFound)만 False 이고, 거부 · 잠김 · 기타 원인은 오류이다.
            if type(e).__name__ == "PasswordDeleteError" and _caused_by_not_found(e):
                return False
            raise ApiKeyStoreError("키체인 삭제 실패: %s" % type(e).__name__) from None
