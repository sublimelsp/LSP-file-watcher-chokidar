from __future__ import annotations

from functools import partial
from LSP.plugin.core.logging import exception_log
from queue import Queue
from typing import final
from typing import Generic
from typing import IO
from typing import Protocol
from typing import TYPE_CHECKING
from typing import TypeVar
from typing_extensions import override
import contextlib
import sublime
import subprocess
import threading
import weakref

if TYPE_CHECKING:
    import socket


T = TypeVar('T')
T_contra = TypeVar('T_contra', contravariant=True)

TCP_CONNECT_TIMEOUT = 5  # seconds


class StopLoopError(Exception):
    pass


class Transport(Generic[T]):

    def send(self, payload: T) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class TransportCallbacks(Protocol[T_contra]):

    def on_transport_close(self, exit_code: int, exception: Exception | None) -> None:
        ...

    def on_payload(self, payload: T_contra) -> None:
        ...

    def on_stderr_message(self, message: str) -> None:
        ...


class AbstractProcessor(Generic[T]):

    def write_data(self, writer: IO[bytes], data: T) -> None:
        raise NotImplementedError

    def read_data(self, reader: IO[bytes]) -> T | None:
        raise NotImplementedError


@final
class ProcessTransport(Transport[T]):

    def __init__(self, name: str, process: subprocess.Popen[bytes] | None, socket: socket.socket | None,
                 reader: IO[bytes], writer: IO[bytes], stderr: IO[bytes] | None,
                 processor: AbstractProcessor[T], callback_object: TransportCallbacks[T]) -> None:
        self._closed = False
        self._process = process
        self._socket = socket
        self._reader = reader
        self._writer = writer
        self._stderr = stderr
        self._processor = processor
        self._reader_thread = threading.Thread(target=self._read_loop, name=f'{name}-reader')
        self._writer_thread = threading.Thread(target=self._write_loop, name=f'{name}-writer')
        self._callback_object = weakref.ref(callback_object)
        self._send_queue: Queue[T | None] = Queue(0)
        self._reader_thread.start()
        self._writer_thread.start()
        if stderr:
            self._stderr_thread = threading.Thread(target=self._stderr_loop, name=f'{name}-stderr')
            self._stderr_thread.start()

    @override
    def send(self, payload: T) -> None:
        self._send_queue.put_nowait(payload)

    @override
    def close(self) -> None:
        if not self._closed:
            self._send_queue.put_nowait(None)
            if self._socket:
                self._socket.close()
            self._closed = True

    def _join_thread(self, t: threading.Thread) -> None:
        if t.ident == threading.current_thread().ident:
            return
        try:
            t.join(2)
        except TimeoutError as ex:
            exception_log(f"failed to join {t.name} thread", ex)

    def __del__(self) -> None:
        self.close()
        self._join_thread(self._writer_thread)
        self._join_thread(self._reader_thread)
        if self._stderr_thread:
            self._join_thread(self._stderr_thread)

    def _read_loop(self) -> None:
        exception = None
        try:
            while self._reader:
                payload = self._processor.read_data(self._reader)
                if payload is None:
                    continue

                def invoke(p: T) -> None:
                    if self._closed:
                        return
                    callback_object = self._callback_object()
                    if callback_object:
                        callback_object.on_payload(p)

                sublime.set_timeout_async(partial(invoke, payload))
        except (AttributeError, BrokenPipeError, StopLoopError):
            pass
        except Exception as ex:
            exception = ex
        if exception:
            self._end(exception)
        else:
            self._send_queue.put_nowait(None)

    def _end(self, exception: Exception | None) -> None:
        exit_code = 0
        if self._process:
            if not exception:
                with contextlib.suppress(AttributeError, ProcessLookupError, subprocess.TimeoutExpired):
                    # Allow the process to stop itself.
                    exit_code = self._process.wait(1)
            if self._process.poll() is None:
                try:
                    # The process didn't stop itself. Terminate!
                    self._process.kill()
                    # still wait for the process to die, or zombie processes might be the result
                    # Ignore the exit code in this case, it's going to be something non-zero because we sent SIGKILL.
                    self._process.wait()
                except (AttributeError, ProcessLookupError):
                    pass
                except Exception as ex:
                    exception = ex  # TODO: Old captured exception is overwritten

        def invoke() -> None:
            callback_object = self._callback_object()
            if callback_object:
                callback_object.on_transport_close(exit_code, exception)

        sublime.set_timeout_async(invoke)
        self.close()

    def _write_loop(self) -> None:
        exception: Exception | None = None
        try:
            while self._writer:
                d = self._send_queue.get()
                if d is None:
                    break
                self._processor.write_data(self._writer, d)
                self._writer.flush()
        except (BrokenPipeError, AttributeError):
            pass
        except Exception as ex:
            exception = ex
        self._end(exception)

    def _stderr_loop(self) -> None:
        try:
            while self._stderr:
                if self._closed:
                    # None message already posted, just return
                    return
                message = self._stderr.readline().decode('utf-8', 'replace')
                if not message:
                    continue
                callback_object = self._callback_object()
                if callback_object:
                    callback_object.on_stderr_message(message.rstrip())
                else:
                    break
        except (BrokenPipeError, AttributeError):
            pass
        except Exception as ex:
            exception_log('unexpected exception type in stderr loop', ex)
        self._send_queue.put_nowait(None)
