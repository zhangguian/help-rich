"""LLM API Key 加密存储(v2.1 §11.3)

使用 cryptography.Fernet(AES-128-CBC + HMAC)。
- FERNET_KEY 存 .env(首次启动自动生成写入)
- 明文 Key → Fernet 加密 → 存 SQLite
- 读时:从 SQLite 取出密文 → Fernet 解密 → 内存中使用
"""
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _ensure_fernet_key() -> str:
    """确保 .env 有 FERNET_KEY,缺失则自动生成并写入"""
    if settings.fernet_key:
        return settings.fernet_key

    # 自动生成
    new_key = Fernet.generate_key().decode()
    env_path = Path(".env")
    if env_path.exists():
        # 追加 FERNET_KEY(若还没有)
        with env_path.open("a", encoding="utf-8") as f:
            f.write(f"\nFERNET_KEY={new_key}\n")
    else:
        env_path.write_text(f"FERNET_KEY={new_key}\n", encoding="utf-8")

    # 同步更新 settings(本次进程内)
    settings.fernet_key = new_key
    return new_key


# 全局 cipher
_cipher = Fernet(_ensure_fernet_key().encode())


def encrypt(plaintext: str) -> str:
    """明文 → Fernet 密文(base64)"""
    return _cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Fernet 密文 → 明文

    失败时抛 InvalidToken(由调用方处理 → 返回 None 不抛错)。
    """
    return _cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


__all__ = ["encrypt", "decrypt", "InvalidToken"]