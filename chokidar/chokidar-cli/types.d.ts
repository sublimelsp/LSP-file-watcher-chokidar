declare namespace ChokidarCli {
    type ChokidarEventType = 'add' | 'addDir' | 'change' | 'unlink' | 'unlinkDir'

    type InputCommand = {
        register?: RegisterWatcherOptions
        unregister?: RegisterWatcherOptions['uid']
    }
    type LspEventType = 'create' | 'change' | 'delete'

    type RegisterWatcherOptions = {
        cwd: string
        debounceChanges: number
        debug: boolean
        events: LspEventType[]
        followSymlinks: boolean
        ignores: string[] | null
        initial: boolean
        patterns: string[]
        polling: boolean
        pollInterval: number
        pollIntervalBinary: number
        uid: number
    }
}
