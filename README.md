# LSP-file-watcher-chokidar

A non-native file watcher implementation for [LSP](https://packagecontrol.io/packages/LSP) that enables support for the `workspace/didChangeWatchedFiles` LSP notification.

The reason that this is implemented as a separate package, and not natively within the LSP package, is that this relies on a separate process that does the file watching and for the built-in implementation we would like to use a native API provided by Sublime Text that it [doesn't provide](https://github.com/sublimehq/sublime_text/issues/2669) at the moment. See the [LSP issue #892](https://github.com/sublimelsp/LSP/issues/892) for supporting it natively within the LSP package.

## Usage

Having this package installed alongside the LSP enables support for an additional `file_watcher` object on the [Client configuration](https://lsp.sublimetext.io/guides/client_configuration/) object.

`file_watcher` object properties:

| Name    | Optional | Description |
|:--------|:---------|:------------|
| pattern | No       | The `glob` pattern defining which files within the workspace should be watched. The pattern is relative to the workspace root. Example: `{**/*.js,**/*.ts,**/*.json}`. See also [supported patterns](https://microsoft.github.io/language-server-protocol/specifications/specification-3-17/#fileSystemWatcher). |
| events  | Yes      | An array with the type of events to watch. Default: `["create", "change", "delete"]` (all supported types). |
| ignores | Yes      | An array of `glob` exclude patterns. By default this includes patterns from Sublime Text's `folder_exclude_patterns` and `file_exclude_patterns` settings and additionally the `'**/node_modules/**'` pattern. When overriding this option the defaults are not included anymore. |
