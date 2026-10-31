from __future__ import annotations

import asyncio
import fcntl
import json
import os
import time
from functools import wraps
from pathlib import Path
from typing import IO, Any, Callable, Optional

DEFAULT_LEASE_PATH = Path(
    os.environ.get("JSAUX_EINK_DESKTOP_LEASE", "/tmp/jsaux-eink-desktop.lock")
)
DEFAULT_TRANSFER_LEASE_PATH = Path(
    os.environ.get("JSAUX_SHARED_BLE_ADAPTER_LOCK")
    or os.environ.get("JSAUX_EINK_BLE_TRANSFER_LEASE")
    or "/tmp/jsaux-ble-adapter.lock"
)
DEFAULT_FOREGROUND_PRIORITY_PATH = Path(
    os.environ.get(
        "JSAUX_SHARED_BLE_FOREGROUND_PRIORITY", "/tmp/jsaux-ble-foreground-priority.json"
    )
)


def _open_foreground_priority_file(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        os.fchmod(fd, 0o666)
    except OSError:
        pass
    return fd


def claim_foreground_ble_priority(
    source: str,
    request_id: int,
    *,
    ttl: float = 180.0,
    path: Path | str = DEFAULT_FOREGROUND_PRIORITY_PATH,
) -> str:
    token = f"{source}:{request_id}"
    priority_path = Path(path)
    fd = _open_foreground_priority_file(priority_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        payload = json.dumps(
            {
                "source": source,
                "token": token,
                "expires_at": time.time() + max(1.0, float(ttl)),
            }
        ).encode("utf-8")
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return token


def clear_foreground_ble_priority(
    token: str,
    *,
    path: Path | str = DEFAULT_FOREGROUND_PRIORITY_PATH,
) -> None:
    priority_path = Path(path)
    fd = _open_foreground_priority_file(priority_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            payload = json.loads(os.read(fd, 4096).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if payload.get("token") == token:
            os.ftruncate(fd, 0)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def foreground_ble_priority_active(
    path: Path | str = DEFAULT_FOREGROUND_PRIORITY_PATH,
) -> bool:
    priority_path = Path(path)
    if not priority_path.exists():
        return False
    fd = _open_foreground_priority_file(priority_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            payload = json.loads(os.read(fd, 4096).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return bool(payload.get("token")) and float(payload.get("expires_at", 0.0)) > time.time()
    except (TypeError, ValueError):
        return False
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class DesktopLease:
    def __init__(self, path: Path | str = DEFAULT_LEASE_PATH) -> None:
        self.path = Path(path)
        self._file: IO[str] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lease_file = self.path.open("a+")
        try:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease_file.close()
            return False
        lease_file.seek(0)
        lease_file.truncate()
        lease_file.write(str(os.getpid()))
        lease_file.flush()
        self._file = lease_file
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


class BleTransferLease(DesktopLease):
    def __init__(self, path: Path | str = DEFAULT_TRANSFER_LEASE_PATH) -> None:
        super().__init__(path)

    async def __aenter__(self) -> "BleTransferLease":
        if self._file is None and not self.acquire():
            raise RuntimeError("Another process is already transferring a BLE frame")
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()

    async def acquire_async(
        self,
        *,
        timeout: float = 0.0,
        poll_interval: float = 0.05,
    ) -> bool:
        """Wait asynchronously for the shared BLE adapter without blocking the event loop."""

        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if self.acquire():
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(max(0.001, float(poll_interval)))


class SharedBleAdapterLease:
    """Serialize active BlueZ operations across JSAUX display processes."""

    def __init__(
        self,
        path: Path | str = DEFAULT_TRANSFER_LEASE_PATH,
        *,
        timeout: float = 120.0,
        poll_interval: float = 0.05,
        debug_logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.path = Path(path)
        self.timeout = max(0.0, float(timeout))
        self.poll_interval = max(0.001, float(poll_interval))
        self._debug_logger = debug_logger
        self._gate = asyncio.Lock()
        self._owner: Optional[asyncio.Task[Any]] = None
        self._depth = 0
        self._fd: Optional[int] = None

    async def acquire(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("shared BLE adapter lease requires an asyncio task")
        if self._owner is task:
            self._depth += 1
            return

        try:
            await asyncio.wait_for(self._gate.acquire(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                "Timed out waiting for this process's BLE adapter operation"
            ) from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for the shared BLE adapter")
                    await asyncio.sleep(min(self.poll_interval, remaining))
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
            self._fd = fd
            self._owner = task
            self._depth = 1
            if self._debug_logger is not None:
                self._debug_logger(f"shared BLE adapter acquired path={self.path}")
        except BaseException:
            os.close(fd)
            self._gate.release()
            raise

    async def release(self) -> None:
        task = asyncio.current_task()
        if self._owner is not task:
            raise RuntimeError("shared BLE adapter lease released by a different task")
        self._depth -= 1
        if self._depth > 0:
            return

        fd = self._fd
        self._fd = None
        self._owner = None
        try:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        finally:
            self._gate.release()

    async def __aenter__(self) -> "SharedBleAdapterLease":
        await self.acquire()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.release()


def shared_ble_operation(method: Callable[..., Any]) -> Callable[..., Any]:
    """Guard one EInk BlueZ operation with the shared adapter lease."""

    @wraps(method)
    async def guarded(self, *args, **kwargs):
        lease = getattr(self, "_shared_ble_adapter_lease", None)
        if lease is None:
            lease = SharedBleAdapterLease()
            self._shared_ble_adapter_lease = lease
        async with lease:
            return await method(self, *args, **kwargs)

    return guarded


def desktop_lease_active(path: Path | str = DEFAULT_LEASE_PATH) -> bool:
    lease_path = Path(path)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_file = lease_path.open("a+")
    try:
        try:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lease_file.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        lease_file.close()


def wait_for_ble_transfer_idle(
    path: Path | str = DEFAULT_TRANSFER_LEASE_PATH,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.05,
) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        transfer = BleTransferLease(path)
        if transfer.acquire():
            transfer.release()
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.001, float(poll_interval)))
