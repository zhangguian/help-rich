"""JSON 文件缓存(arch §4.6.2 原子写 + §5.6 缓存)

- TTL 默认 300s(行情 5 分钟缓存)
- 原子写:临时文件 + os.replace,防并发写坏
- 多进程安全:读写都有锁
"""
import json
import os
import threading
import time
from pathlib import Path


class JSONCache:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or Path("./cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, key: str) -> Path:
        # key 只允许字母数字和 ._-,防止路径穿越
        safe = "".join(c for c in key if c.isalnum() or c in "._-")
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str, ttl_seconds: int = 300) -> dict | None:
        """读取缓存,过期或损坏返回 None"""
        with self._lock:
            path = self._path(key)
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
            if time.time() - data.get("_ts", 0) > ttl_seconds:
                return None
            return data.get("payload")

    def set(self, key: str, payload: dict) -> None:
        """原子写入缓存"""
        with self._lock:
            path = self._path(key)
            content = json.dumps(
                {"_ts": time.time(), "payload": payload},
                ensure_ascii=False,
            )
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, path)
            except OSError:
                pass

    def delete(self, key: str) -> None:
        with self._lock:
            path = self._path(key)
            if path.exists():
                path.unlink(missing_ok=True)
