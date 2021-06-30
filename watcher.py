from LSP.plugin import FileWatcher
from LSP.plugin import FileWatcherProtocol
from LSP.plugin import FileWatcherKind
from LSP.plugin import register_file_watcher_implementation
from LSP.plugin.core.typing import List, Optional
from lsp_utils import NodeRuntime
from os import path
from sublime_lib import ActivityIndicator
from threading import Thread
import sublime
import subprocess
import weakref


CHOKIDAR_DIR = path.join(path.dirname(path.realpath(__file__)), 'chokidar')
CHOKIDAR_CLI_PATH = path.join(CHOKIDAR_DIR, 'chokidar-cli', 'index.js')
STORAGE_PATH = path.abspath(path.join(sublime.cache_path(), "..", "Package Storage"))


CHOKIDAR_EVENT_TYPE_TO_WATCH_KIND = {
    'add': 'create',
    'change': 'change',
    'unlink': 'delete',
}


def log(message: str) -> None:
    print('{}: {}'.format(__package__, message))


class FileWatcherChokidar(FileWatcher):

    @classmethod
    def create(
        cls,
        root_path: str,
        pattern: str,
        events: List[FileWatcherKind],
        ignores: List[str],
        handler: FileWatcherProtocol
    ) -> 'FileWatcher':
        node_runtime = NodeRuntime.get(__package__, STORAGE_PATH, (12, 0, 0))
        if not node_runtime:
            raise Exception('{}: Failed to locate the Node.js Runtime'.format(__package__))
        watcher = FileWatcherChokidar(root_path, pattern, events, ignores, handler, node_runtime)
        watcher.start()
        return watcher

    def __init__(
        self,
        root_path: str,
        pattern: str,
        events: List[FileWatcherKind],
        ignores: List[str],
        handler: FileWatcherProtocol,
        node_runtime: NodeRuntime
    ) -> None:
        self._root_path = root_path
        self._pattern = pattern
        self._events = events
        self._ignores = ignores
        self._handler = weakref.ref(handler)
        self._node_runtime = node_runtime
        self._process = None  # type: Optional[subprocess.Popen]
        self._thread = None  # type: Optional[Thread]

    def start(self) -> None:
        self._thread = Thread(target=self._run_thread)
        self._thread.start()

    def destroy(self) -> None:
        if self._process and self._thread:
            self._process.terminate()
            self._thread.join()

    def _run_thread(self) -> None:
        if not path.isdir(path.join(CHOKIDAR_DIR, 'node_modules')):
            with ActivityIndicator(sublime.active_window(), 'Installing file watcher'):
                self._node_runtime.npm_install(CHOKIDAR_DIR)
        log('Starting watcher for directory "{}". Pattern: {}'.format(self._root_path, self._pattern))
        node_bin = self._node_runtime.node_bin()
        if not node_bin:
            raise Exception('Node binary not resolved')
        command = [node_bin, CHOKIDAR_CLI_PATH, self._pattern]
        for ignore in self._ignores:
            command.extend(['--ignore', ignore])
        log('Command: {}'.format(' '.join(command)))
        self._process = subprocess.Popen(command, stdout=subprocess.PIPE, universal_newlines=True, cwd=self._root_path)
        while True:
            if not self._process.stdout:
                break
            output = self._process.stdout.readline()
            if output == '' and self._process.poll() is not None:
                break
            if output:
                self._on_output(output.strip())
        log('Watcher ended')

    def _on_output(self, line: str) -> None:
        handler = self._handler()
        if not handler:
            return
        if ':' not in line:
            log('Invalid watcher output: {}'.format(line))
            return
        event_type, cwd_relative_path = line.split(':', 1)
        event_kind = CHOKIDAR_EVENT_TYPE_TO_WATCH_KIND.get(event_type)
        if event_kind in self._events:
            handler.on_file_event_async([(event_kind, path.join(self._root_path, cwd_relative_path))])


register_file_watcher_implementation(FileWatcherChokidar)
