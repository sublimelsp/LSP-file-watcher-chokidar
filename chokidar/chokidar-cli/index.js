#!/usr/bin/env node

const { resolve } = require('path');
const readline = require('readline');
const debounce = require('lodash.debounce');
const chokidar = require('chokidar');

/** @type {Record<ChokidarCli.ChokidarEventType, ChokidarCli.LspEventType | null>} */
const CHOKIDAR_EVENT_TYPE_TO_LSP = {
    add: 'create',
    addDir: null,
    change: 'change',
    unlink: 'delete',
    unlinkDir: null,
};

/** @type {Partial<ChokidarCli.RegisterWatcherOptions>} */
const defaultOpts = {
    debounceChanges: 400,
    debug: false,
    events: [],
    followSymlinks: false,
    ignores: null,
    initial: false,
    polling: false,
    pollInterval: 100,
    pollIntervalBinary: 300,
};

/** @type {Map<number, chokidar.FSWatcher>} */
const watchers = new Map();
/** @type {import('readline').ReadLine | null} */
let rl = null;

function main() {
    rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
    });

    rl.on('line', handleInput);
}

/** @param {string} line */
function handleInput(line) {
    if (!line) {
        if (rl) {
            console.error('Closing readline interface due to empty input.');
            rl.close();
            rl = null;
        }
        return;
    }

    /** @type {ChokidarCli.InputCommand} */
    let data;

    try {
        data = JSON.parse(line);
    } catch (error) {
        console.error(`Failed parsing input: "${line}"`);
        return;
    }

    if (!data.register && !data.unregister) {
        console.error('Input data must contain either "register" or "unregister" property.');
        return;
    }

    if (data.unregister) {
        const watcher = watchers.get(data.unregister);
        if (watcher) {
            watcher.close();
            watchers.delete(data.unregister);
        } else {
            console.error(`Unregistering watcher with ID "${data.unregister}" failed. No watcher registered.`);
        }
    }

    if (data.register) {
        const userOpts = data.register;
        const opts = Object.assign({}, defaultOpts, userOpts);
        if (!opts.uid || !opts.cwd) {
            console.error('Failed registering watcher. Missing "uid" or "cwd".');
            return;
        }
        registerWatcher(opts);
    }
}

/** @param {ChokidarCli.RegisterWatcherOptions} opts */
function registerWatcher(opts) {
    const chokidarOpts = createChokidarOpts(opts);
    const watcher = chokidar.watch(opts.patterns, chokidarOpts);
    if (watchers.has(opts.uid)) {
        console.error(`Failed registering watcher. Watcher with ID "${opts.uid}" already exists.`);
        return;
    }
    watchers.set(opts.uid, watcher);

    const debouncedChangesRun = debounce(reportDebouncedChanges, opts.debounceChanges);
    /** @type {string[]} */
    let debouncedChangesQueue = [];

    function reportDebouncedChanges() {
        if (debouncedChangesQueue.length) {
            console.log(debouncedChangesQueue.join('\n'));
            console.log('<flush>');
            debouncedChangesQueue = [];
        }
    }

    watcher.on('all', (event, path) => {
        const lspEvent = CHOKIDAR_EVENT_TYPE_TO_LSP[event];

        if (!lspEvent) {
            if (opts.debug) {
                console.error(`Unsupported event type "${event}".`);
            }
            return;
        }

        const eventString = `${opts.uid}:${lspEvent}:${path}`;

        if (opts.debounceChanges > 0) {
            debouncedChangesQueue.push(eventString);
            debouncedChangesRun();
        } else {
            console.log(eventString);
            console.log('<flush>');
        }
    });

    watcher.on('error', error => {
        console.error('Error:', error);
        console.error(error.stack);
    });

    watcher.once('ready', () => {
        const list = opts.patterns.map(pattern => resolve(pattern)).join('", "');
        if (opts.debug) {
            console.error('Watching', `"${list}" ..`);
        }
    });
}

/**
 * @param {ChokidarCli.RegisterWatcherOptions} opts
 * @return {chokidar.WatchOptions}
 */
function createChokidarOpts(opts) {
    /** @type {chokidar.WatchOptions} */
    const chokidarOpts = {
        cwd: opts.cwd,
        followSymlinks: opts.followSymlinks,
        usePolling: opts.polling,
        interval: opts.pollInterval,
        binaryInterval: opts.pollIntervalBinary,
        ignoreInitial: !opts.initial,
    };

    if (opts.ignores) {
        chokidarOpts.ignored = opts.ignores;
    }

    return chokidarOpts;
}

main();

// Set up a parent-process watchdog.
// Based on https://github.com/microsoft/vscode-languageserver-node/blob/54b686f0a1817a845f34bda19d5b1651c445f2cf/server/src/node/main.ts#L78-L93
const parentProcessPid = process.ppid;
if (Number.isInteger(parentProcessPid)) {
    // Set up a timer to periodically check if the parent is still alive.
    setInterval(() => {
        try {
            process.kill(parentProcessPid, 0);
        } catch (ex) {
            // Parent process doesn't exist anymore. Exit the server.
            if (rl) {
                rl.close();
            }
            process.exit(1);
        }
    }, 3000);
}
