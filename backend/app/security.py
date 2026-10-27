"""Защита данных: хеширование паролей (PBKDF2), токены доступа, шифрование персональных полей при хранении (Fernet/AES).
Ключ берётся из KK_SECRET_KEY; при отсутствии создаётся файл data/secret.key (на сервере организации — хранилище секретов)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

_PBKDF_ITER = 200_000
_fernet: Optional[Fernet] = None


def _key() -> bytes:
    env = os.environ.get("KK_SECRET_KEY")
    if env:
        return base64.urlsafe_b64encode(hashlib.sha256(env.encode()).digest())
    data = Path(os.environ.get("KK_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    data.mkdir(parents=True, exist_ok=True)
    p = data / "secret.key"
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
        try:
            p.chmod(0o600)
        except OSError:
            pass
    return p.read_bytes()


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def reset_key_cache() -> None:
    global _fernet
    _fernet = None


def hash_password(pw: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _PBKDF_ITER)
    return "pbkdf2$%d$%s$%s" % (_PBKDF_ITER, salt.hex(), dk.hex())


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def new_invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих символов
    return "".join(secrets.choice(alphabet) for _ in range(8))


class EncryptedText(TypeDecorator):
    """Шифрованная строка: в БД лежит шифртекст, в коде — обычная строка."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return fernet().encrypt(str(value).encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            return "[не удалось расшифровать]"
