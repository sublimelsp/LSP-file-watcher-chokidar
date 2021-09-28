from hashlib import md5
from json import dumps
from LSP.plugin import FileWatcher
from LSP.plugin import FileWatcherEventType
from LSP.plugin import FileWatcherProtocol
from LSP.plugin import register_file_watcher_implementation
from LSP.plugin.core.transports import AbstractProcessor
from LSP.plugin.core.transports import ProcessTransport
from LSP.plugin.core.transports import StopLoopError
from LSP.plugin.core.transports import Transport
from LSP.plugin.core.transports import TransportCallbacks
from LSP.plugin.core.typing import Any, Callable, cast, Dict, IO, List, Optional, Tuple
from lsp_utils import NodeRuntime
from os import makedirs
from os import path
from os import remove
from shutil import rmtree
from shutil import which
from sublime_lib import ActivityIndicator
from sublime_lib import ResourcePath
import sublime
import subprocess
import weakref


PACKAGE_STORAGE = path.abspath(path.join(sublime.cache_path(), "..", "Package Storage"))
VIRTUAL_CHOKIDAR_PATH = 'Packages/{}/{}/'.format(__package__, 'chokidar')
CHOKIDAR_PACKAGE_STORAGE = path.join(PACKAGE_STORAGE, __package__)
CHOKIDAR_INSTALATION_MARKER = path.join(CHOKIDAR_PACKAGE_STORAGE, '.installing')
CHOKIDAR_CLI_PATH = path.join(CHOKIDAR_PACKAGE_STORAGE, 'chokidar', 'chokidar-cli', 'index.js')


def log(message: str) -> None:
    print('{}: {}'.format(__package__, message))


class TemporaryInstallationMarker:
    """
    Creates a temporary file for the duration of the context.
    The temporary file is not removed if an exception triggeres within the context.

    Usage:

    ```
    with TemporaryInstallationMarker('/foo/file'):
        ...
    ```
    """

    def __init__(self, marker_path: str) -> None:
        self._marker_path = marker_path

    def __enter__(self) -> 'TemporaryInstallationMarker':
        makedirs(path.dirname(self._marker_path), exist_ok=True)
        open(self._marker_path, 'a').close()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type:
            # Don't remove the marker on exception.
            return
        remove(self._marker_path)


class StringTransportHandler(AbstractProcessor[str]):

    def write_data(self, writer: IO[bytes], data: str) -> None:
        writer.write('{}\n'.format(data).encode('utf-8'))

    def read_data(self, reader: IO[bytes]) -> Optional[str]:
        data = reader.readline()
        text = None
        try:
            text = data.decode('utf-8').strip()
        except Exception as ex:
            log("decode error: {}".format(ex))
        if not text:
            raise StopLoopError()
        return text


class FileWatcherController(FileWatcher):

    @classmethod
    def create(
        cls,
        root_path: str,
        patterns: List[str],
        events: List[FileWatcherEventType],
        ignores: List[str],
        handler: FileWatcherProtocol
    ) -> 'FileWatcher':
        return file_watcher.register_watcher(root_path, patterns, events, ignores, handler)

    def __init__(self, on_destroy: Callable[[], None]) -> None:
        self._on_destroy = on_destroy

    def destroy(self) -> None:
        self._on_destroy()


