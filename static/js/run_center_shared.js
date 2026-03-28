/**
 * 运行中心共享上下文与跳转逻辑
 */
(function initRunCenterShared(globalScope) {
    const scope = globalScope || (typeof window !== 'undefined' ? window : globalThis);

    function cleanValue(value) {
        return value === null || value === undefined ? '' : String(value).trim();
    }

    function buildHref(pathname, pairs) {
        const params = new URLSearchParams();
        pairs.forEach(([key, value]) => {
            const normalized = cleanValue(value);
            if (normalized) {
                params.set(key, normalized);
            }
        });
        const query = params.toString();
        return query ? `${pathname}?${query}` : pathname;
    }

    function parseContext(search = '') {
        const params = new URLSearchParams(String(search || '').replace(/^\?/, ''));
        const currentScope = cleanValue(params.get('scope')) || 'scheduled';
        return {
            scope: currentScope,
            source: cleanValue(params.get('source')) || (currentScope === 'scheduled' ? 'scheduled-tasks' : 'registration-workbench'),
            task_uuid: cleanValue(params.get('task_uuid')),
            batch_id: cleanValue(params.get('batch_id')),
            plan_id: cleanValue(params.get('plan_id')),
            run_id: cleanValue(params.get('run_id')),
        };
    }

    function buildRunCenterHref(context = {}) {
        const currentScope = cleanValue(context.scope) || 'scheduled';
        return buildHref('/run-center', [
            ['scope', currentScope],
            ['task_uuid', currentScope === 'task' ? context.task_uuid : ''],
            ['batch_id', currentScope === 'batch' ? context.batch_id : ''],
            ['plan_id', currentScope === 'scheduled' ? context.plan_id : ''],
            ['run_id', currentScope === 'scheduled' ? context.run_id : ''],
            ['source', context.source || (currentScope === 'scheduled' ? 'scheduled-tasks' : 'registration-workbench')],
        ]);
    }

    function buildContextHref(context = {}) {
        const currentScope = cleanValue(context.scope) || 'scheduled';
        if (currentScope === 'scheduled') {
            return buildHref('/scheduled-tasks', [
                ['scope', 'scheduled'],
                ['plan_id', context.plan_id],
                ['run_id', context.run_id],
                ['source', context.source || 'scheduled-tasks'],
            ]);
        }

        return buildHref('/registration-workbench', [
            ['scope', currentScope],
            ['task_uuid', currentScope === 'task' ? context.task_uuid : ''],
            ['batch_id', currentScope === 'batch' ? context.batch_id : ''],
            ['source', context.source || 'registration-workbench'],
        ]);
    }

    function buildRetryHref(context = {}) {
        const currentScope = cleanValue(context.scope) || 'scheduled';
        if (currentScope === 'scheduled') {
            return buildHref('/scheduled-tasks', [
                ['retry', '1'],
                ['scope', 'scheduled'],
                ['plan_id', context.plan_id],
                ['run_id', context.run_id],
                ['source', context.source || 'scheduled-tasks'],
            ]);
        }

        return buildHref('/registration-workbench', [
            ['retry', '1'],
            ['scope', currentScope],
            ['task_uuid', currentScope === 'task' ? context.task_uuid : ''],
            ['batch_id', currentScope === 'batch' ? context.batch_id : ''],
            ['source', context.source || 'registration-workbench'],
        ]);
    }

    function buildRunsPath(context = {}, options = {}) {
        const page = Number.parseInt(options.page || options.pageIndex || '1', 10);
        const pageSize = Number.parseInt(options.page_size || options.pageSize || '20', 10);
        const currentScope = cleanValue(context.scope) || 'scheduled';
        return buildHref('/scheduled-runs', [
            ['plan_id', currentScope === 'scheduled' ? context.plan_id : ''],
            ['task_type', options.task_type || options.taskType || ''],
            ['status', options.status || ''],
            ['started_from', options.started_from || options.startedFrom || ''],
            ['started_to', options.started_to || options.startedTo || ''],
            ['page', Number.isInteger(page) && page > 0 ? String(page) : '1'],
            ['page_size', Number.isInteger(pageSize) && pageSize > 0 ? String(pageSize) : '20'],
        ]);
    }

    scope.runCenterShared = {
        parseContext,
        buildRunCenterHref,
        buildContextHref,
        buildRetryHref,
        buildRunsPath,
    };
})(typeof window !== 'undefined' ? window : globalThis);