class FileWatcherChokidar(TransportCallbacks):

    def __init__(self) -> None:
        self._last_controller_id = 0
        self._handlers = {}  # type: Dict[str, Tuple[weakref.ref[FileWatcherProtocol], str]]
        self._node_runtime = None  # type: Optional[NodeRuntime]
        self._transport = None  # type: Optional[Transport[str]]

    def register_watcher(
        self,
        root_path: str,
        patterns: List[str],
        events: List[FileWatcherEventType],
        ignores: List[str],
        handler: FileWatcherProtocol
    ) -> 'FileWatcherController':
        self._last_controller_id += 1
        controller_id = self._last_controller_id
        controller = FileWatcherController(on_destroy=lambda: self._on_watcher_removed(controller_id))
        self._on_watcher_added(root_path, patterns, events, ignores, handler)
        return controller

    def _on_watcher_added(
        self,
        root_path: str,
        patterns: List[str],
        events: List[FileWatcherEventType],
        ignores: List[str],
        handler: FileWatcherProtocol
    ) -> None:
        self._handlers[str(self._last_controller_id)] = (weakref.ref(handler), root_path)
        if len(self._handlers) and not self._transport:
            self._start_process()
        if not self._transport:
            log('ERROR: Failed creating transport')
            return
        # log('Starting watcher for directory "{}". Pattern: {}. Ignores: {}'.format(root_path, patterns, ignores))
        register_data = {
            'register': {
                'cwd': root_path,
                'events': events,
                'ignores': ignores,
                'patterns': patterns,
                'uid': self._last_controller_id,
            }
        }
        self._transport.send(self._to_json(register_data))

    def _on_watcher_removed(self, controller_id: int) -> None:
        # log('Removing watcher with id "{}"'.format(controller_id))
        self._handlers.pop(str(controller_id))
        if not self._transport:
            log('ERROR: Transport does not exist')
            return
        self._transport.send(self._to_json({'unregister': controller_id}))
        if not len(self._handlers) and self._transport:
            self._end_process()

    def _to_json(self, obj: Any) -> str:
        return dumps(
            obj,
            ensure_ascii=False,
            sort_keys=False,
            check_circular=False,
            separators=(',', ':')
        )

    def _start_process(self) -> None:
        # log('Starting watcher process')
        node_runtime = self._resolve_node_runtime()
        node_bin = node_runtime.node_bin()
        if not node_bin:
            raise Exception('Node binary not resolved')
        self._initialize_storage(node_runtime)
        command = [node_bin, CHOKIDAR_CLI_PATH]
        startup_info = _create_startup_info(command)
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startup_info)
        if not process.stdin or not process.stdout:
            raise RuntimeError('Failed initializing watcher process')
        self._transport = ProcessTransport(
            'lspwatcher', process, None, process.stdout, process.stdin, process.stderr, StringTransportHandler(), self)

    def _resolve_node_runtime(self) -> NodeRuntime:
        if self._node_runtime:
            return self._node_runtime
        self._node_runtime = NodeRuntime.get(__package__, PACKAGE_STORAGE, (12, 0, 0))
        if not self._node_runtime:
            raise Exception('{}: Failed to locate the Node.js Runtime'.format(__package__))
        return self._node_runtime

    def _initialize_storage(self, node_runtime: NodeRuntime) -> None:
        destination_dir = path.join(CHOKIDAR_PACKAGE_STORAGE, 'chokidar')
        installed = False
        if path.isdir(path.join(destination_dir, 'node_modules')):
            # Dependencies already installed. Check if the version has changed or last installation did not complete.
            try:
                src_hash = md5(ResourcePath(VIRTUAL_CHOKIDAR_PATH, 'package.json').read_bytes()).hexdigest()
                with open(path.join(destination_dir, 'package.json'), 'rb') as file:
                    dst_hash = md5(file.read()).hexdigest()
                if src_hash == dst_hash and not path.isfile(CHOKIDAR_INSTALATION_MARKER):
                    installed = True
            except FileNotFoundError:
                # Needs to be re-installed.
                pass

        if not installed:
            with TemporaryInstallationMarker(CHOKIDAR_INSTALATION_MARKER):
                if path.isdir(destination_dir):
                    rmtree(destination_dir)
                ResourcePath(VIRTUAL_CHOKIDAR_PATH).copytree(destination_dir, exist_ok=True)
                with ActivityIndicator(sublime.active_window(), 'Installing file watcher'):
                    node_runtime.npm_install(destination_dir)

    def _end_process(self, exception: Optional[Exception] = None) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
            log('Watcher process ended. Exception: {}'.format(str(exception)))

    # --- TransportCallbacks -------------------------------------------------------------------------------------------

    def on_payload(self, payload: str) -> None:
        if ':' not in payload:
            log('Invalid watcher output: {}'.format(payload))
            return
        uid, event_type, cwd_relative_path = payload.split(':', 2)
        handler, root_path = self._handlers[uid]
        handler_impl = handler()
        if not handler_impl:
            log('ERROR: on_payload(): Handler already deleted')
            return
        event_kind = cast(FileWatcherEventType, event_type)
        handler_impl.on_file_event_async([(event_kind, path.join(root_path, cwd_relative_path))])

    def on_stderr_message(self, message: str) -> None:
        log('ERROR: {}'.format(message))

    def on_transport_close(self, exit_code: int, exception: Optional[Exception]) -> None:
        self._end_process(exception)


def _create_startup_info(args: List[str]) -> Any:
    startupinfo = None
    if sublime.platform() == "windows":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.SW_HIDE | subprocess.STARTF_USESHOWWINDOW  # type: ignore
        executable_arg = args[0]
        _, ext = path.splitext(executable_arg)
        if len(ext) < 1:
            path_to_executable = which(executable_arg)
            # what extensions should we append so CreateProcess can find it?
            # node has .cmd
            # dart has .bat
            # python has .exe wrappers - not needed
            for extension in ['.cmd', '.bat']:
                if path_to_executable and path_to_executable.lower().endswith(extension):
                    args[0] = executable_arg + extension
                    break
    return startupinfo


file_watcher = FileWatcherChokidar()


register_file_watcher_implementation(FileWatcherController)
