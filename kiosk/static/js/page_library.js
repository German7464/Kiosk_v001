'use strict';
(() => {
    const root = typeof window !== 'undefined' ? window : globalThis;
    const doc = root.document;
    if (!doc) return;

    const API_OBJECTS = '/editor/pages/objects';
    const API_PLAN = '/editor/pages/plan';
    const EVENTS_API = '/editor/objects';
    const KINDS = ['dataset', 'block', 'layout', 'page', 'profile', 'assignment'];
    const KIND_LABELS = {
        dataset: 'Dataset', block: 'Block', layout: 'Layout', page: 'Page',
        profile: 'Profile', assignment: 'Assignment',
    };
    const TARGETS = ['tv-landscape', 'tv-portrait', 'kiosk-landscape', 'kiosk-portrait'];
    const TARGET_LABELS = {
        'tv-landscape': 'TV landscape', 'tv-portrait': 'TV portrait',
        'kiosk-landscape': 'Kiosk landscape', 'kiosk-portrait': 'Kiosk portrait',
    };
    const state = {
        catalog: [], events: [], byId: new Map(), eventById: new Map(),
        current: null, dirty: false, stale: false, saving: false,
        layout: null, grid: null, previewGrid: null, initialized: false,
    };
    let role = '';
    let loadingForm = false;

    function one(selector, scope) {
        return (scope || doc).querySelector(selector);
    }

    function all(selector, scope) {
        return Array.from((scope || doc).querySelectorAll(selector));
    }

    function field(form, name) {
        return form ? form.querySelector('[name="' + name + '"]') : null;
    }

    function csrf() {
        const panel = one('[data-page-library]');
        if (panel && panel.dataset.csrf) return panel.dataset.csrf;
        const meta = one('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    function isAdministrator() {
        return role === 'administrator';
    }

    function setStatus(message, tone) {
        const node = one('#page-library-status');
        if (!node) return;
        node.textContent = String(message || '');
        if (tone) node.dataset.tone = tone;
        else delete node.dataset.tone;
    }

    function setPlanStatus(message, tone) {
        const node = one('#plan-status');
        if (!node) return;
        node.textContent = String(message || '');
        if (tone) node.dataset.tone = tone;
        else delete node.dataset.tone;
    }

    function requestError(message, status, code) {
        const error = new Error(message);
        error.status = status;
        error.code = code;
        return error;
    }

    async function request(path, payload) {
        const options = {
            method: payload === undefined ? 'GET' : 'POST',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        };
        if (payload !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.headers['X-CSRF-Token'] = csrf();
            options.body = JSON.stringify(payload);
        }
        const response = await fetch(path, options);
        let result = null;
        try {
            result = await response.json();
        } catch (ignored) {
            result = null;
        }
        if (!response.ok) {
            const code = result && typeof result.error === 'string' ? result.error : 'request_refused';
            throw requestError(result && typeof result.error === 'string'
                ? result.error : 'Request refused (' + response.status + ').', response.status, code);
        }
        if (result === null) throw requestError('The server returned an invalid JSON response.', response.status, 'invalid_response');
        return result;
    }

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function createId(kind) {
        if (!KINDS.includes(kind)) throw new Error('Unknown object kind.');
        const webCrypto = typeof crypto !== 'undefined' && crypto ? crypto : root.crypto;
        if (!webCrypto || typeof webCrypto.randomUUID !== 'function') {
            throw new Error('Secure random UUID generation is unavailable.');
        }
        return kind + '-' + webCrypto.randomUUID().replaceAll('-', '').toLowerCase();
    }

    function kindOf(objectOrId) {
        const id = typeof objectOrId === 'string' ? objectOrId : objectOrId && objectOrId.id;
        const prefix = String(id || '').split('-')[0];
        if (KINDS.includes(prefix)) return prefix;
        const payload = objectOrId && typeof objectOrId === 'object' ? objectOrId.payload : null;
        if (!payload || typeof payload !== 'object') return null;
        if ('device' in payload && 'profile' in payload) return 'assignment';
        if ('selection' in payload) return 'profile';
        if ('layouts' in payload && 'fallback' in payload) return 'page';
        if ('columns' in payload && 'rows' in payload && 'placements' in payload) return 'layout';
        if ('dataset' in payload && 'limit' in payload) return 'block';
        if ('module' in payload && 'events' in payload) return 'dataset';
        return null;
    }

    function objectById(id) {
        return state.byId.get(String(id)) || null;
    }

    function eventById(id) {
        return state.eventById.get(String(id)) || null;
    }

    function objectsOfKind(kind, source) {
        return (source || state.catalog).filter(object => kindOf(object) === kind);
    }

    function labelFor(objectOrId) {
        const object = typeof objectOrId === 'string' ? objectById(objectOrId) : objectOrId;
        if (!object) return String(objectOrId || '(missing)') + ' (not listed)';
        const payload = object.payload || {};
        const kind = kindOf(object);
        if (kind === 'dataset') return payload.name || object.id;
        if (kind === 'block') {
            const dataset = objectById(payload.dataset);
            return (payload.name || object.id) + (dataset ? ' · ' + (dataset.payload.name || dataset.id) : '');
        }
        if (kind === 'layout') {
            return (TARGET_LABELS[payload.target] || payload.target || 'Layout') + ' · ' +
                String(payload.columns || '?') + '×' + String(payload.rows || '?');
        }
        if (kind === 'page') return payload.name || object.id;
        if (kind === 'profile') return payload.name || object.id;
        if (kind === 'assignment') {
            const profile = payload.profile ? objectById(payload.profile) : null;
            return (payload.device || object.id) + ' · ' +
                (profile ? (profile.payload.name || profile.id) : 'individual selection');
        }
        return object.id;
    }

    function objectMeta(object) {
        const parts = [
            'v' + String(object.version),
            object.author || 'unknown author',
            object.ready ? 'Ready' : 'Working',
            'published v' + String(object.published_version || 0),
        ];
        if (kindOf(object) === 'dataset') {
            const count = objectsOfKind('block').filter(block => (block.payload || {}).dataset === object.id).length;
            parts.push('shared by ' + String(count) + ' block' + (count === 1 ? '' : 's'));
        }
        return parts.join(' · ');
    }

    function eventLabel(event) {
        if (!event) return '';
        const payload = event.payload || {};
        const title = payload.title || ('Event ' + String(event.id));
        return title + ' · v' + String(event.version);
    }

    function clampInteger(value, minimum, maximum, fallback) {
        const number = Number(value);
        return Number.isInteger(number) && number >= minimum && number <= maximum ? number : fallback;
    }

    function normalizePlacement(value, columns, rows) {
        if (!value || typeof value !== 'object') return null;
        const x = Number(value.x);
        const y = Number(value.y);
        const w = Number(value.w);
        const h = Number(value.h);
        const block = value.block === undefined ? value.blockId : value.block;
        if (!Number.isInteger(x) || !Number.isInteger(y) || !Number.isInteger(w) || !Number.isInteger(h)) return null;
        if (x < 0 || y < 0 || w < 1 || h < 1 || x + w > columns || y + h > rows) return null;
        if (block === undefined || block === null || String(block) === '') return null;
        return { block: String(block), x: x, y: y, w: w, h: h };
    }

    function normalizeGridLayout(value, fallback) {
        const source = value && value.layout && typeof value.layout === 'object' ? value.layout : value;
        if (!source) return null;
        const base = fallback || { columns: 12, rows: 12, placements: [] };
        const columns = clampInteger(source.columns, 1, 24, base.columns || 12);
        const rows = clampInteger(source.rows, 1, 24, base.rows || 12);
        const rawPlacements = Array.isArray(source) ? source : source.placements;
        const placements = [];
        if (Array.isArray(rawPlacements)) {
            for (const item of rawPlacements) {
                const placement = normalizePlacement(item, columns, rows);
                if (!placement) return null;
                placements.push(placement);
            }
        }
        return { columns: columns, rows: rows, placements: placements };
    }

    function layoutSnapshot() {
        const layout = state.layout || { columns: 12, rows: 12, placements: [] };
        return {
            columns: layout.columns,
            rows: layout.rows,
            placements: layout.placements.map(placement => ({
                block: placement.block, x: placement.x, y: placement.y,
                w: placement.w, h: placement.h,
            })),
        };
    }

    function blockLabels() {
        const labels = {};
        for (const block of objectsOfKind('block')) {
            labels[block.id] = labelFor(block) + ' · v' + String(block.version);
        }
        return labels;
    }

    function adaptFallbackToRows(layout) {
        const columns = clampInteger(layout && layout.columns, 1, 24, 12);
        const source = Array.isArray(layout && layout.placements) ? layout.placements.slice() : [];
        source.sort((left, right) => (Number(left.y) - Number(right.y)) || (Number(left.x) - Number(right.x)));
        const placements = [];
        for (const item of source.slice(0, 24)) {
            if (!item || item.block === undefined || item.block === null || String(item.block) === '') continue;
            placements.push({
                block: String(item.block), x: 0, y: placements.length,
                w: columns, h: 1,
            });
        }
        return { columns: columns, rows: Math.max(1, placements.length), placements: placements };
    }

    function resolvePagePreview(layouts, fallback, target) {
        const direct = layoutObject(layouts[target]);
        if (direct) {
            return { layout: normalizeGridLayout(direct.payload, null), source: target, adapted: false };
        }
        const fallbackLayout = layoutObject(layouts[fallback]);
        if (!fallbackLayout) return null;
        return { layout: adaptFallbackToRows(fallbackLayout.payload || {}), source: fallback, adapted: true };
    }

    function layoutObject(id) {
        const object = id ? objectById(id) : null;
        return object && kindOf(object) === 'layout' ? object : null;
    }

    function validatePlacements(placements, columns, rows) {
        if (!Array.isArray(placements)) throw new Error('Placements must be a list.');
        const seen = [];
        for (const placement of placements) {
            if (!placement || typeof placement.block !== 'string' || !placement.block) {
                throw new Error('Every placement needs a block.');
            }
            for (const name of ['x', 'y', 'w', 'h']) {
                if (!Number.isInteger(placement[name])) throw new Error('Placement ' + name + ' must be a whole number.');
            }
            if (placement.x < 0 || placement.y < 0 || placement.w < 1 || placement.h < 1 ||
                    placement.x + placement.w > columns || placement.y + placement.h > rows) {
                throw new Error('Placement ' + placement.block + ' is outside the grid.');
            }
            for (const other of seen) {
                if (placement.x < other.x + other.w && placement.x + placement.w > other.x &&
                        placement.y < other.y + other.h && placement.y + placement.h > other.y) {
                    throw new Error('Placements ' + other.block + ' and ' + placement.block + ' overlap.');
                }
            }
            seen.push(placement);
        }
        return placements;
    }

    function defaults(kind) {
        if (kind === 'dataset') return { schema: 1, name: '', module: 'events', events: [] };
        if (kind === 'block') return { schema: 1, name: '', dataset: '', tags: [], limit: 20, appearance: 'cards' };
        if (kind === 'layout') return { schema: 1, target: 'tv-landscape', columns: 12, rows: 12, placements: [] };
        if (kind === 'page') return { schema: 1, name: '', order: 0, layouts: {}, fallback: '' };
        if (kind === 'profile') return {
            schema: 1, name: '', selection: { pages: [], start_page: '', transition_seconds: 10 },
        };
        if (kind === 'assignment') return {
            schema: 1, device: '', profile: null,
            selection: { pages: [], start_page: '', transition_seconds: 10 },
        };
        throw new Error('Unknown object kind.');
    }

    function option(value, label, selected, disabled) {
        const node = doc.createElement('option');
        node.value = value;
        node.textContent = label;
        node.selected = Boolean(selected);
        if (disabled) node.disabled = true;
        return node;
    }

    function renderCatalog() {
        const host = one('#library-objects');
        if (!host) return;
        host.replaceChildren();
        let shown = 0;
        for (const kind of KINDS) {
            if (kind === 'assignment' && !isAdministrator()) continue;
            const objects = objectsOfKind(kind).sort((left, right) => labelFor(left).localeCompare(labelFor(right)));
            if (!objects.length) continue;
            shown += objects.length;
            const group = doc.createElement('section');
            group.className = 'page-library-object-group';
            const title = doc.createElement('h3');
            title.textContent = KIND_LABELS[kind] + ' (' + String(objects.length) + ')';
            const list = doc.createElement('ul');
            for (const object of objects) {
                const item = doc.createElement('li');
                const button = doc.createElement('button');
                button.type = 'button';
                button.setAttribute('aria-pressed', state.current && state.current.id === object.id ? 'true' : 'false');
                const name = doc.createElement('span');
                name.className = 'page-library-object-name';
                name.textContent = labelFor(object);
                const meta = doc.createElement('span');
                meta.className = 'page-library-object-meta';
                meta.textContent = objectMeta(object);
                button.append(name, meta);
                button.addEventListener('click', () => openObject(object.id));
                item.append(button);
                list.append(item);
            }
            group.append(title, list);
            host.append(group);
        }
        if (!shown) {
            const empty = doc.createElement('p');
            empty.className = 'page-library-hint';
            empty.textContent = 'No page-library objects are listed yet.';
            host.append(empty);
        }
    }

    function renderEventChoices(selectedIds) {
        const host = one('[data-event-choices]');
        if (!host) return;
        host.replaceChildren();
        const selected = new Set((selectedIds || []).map(String));
        const events = state.events.slice();
        const listed = new Set(events.map(event => String(event.id)));
        for (const id of selected) {
            if (!listed.has(id)) events.push({ id: id, version: 0, payload: { title: 'Event ' + id } });
        }
        if (!events.length) {
            const empty = doc.createElement('p');
            empty.className = 'page-library-hint';
            empty.textContent = 'No Events are available. Create an Event before selecting dataset contents.';
            host.append(empty);
            return;
        }
        for (const event of events) {
            const label = doc.createElement('label');
            const input = doc.createElement('input');
            input.type = 'checkbox';
            input.name = 'events';
            input.value = String(event.id);
            input.checked = selected.has(String(event.id));
            const text = doc.createElement('span');
            text.textContent = eventLabel(event) + ' · ID ' + String(event.id);
            label.append(input, text);
            host.append(label);
        }
    }

    function renderDatasetOptions(select, selected) {
        if (!select) return;
        select.replaceChildren();
        const datasets = objectsOfKind('dataset');
        const ids = new Set(datasets.map(dataset => dataset.id));
        if (!datasets.length) {
            select.append(option('', 'No datasets available', false, true));
        }
        for (const dataset of datasets) {
            select.append(option(dataset.id, labelFor(dataset) + ' · v' + String(dataset.version),
                dataset.id === selected));
        }
        if (selected && !ids.has(selected)) {
            select.append(option(selected, labelFor(selected) + ' · missing from list', true));
        }
        if (selected) select.value = selected;
    }

    function updatedBlockDatasetInfo() {
        const node = one('[data-block-dataset-info]');
        const select = one('#block-form [name="dataset"]');
        if (!node || !select) return;
        const dataset = objectById(select.value);
        if (!dataset) {
            node.textContent = 'Choose a shared dataset. Editing a block never deletes its dataset.';
            return;
        }
        const blocks = objectsOfKind('block').filter(block => (block.payload || {}).dataset === dataset.id);
        node.textContent = 'Shared dataset ' + labelFor(dataset) + ' v' + String(dataset.version) +
            ' · ' + String(((dataset.payload || {}).events || []).length) + ' Events · used by ' +
            String(blocks.length) + ' block' + (blocks.length === 1 ? '' : 's') + '.';
    }

    function renderDatasetUsage() {
        const node = one('[data-dataset-usage]');
        if (!node) return;
        if (!state.current || kindOf(state.current) !== 'dataset' || state.current.isNew) {
            node.textContent = 'Shared datasets are reused by blocks. Editing a block or layout never deletes a dataset.';
            return;
        }
        const blocks = objectsOfKind('block').filter(block => (block.payload || {}).dataset === state.current.id);
        if (!blocks.length) {
            node.textContent = 'This dataset is not referenced by any block yet.';
            return;
        }
        node.textContent = 'Shared with ' + String(blocks.length) + ' block' +
            (blocks.length === 1 ? '' : 's') + ': ' + blocks.map(block => labelFor(block)).join(', ');
    }

    function renderPageChoices(container, selectedIds) {
        if (!container) return;
        container.replaceChildren();
        const selected = new Set((selectedIds || []).map(String));
        const pages = objectsOfKind('page');
        const listed = new Set(pages.map(page => page.id));
        const missing = Array.from(selected).filter(id => !listed.has(id));
        if (!pages.length && !missing.length) {
            const empty = doc.createElement('p');
            empty.className = 'page-library-hint';
            empty.textContent = 'No pages are available. Create a page first.';
            container.append(empty);
            return;
        }
        for (const page of pages) {
            const label = doc.createElement('label');
            const input = doc.createElement('input');
            input.type = 'checkbox';
            input.name = 'pages';
            input.value = page.id;
            input.checked = selected.has(page.id);
            const text = doc.createElement('span');
            text.textContent = labelFor(page) + ' · v' + String(page.version);
            label.append(input, text);
            container.append(label);
        }
        for (const id of missing) {
            const label = doc.createElement('label');
            const input = doc.createElement('input');
            input.type = 'checkbox';
            input.name = 'pages';
            input.value = id;
            input.checked = true;
            const text = doc.createElement('span');
            text.textContent = labelFor(id) + ' · missing from list';
            label.append(input, text);
            container.append(label);
        }
    }

    function selectedPageIds(container) {
        return all('input[name="pages"]:checked', container).map(input => input.value);
    }

    function renderPageStartOptions(select, pages, desired) {
        if (!select) return;
        const wanted = desired === undefined ? select.value : desired;
        select.replaceChildren();
        if (!pages.length) {
            select.append(option('', 'Select at least one page', false, true));
            return;
        }
        for (const id of pages) {
            select.append(option(id, labelFor(id) + ' · v' + String((objectById(id) || {}).version || 0), id === wanted));
        }
        select.value = pages.includes(wanted) ? wanted : pages[0];
    }

    function renderLayoutTargetSelects(layouts) {
        for (const select of all('[data-page-layout-target]')) {
            const target = select.dataset.pageLayoutTarget;
            const selected = layouts[target] || '';
            select.replaceChildren(option('', 'None', selected === ''));
            const available = objectsOfKind('layout').filter(layout => (layout.payload || {}).target === target);
            for (const layout of available) {
                select.append(option(layout.id, labelFor(layout) + ' · v' + String(layout.version),
                    layout.id === selected));
            }
            if (selected && !available.some(layout => layout.id === selected)) {
                select.append(option(selected, 'Missing layout ' + selected, true));
            }
            select.value = selected;
        }
    }

    function collectPageLayouts(form) {
        const layouts = {};
        for (const select of all('[data-page-layout-target]', form)) {
            if (select.value) layouts[select.dataset.pageLayoutTarget] = select.value;
        }
        return layouts;
    }

    function renderFallbackOptions(select, layouts, desired) {
        if (!select) return;
        const supplied = TARGETS.filter(target => Boolean(layouts[target]));
        const wanted = desired === undefined ? select.value : desired;
        select.replaceChildren();
        if (!supplied.length) {
            select.append(option('', 'Assign a layout first', false, true));
            return;
        }
        for (const target of supplied) {
            select.append(option(target, TARGET_LABELS[target], target === wanted));
        }
        select.value = supplied.includes(wanted) ? wanted : supplied[0];
    }

    function renderProfileOptions(select, selected) {
        if (!select) return;
        select.replaceChildren(option('', 'Individual page selection', !selected));
        const profiles = objectsOfKind('profile');
        const ids = new Set(profiles.map(profile => profile.id));
        for (const profile of profiles) {
            select.append(option(profile.id, labelFor(profile) + ' · v' + String(profile.version),
                profile.id === selected));
        }
        if (selected && !ids.has(selected)) {
            select.append(option(selected, labelFor(selected) + ' · missing from list', true));
        }
        select.value = selected || '';
    }

    function gridApi() {
        return root.KioskPageGrid && typeof root.KioskPageGrid.mount === 'function' ? root.KioskPageGrid : null;
    }

    function destroyGrid(handle) {
        if (!handle || typeof handle.destroy !== 'function') return;
        try { handle.destroy(); } catch (ignored) { /* A failed teardown must not discard editor state. */ }
    }

    function destroyGrids() {
        destroyGrid(state.grid);
        destroyGrid(state.previewGrid);
        state.grid = null;
        state.previewGrid = null;
    }

    let mountingGrid = false;

    function handleGridChange(value) {
        if (!state.layout || !state.current || kindOf(state.current) !== 'layout') return;
        const layout = normalizeGridLayout(value, state.layout);
        if (!layout) {
            setStatus('The grid returned an invalid placement. The previous layout is preserved.', 'error');
            return;
        }
        state.layout = layout;
        const form = one('#layout-form');
        if (form) {
            field(form, 'columns').value = String(layout.columns);
            field(form, 'rows').value = String(layout.rows);
        }
        renderPlacements();
        if (!mountingGrid) markDirty();
    }

    function mountLayoutGrid() {
        const host = one('#layout-grid');
        destroyGrid(state.grid);
        state.grid = null;
        if (!host) return;
        host.replaceChildren();
        const api = gridApi();
        if (!api) {
            host.textContent = 'The adaptive grid module is unavailable. Placement fields remain editable.';
            return;
        }
        mountingGrid = true;
        try {
            state.grid = api.mount(host, {
                layout: layoutSnapshot(), labels: blockLabels(), onChange: handleGridChange,
            });
        } catch (error) {
            host.textContent = 'The adaptive grid could not be loaded. Placement fields remain editable.';
            setStatus('Grid unavailable: ' + error.message, 'error');
        } finally {
            mountingGrid = false;
        }
    }

    function syncLayoutGrid() {
        if (!state.grid || typeof state.grid.setLayout !== 'function') return;
        try {
            state.grid.setLayout(layoutSnapshot(), blockLabels());
        } catch (error) {
            setStatus('The grid could not be updated: ' + error.message, 'error');
        }
    }

    function renderPlacementBlockOptions(select) {
        if (!select) return;
        select.replaceChildren();
        const blocks = objectsOfKind('block');
        if (!blocks.length) {
            select.append(option('', 'No blocks available', false, true));
            return;
        }
        select.append(option('', 'Choose a block', false, true));
        for (const block of blocks) {
            select.append(option(block.id, labelFor(block) + ' · v' + String(block.version)));
        }
    }

    function updatePlacementFromRow(index, row) {
        const placement = state.layout && state.layout.placements[index];
        if (!placement || !row) return;
        const values = {};
        for (const name of ['x', 'y', 'w', 'h']) {
            const input = one('[data-placement-field="' + name + '"]', row);
            const value = input ? Number(input.value) : NaN;
            if (!Number.isInteger(value)) {
                setStatus('Placement positions and sizes must be whole numbers.', 'error');
                return;
            }
            values[name] = value;
        }
        const next = {
            block: placement.block, x: values.x, y: values.y, w: values.w, h: values.h,
        };
        try {
            validatePlacements([next], state.layout.columns, state.layout.rows);
        } catch (error) {
            setStatus(error.message + ' The previous position is preserved.', 'error');
            return;
        }
        state.layout.placements[index] = next;
        syncLayoutGrid();
        markDirty();
    }

    function renderPlacements() {
        const body = one('[data-layout-placements]');
        if (!body || !state.layout) return;
        body.replaceChildren();
        if (!state.layout.placements.length) {
            const row = doc.createElement('tr');
            const cell = doc.createElement('td');
            cell.colSpan = 6;
            cell.textContent = 'No placements. Add a block from the list above.';
            row.append(cell);
            body.append(row);
            return;
        }
        state.layout.placements.forEach((placement, index) => {
            const row = doc.createElement('tr');
            row.dataset.placementIndex = String(index);
            const blockCell = doc.createElement('td');
            blockCell.textContent = labelFor(placement.block);
            row.append(blockCell);
            for (const name of ['x', 'y', 'w', 'h']) {
                const cell = doc.createElement('td');
                const input = doc.createElement('input');
                input.type = 'number';
                input.step = '1';
                input.min = name === 'w' || name === 'h' ? '1' : '0';
                input.max = name === 'x' || name === 'w' ? String(state.layout.columns) : String(state.layout.rows);
                input.value = String(placement[name]);
                input.dataset.placementField = name;
                input.setAttribute('aria-label', name.toUpperCase() + ' for ' + labelFor(placement.block));
                input.addEventListener('change', () => updatePlacementFromRow(index, row));
                cell.append(input);
                row.append(cell);
            }
            const actionCell = doc.createElement('td');
            const remove = doc.createElement('button');
            remove.type = 'button';
            remove.className = 'page-library-secondary';
            remove.textContent = 'Remove';
            remove.addEventListener('click', () => {
                state.layout.placements.splice(index, 1);
                renderPlacements();
                syncLayoutGrid();
                markDirty();
            });
            actionCell.append(remove);
            row.append(actionCell);
            body.append(row);
        });
    }

    function findFreePlacement(columns, rows, placements) {
        const width = Math.min(6, columns);
        const height = Math.min(6, rows);
        for (let y = 0; y + height <= rows; y += 1) {
            for (let x = 0; x + width <= columns; x += 1) {
                const candidate = { x: x, y: y, w: width, h: height };
                const conflict = placements.some(other =>
                    candidate.x < other.x + other.w && candidate.x + candidate.w > other.x &&
                    candidate.y < other.y + other.h && candidate.y + candidate.h > other.y);
                if (!conflict) return candidate;
            }
        }
        return null;
    }

    function addPlacement() {
        if (!state.layout) return;
        const select = one('#layout-new-block');
        const blockId = select ? select.value : '';
        if (!blockId) {
            setStatus('Choose a block before adding a placement.', 'error');
            return;
        }
        const free = findFreePlacement(state.layout.columns, state.layout.rows, state.layout.placements);
        if (!free) {
            setStatus('No free grid space remains. Resize or remove a placement first.', 'error');
            return;
        }
        state.layout.placements.push({ block: blockId, x: free.x, y: free.y, w: free.w, h: free.h });
        renderPlacements();
        syncLayoutGrid();
        markDirty();
        setStatus('Placement added to the unsaved layout.', 'ok');
    }

    function updateLayoutBounds() {
        const form = one('#layout-form');
        if (!form || !state.layout) return;
        const columns = Number(field(form, 'columns').value);
        const rows = Number(field(form, 'rows').value);
        if (!Number.isInteger(columns) || columns < 1 || columns > 24 ||
                !Number.isInteger(rows) || rows < 1 || rows > 24) {
            setStatus('Columns and rows must be whole numbers from 1 to 24.', 'error');
            return;
        }
        state.layout.columns = columns;
        state.layout.rows = rows;
        renderPlacements();
        syncLayoutGrid();
        markDirty();
    }

    function mountPagePreview() {
        const host = one('#page-preview-grid');
        const note = one('[data-page-preview-note]');
        destroyGrid(state.previewGrid);
        state.previewGrid = null;
        if (!host) return;
        host.replaceChildren();
        const form = one('#page-form');
        const layouts = collectPageLayouts(form);
        const fallback = field(form, 'fallback').value;
        if (!Object.keys(layouts).length) {
            if (note) note.textContent = 'Assign at least one target layout before previewing.';
            host.textContent = 'No layout to preview.';
            return;
        }
        const targetSelect = one('#page-preview-target');
        const target = targetSelect ? targetSelect.value : TARGETS[0];
        const resolved = resolvePagePreview(layouts, fallback, target);
        if (!resolved || !resolved.layout) {
            if (note) note.textContent = 'No usable fallback layout is available.';
            host.textContent = 'No fallback layout to preview.';
            return;
        }
        if (note) {
            note.textContent = resolved.adapted
                ? 'Target ' + TARGET_LABELS[target] + ' has no layout. Using ' +
                    TARGET_LABELS[resolved.source] + ' as ' + String(resolved.layout.placements.length) +
                    ' full-width row' + (resolved.layout.placements.length === 1 ? '' : 's') + '.'
                : 'Using the supplied ' + TARGET_LABELS[target] + ' layout.';
        }
        const api = gridApi();
        if (!api) {
            host.textContent = 'The adaptive grid module is unavailable.';
            return;
        }
        try {
            state.previewGrid = api.mount(host, {
                layout: resolved.layout, labels: blockLabels(), onChange: () => {},
            });
        } catch (error) {
            host.textContent = 'The preview grid could not be loaded.';
            setStatus('Preview unavailable: ' + error.message, 'error');
        }
    }

    function updatePageFallbackAndPreview() {
        const form = one('#page-form');
        if (!form) return;
        const layouts = collectPageLayouts(form);
        renderFallbackOptions(field(form, 'fallback'), layouts);
        mountPagePreview();
    }

    function updateAssignmentMode() {
        const form = one('#assignment-form');
        if (!form) return;
        const selectedProfile = field(form, 'profile').value;
        const individual = one('[data-assignment-individual]', form);
        if (!individual) return;
        individual.hidden = Boolean(selectedProfile);
        for (const input of all('input, select', individual)) input.disabled = Boolean(selectedProfile);
    }

    function updateStartOptionsFor(kind) {
        const form = one('#' + kind + '-form');
        if (!form) return;
        const choices = one('[data-page-choices]', form);
        const start = field(form, 'start_page');
        const pages = selectedPageIds(choices);
        const desired = start ? start.value : '';
        renderPageStartOptions(start, pages, desired);
        if (kind === 'assignment') updateAssignmentMode();
    }

    function populateDataset(form, object) {
        const payload = object.payload || defaults('dataset');
        field(form, 'name').value = payload.name || '';
        field(form, 'module').value = payload.module || 'events';
        renderEventChoices(payload.events || []);
        renderDatasetUsage();
    }

    function populateBlock(form, object) {
        const payload = object.payload || defaults('block');
        field(form, 'name').value = payload.name || '';
        renderDatasetOptions(field(form, 'dataset'), payload.dataset || '');
        field(form, 'tags').value = Array.isArray(payload.tags) ? payload.tags.join(', ') : '';
        field(form, 'limit').value = String(payload.limit === undefined ? 20 : payload.limit);
        field(form, 'appearance').value = payload.appearance === 'list' ? 'list' : 'cards';
        updatedBlockDatasetInfo();
    }

    function storedLayout(payload) {
        const source = payload || defaults('layout');
        const columns = clampInteger(source.columns, 1, 24, 12);
        const rows = clampInteger(source.rows, 1, 24, 12);
        const placements = Array.isArray(source.placements) ? source.placements.map(item => ({
            block: String(item && item.block !== undefined ? item.block : ''),
            x: Number(item && item.x), y: Number(item && item.y),
            w: Number(item && item.w), h: Number(item && item.h),
        })) : [];
        return { columns: columns, rows: rows, placements: placements };
    }

    function populateLayout(form, object) {
        const payload = object.payload || defaults('layout');
        field(form, 'target').value = TARGETS.includes(payload.target) ? payload.target : 'tv-landscape';
        state.layout = storedLayout(payload);
        field(form, 'columns').value = String(state.layout.columns);
        field(form, 'rows').value = String(state.layout.rows);
        renderPlacementBlockOptions(one('#layout-new-block'));
        renderPlacements();
        mountLayoutGrid();
    }

    function populatePage(form, object) {
        const payload = object.payload || defaults('page');
        field(form, 'name').value = payload.name || '';
        field(form, 'order').value = String(payload.order === undefined ? 0 : payload.order);
        const layouts = payload.layouts && typeof payload.layouts === 'object' ? payload.layouts : {};
        renderLayoutTargetSelects(layouts);
        renderFallbackOptions(field(form, 'fallback'), layouts, payload.fallback || '');
        const preview = one('#page-preview-target');
        if (preview) {
            preview.value = TARGETS.find(target => Boolean(layouts[target])) || TARGETS[0];
        }
        mountPagePreview();
    }

    function populateProfile(form, object) {
        const payload = object.payload || defaults('profile');
        const selection = payload.selection || { pages: [], start_page: '', transition_seconds: 10 };
        field(form, 'name').value = payload.name || '';
        const choices = one('[data-page-choices]', form);
        renderPageChoices(choices, selection.pages || []);
        renderPageStartOptions(field(form, 'start_page'), selection.pages || [], selection.start_page || '');
        field(form, 'transition_seconds').value = String(selection.transition_seconds === undefined
            ? 10 : selection.transition_seconds);
    }

    function populateAssignment(form, object) {
        if (!form) return;
        const payload = object.payload || defaults('assignment');
        const selection = payload.selection || { pages: [], start_page: '', transition_seconds: 10 };
        field(form, 'device').value = payload.device || '';
        renderProfileOptions(field(form, 'profile'), payload.profile || '');
        const choices = one('[data-page-choices]', form);
        renderPageChoices(choices, (payload.profile ? [] : selection.pages) || []);
        renderPageStartOptions(field(form, 'start_page'), payload.profile ? [] : (selection.pages || []),
            selection.start_page || '');
        field(form, 'transition_seconds').value = String(selection.transition_seconds === undefined
            ? 10 : selection.transition_seconds);
        updateAssignmentMode();
    }

    function populateForm(kind, object) {
        const form = one('#' + kind + '-form');
        if (!form) throw new Error('The ' + KIND_LABELS[kind] + ' editor is not available.');
        if (kind === 'dataset') populateDataset(form, object);
        else if (kind === 'block') populateBlock(form, object);
        else if (kind === 'layout') populateLayout(form, object);
        else if (kind === 'page') populatePage(form, object);
        else if (kind === 'profile') populateProfile(form, object);
        else if (kind === 'assignment') populateAssignment(form, object);
        field(form, 'id').value = object.id;
        field(form, 'version').value = String(object.version || 0);
    }

    function updateMeta() {
        const node = one('#editor-meta');
        if (!node) return;
        if (!state.current) {
            node.textContent = 'Choose an object or create a new one.';
            return;
        }
        const kind = kindOf(state.current);
        const dependencies = Object.entries(state.current.dependencies || {});
        const dependencyText = dependencies.length
            ? ' · dependencies ' + dependencies.map(entry => entry[0] + '@v' + String(entry[1])).join(', ')
            : ' · no fixed dependencies';
        node.textContent = (KIND_LABELS[kind] || 'Object') + ' · ' + state.current.id +
            ' · v' + String(state.current.version) +
            ' · ' + (state.current.isNew ? 'not yet saved' : (state.current.author || 'unknown author')) +
            ' · ' + (state.current.ready ? 'Ready' : 'Working') +
            ' · published v' + String(state.current.published_version || 0) + dependencyText;
    }

    function updateReadyButtons() {
        const disabled = !state.current || (state.current.version || 0) < 1 ||
            state.dirty || state.saving || state.stale;
        for (const button of all('[data-ready]')) button.disabled = disabled;
    }

    function markDirty() {
        state.dirty = true;
        updateReadyButtons();
    }

    function confirmDiscard() {
        if (state.saving) return false;
        if (!state.dirty) return true;
        if (typeof root.confirm !== 'function') return true;
        return root.confirm('Discard the unsaved fields and grid changes in the current editor?');
    }

    function closeEditor() {
        destroyGrids();
        state.current = null;
        state.dirty = false;
        state.stale = false;
        state.layout = null;
        for (const editor of all('.page-library-editor')) editor.hidden = true;
        updateMeta();
        updateReadyButtons();
        renderCatalog();
    }

    function showEditor(kind, object) {
        destroyGrids();
        for (const editor of all('.page-library-editor')) editor.hidden = true;
        const editor = one('#' + kind + '-editor');
        const form = one('#' + kind + '-form');
        if (!editor || !form) throw new Error('The ' + KIND_LABELS[kind] + ' editor is not available.');
        form.reset();
        loadingForm = true;
        try {
            populateForm(kind, object);
        } finally {
            loadingForm = false;
        }
        editor.hidden = false;
        updateMeta();
        updateReadyButtons();
    }

    function openObject(id, options) {
        const settings = options || {};
        if (!settings.force && !confirmDiscard()) return false;
        const object = objectById(id);
        if (!object) {
            setStatus('Object ' + String(id) + ' is not in the current list. Reload the list explicitly.', 'error');
            return false;
        }
        const kind = kindOf(object);
        if (!kind) {
            setStatus('Object ' + String(id) + ' has an unsupported kind.', 'error');
            return false;
        }
        if ((kind === 'assignment' || kind === 'profile') && !isAdministrator()) {
            setStatus('Profiles and assignments are editable by administrators.', 'error');
            return false;
        }
        state.current = object;
        state.dirty = false;
        state.stale = false;
        try {
            showEditor(kind, object);
        } catch (error) {
            setStatus(error.message, 'error');
            return false;
        }
        renderCatalog();
        setStatus('Loaded ' + KIND_LABELS[kind] + ' v' + String(object.version) + '.', '');
        return true;
    }

    function beginNew(kind) {
        if (!KINDS.includes(kind)) return;
        if ((kind === 'assignment' || kind === 'profile') && !isAdministrator()) {
            setStatus('Profiles and assignments are editable by administrators.', 'error');
            return;
        }
        if (!confirmDiscard()) return;
        let id;
        try {
            id = createId(kind);
        } catch (error) {
            setStatus(error.message, 'error');
            return;
        }
        const object = {
            id: id, version: 0, payload: defaults(kind), dependencies: {},
            author: '', ready: false, published_version: 0, isNew: true,
        };
        state.current = object;
        state.dirty = false;
        state.stale = false;
        try {
            showEditor(kind, object);
        } catch (error) {
            setStatus(error.message, 'error');
            return;
        }
        renderCatalog();
        setStatus('New ' + KIND_LABELS[kind] + ' draft. Save it to add it to the shared library.', '');
    }

    function formText(form, name) {
        const input = field(form, name);
        return input ? String(input.value || '').trim() : '';
    }

    function requiredText(form, name, label) {
        const value = formText(form, name);
        if (!value) throw new Error(label + ' is required.');
        return value;
    }

    function formInteger(form, name, minimum, maximum, label) {
        const input = field(form, name);
        if (!input || String(input.value).trim() === '') throw new Error(label + ' is required.');
        const value = Number(input.value);
        if (!Number.isInteger(value) || value < minimum || value > maximum) {
            throw new Error(label + ' must be a whole number from ' + String(minimum) + ' to ' + String(maximum) + '.');
        }
        return value;
    }

    function readDataset(form) {
        const events = all('input[name="events"]:checked', form).map(input => input.value);
        return {
            schema: 1,
            name: requiredText(form, 'name', 'Dataset name'),
            module: 'events',
            events: events,
        };
    }

    function readBlock(form) {
        const dataset = requiredText(form, 'dataset', 'Dataset');
        if (!objectById(dataset)) throw new Error('Choose a dataset from the current list.');
        const rawTags = formText(form, 'tags');
        const tags = rawTags ? rawTags.split(',').map(tag => tag.trim()).filter(Boolean) : [];
        const appearance = formText(form, 'appearance');
        if (appearance !== 'cards' && appearance !== 'list') throw new Error('Appearance must be cards or list.');
        return {
            schema: 1,
            name: requiredText(form, 'name', 'Block name'),
            dataset: dataset,
            tags: tags,
            limit: formInteger(form, 'limit', 1, 100, 'Limit'),
            appearance: appearance,
        };
    }

    function readLayout(form) {
        const target = formText(form, 'target');
        if (!TARGETS.includes(target)) throw new Error('Choose a supported layout target.');
        const columns = formInteger(form, 'columns', 1, 24, 'Columns');
        const rows = formInteger(form, 'rows', 1, 24, 'Rows');
        if (!state.layout) throw new Error('The layout grid state is unavailable.');
        const placements = state.layout.placements.map(item => ({
            block: String(item.block), x: item.x, y: item.y, w: item.w, h: item.h,
        }));
        validatePlacements(placements, columns, rows);
        return { schema: 1, target: target, columns: columns, rows: rows, placements: placements };
    }

    function readPage(form) {
        const layouts = collectPageLayouts(form);
        const targets = Object.keys(layouts);
        if (!targets.length) throw new Error('Assign at least one layout target to the page.');
        for (const target of targets) {
            const layout = layoutObject(layouts[target]);
            if (!layout) throw new Error('Layout ' + layouts[target] + ' is missing from the current list.');
            if ((layout.payload || {}).target !== target) {
                throw new Error('Layout ' + layouts[target] + ' does not target ' + TARGET_LABELS[target] + '.');
            }
        }
        const fallback = formText(form, 'fallback');
        if (!fallback || !layouts[fallback]) throw new Error('The fallback must be one of the supplied layout targets.');
        return {
            schema: 1,
            name: requiredText(form, 'name', 'Page name'),
            order: formInteger(form, 'order', 0, 10000, 'Order'),
            layouts: layouts,
            fallback: fallback,
        };
    }

    function readSelectionFrom(form) {
        const choices = one('[data-page-choices]', form);
        const pages = selectedPageIds(choices);
        if (!pages.length) throw new Error('Select at least one page.');
        const start = requiredText(form, 'start_page', 'Start page');
        if (!pages.includes(start)) throw new Error('The start page must be one of the selected pages.');
        return {
            pages: pages,
            start_page: start,
            transition_seconds: formInteger(form, 'transition_seconds', 5, 600, 'Transition seconds'),
        };
    }

    function readProfile(form) {
        return {
            schema: 1,
            name: requiredText(form, 'name', 'Profile name'),
            selection: readSelectionFrom(form),
        };
    }

    function readAssignment(form) {
        const device = requiredText(form, 'device', 'Device');
        const profile = formText(form, 'profile');
        if (profile) {
            if (!objectById(profile)) throw new Error('Choose a profile from the current list.');
            return { schema: 1, device: device, profile: profile, selection: null };
        }
        return { schema: 1, device: device, profile: null, selection: readSelectionFrom(form) };
    }

    function readPayload(kind, form) {
        if (kind === 'dataset') return readDataset(form);
        if (kind === 'block') return readBlock(form);
        if (kind === 'layout') return readLayout(form);
        if (kind === 'page') return readPage(form);
        if (kind === 'profile') return readProfile(form);
        if (kind === 'assignment') return readAssignment(form);
        throw new Error('Unknown object kind.');
    }

    function listedVersion(id) {
        const object = objectById(id);
        if (object) return object.version;
        const event = eventById(id);
        return event ? event.version : null;
    }

    function addDependency(dependencies, id, label) {
        const version = listedVersion(id);
        if (version === null) {
            throw new Error(label + ' ' + String(id) + ' is not in the current list. Reload before saving.');
        }
        dependencies[String(id)] = version;
    }

    function dependenciesFor(kind, payload) {
        const dependencies = {};
        if (kind === 'dataset') {
            for (const eventId of payload.events || []) addDependency(dependencies, eventId, 'Event');
        } else if (kind === 'block') {
            addDependency(dependencies, payload.dataset, 'Dataset');
        } else if (kind === 'layout') {
            for (const placement of payload.placements || []) addDependency(dependencies, placement.block, 'Block');
        } else if (kind === 'page') {
            for (const layoutId of Object.values(payload.layouts || {})) addDependency(dependencies, layoutId, 'Layout');
        } else if (kind === 'profile') {
            for (const pageId of (payload.selection || {}).pages || []) addDependency(dependencies, pageId, 'Page');
        } else if (kind === 'assignment') {
            if (payload.profile) addDependency(dependencies, payload.profile, 'Profile');
            else for (const pageId of (payload.selection || {}).pages || []) addDependency(dependencies, pageId, 'Page');
        }
        return dependencies;
    }

    function validateNative(form) {
        if (form && typeof form.reportValidity === 'function') return form.reportValidity();
        return true;
    }

    async function save(kind) {
        const form = one('#' + kind + '-form');
        if (!form || !state.current || state.saving) return false;
        if (!validateNative(form)) return false;
        let payload;
        let dependencies;
        try {
            payload = readPayload(kind, form);
            dependencies = dependenciesFor(kind, payload);
        } catch (error) {
            setStatus(error.message, 'error');
            return false;
        }
        const id = field(form, 'id').value;
        const expected = Number(field(form, 'version').value);
        if (!Number.isInteger(expected) || expected < 0) {
            setStatus('The loaded version is invalid. Reload the object explicitly.', 'error');
            return false;
        }
        state.saving = true;
        form.inert = true;
        updateReadyButtons();
        const submitButtons = all('button[type="submit"]', form);
        for (const button of submitButtons) button.disabled = true;
        try {
            const result = await request(API_OBJECTS + '/' + encodeURIComponent(id), {
                expected_version: expected, payload: payload, dependencies: dependencies,
            });
            if (!result || !Number.isInteger(result.version)) {
                throw requestError('The save response did not include a version.', 200, 'invalid_response');
            }
            state.current.version = result.version;
            state.current.payload = payload;
            state.current.dependencies = dependencies;
            state.current.ready = false;
            state.current.isNew = false;
            field(form, 'version').value = String(result.version);
            state.dirty = false;
            state.stale = false;
            setStatus('Saved draft v' + String(result.version) + '. Displays are unchanged until publication.', 'ok');
            updateMeta();
            updateReadyButtons();
            try {
                await refreshObjects({ preserveCurrent: true });
            } catch (error) {
                setStatus('Saved draft v' + String(result.version) + ', but the list refresh failed: ' + error.message, 'error');
            }
            return true;
        } catch (error) {
            if (error.status === 409) {
                state.stale = true;
                setStatus('Version conflict: the draft changed elsewhere. Unsaved fields and grid are preserved. ' +
                    'Reload listed objects only if you explicitly want to discard them.', 'error');
            } else {
                setStatus('Save refused: ' + error.message, 'error');
            }
            return false;
        } finally {
            state.saving = false;
            form.inert = false;
            for (const button of submitButtons) button.disabled = false;
            updateReadyButtons();
        }
    }

    async function markReady(kind) {
        const form = one('#' + kind + '-form');
        if (!form || !state.current || state.saving) return false;
        if (state.dirty) {
            setStatus('Save the current fields before marking a version ready.', 'error');
            return false;
        }
        const version = Number(field(form, 'version').value);
        if (!Number.isInteger(version) || version < 1) {
            setStatus('Save this object before marking a version ready.', 'error');
            return false;
        }
        const id = field(form, 'id').value;
        state.saving = true;
        updateReadyButtons();
        try {
            await request(API_OBJECTS + '/' + encodeURIComponent(id) + '/ready', { version: version });
            state.current.ready = true;
            const listed = objectById(id);
            if (listed) listed.ready = true;
            state.dirty = false;
            state.stale = false;
            setStatus('Version ' + String(version) + ' is ready for publication review. It is not published.', 'ok');
            updateMeta();
            try {
                await refreshObjects({ preserveCurrent: true });
            } catch (error) {
                setStatus('Version ' + String(version) + ' is ready, but the list refresh failed: ' + error.message, 'error');
            }
            return true;
        } catch (error) {
            if (error.status === 409) {
                state.stale = true;
                setStatus('Readiness conflict: the object changed elsewhere. No editor fields were replaced. ' +
                    'Reload listed objects only if you explicitly want to discard them.', 'error');
            } else {
                setStatus('Readiness refused: ' + error.message, 'error');
            }
            return false;
        } finally {
            state.saving = false;
            updateReadyButtons();
        }
    }

    async function refreshObjects(options) {
        const settings = options || {};
        const eventsPromise = request(EVENTS_API).catch(error => ({ error: error }));
        const library = await request(API_OBJECTS);
        const eventsResult = await eventsPromise;
        if (!library || !Array.isArray(library.objects)) {
            throw requestError('The page library response did not include objects.', 200, 'invalid_response');
        }
        state.catalog = library.objects.filter(object => object && typeof object.id === 'string');
        state.byId = new Map(state.catalog.map(object => [String(object.id), object]));
        const eventsFailed = Boolean(eventsResult && eventsResult.error);
        state.events = !eventsFailed && eventsResult && Array.isArray(eventsResult.objects)
            ? eventsResult.objects.filter(event => event && event.id !== undefined) : [];
        state.eventById = new Map(state.events.map(event => [String(event.id), event]));
        renderCatalog();
        if (settings.preserveCurrent && state.current) {
            const fresh = objectById(state.current.id);
            if (fresh && fresh.version === state.current.version) {
                state.current = fresh;
                updateMeta();
                updateReadyButtons();
            } else if (fresh) {
                state.stale = true;
                updateReadyButtons();
                setStatus('A newer version was saved elsewhere. This form still holds the loaded version.', 'error');
            }
        }
        return { eventsError: eventsFailed ? eventsResult.error : null };
    }

    async function reloadList() {
        if (!confirmDiscard()) return false;
        const currentId = state.current && !state.current.isNew ? state.current.id : null;
        try {
            const result = await refreshObjects();
            state.dirty = false;
            if (currentId && objectById(currentId)) openObject(currentId, { force: true });
            else closeEditor();
            if (result.eventsError) {
                setStatus('Library reloaded, but the Events list is unavailable: ' + result.eventsError.message, 'error');
            } else {
                setStatus('Library reloaded from the server.', 'ok');
            }
            return true;
        } catch (error) {
            setStatus('Library reload failed: ' + error.message + ' No editor fields were discarded.', 'error');
            return false;
        }
    }

    function renderPlanList(host, items, includeReason) {
        if (!host) return;
        host.replaceChildren();
        if (!items.length) {
            const item = doc.createElement('li');
            item.textContent = includeReason ? 'No excluded objects.' : 'No included objects.';
            host.append(item);
            return;
        }
        for (const entry of items) {
            const object = objectById(entry.id);
            const item = doc.createElement('li');
            const kind = kindOf(entry.id);
            item.textContent = (KIND_LABELS[kind] || 'Object') + ' · ' +
                (object ? labelFor(object) + ' · ' : '') + String(entry.id) +
                ' · v' + String(entry.version) + ' · ' + (entry.author || 'unknown author') +
                (includeReason ? ' · ' + String(entry.reason || 'excluded') : '');
            host.append(item);
        }
    }

    async function loadPlan() {
        setPlanStatus('', '');
        const targetForm = one('#target-preview-form');
        const openPreview = one('button', targetForm);
        openPreview.disabled = true;
        try {
            const result = await request(API_PLAN);
            if (!result || !Array.isArray(result.included) || !Array.isArray(result.excluded)) {
                throw requestError('The publication preview response is invalid.', 200, 'invalid_response');
            }
            renderPlanList(one('#plan-included'), result.included, false);
            renderPlanList(one('#plan-excluded'), result.excluded, true);
            if (/^[0-9a-f]{64}$/.test(result.revision_sha256)) {
                field(targetForm, 'revision_sha256').value = result.revision_sha256;
                openPreview.disabled = false;
            }
            setPlanStatus('Read-only preview: ' + String(result.included.length) + ' included, ' +
                String(result.excluded.length) + ' excluded.', 'ok');
            return result;
        } catch (error) {
            renderPlanList(one('#plan-included'), [], false);
            renderPlanList(one('#plan-excluded'), [], true);
            setPlanStatus('Publication preview unavailable: ' + error.message, 'error');
            return null;
        }
    }

    async function loadEventsModule() {
        const path = '/editor/pages/modules/events';
        const indicator = one('#events-module-state');
        const toggle = one('#events-module-toggle');
        try {
            const status = await request(path);
            indicator.textContent = 'Events module: ' + status.state;
            if (!toggle) return;
            toggle.hidden = false;
            toggle.textContent = status.enabled ? 'Disable Events editing' : 'Enable Events editing';
            toggle.onclick = async () => {
                toggle.disabled = true;
                try {
                    await request(path, { expected_version: status.version, enabled: !status.enabled });
                    await loadEventsModule();
                    await loadPlan();
                } catch (error) {
                    setStatus('Module change refused: ' + error.message, 'error');
                } finally {
                    toggle.disabled = false;
                }
            };
        } catch (error) {
            indicator.textContent = 'Events module status unavailable.';
            if (toggle) toggle.hidden = true;
        }
    }

    function handleFormEvent(event) {
        const form = event.currentTarget;
        const target = event.target;
        if (loadingForm || !form || !target || !form.dataset.kind) return;
        const kind = form.dataset.kind;
        if (target.id === 'page-preview-target') {
            mountPagePreview();
            return;
        }
        if (target.id === 'layout-new-block') return;
        if (kind === 'layout' && (target.name === 'columns' || target.name === 'rows')) {
            updateLayoutBounds();
        } else if (kind === 'block' && target.name === 'dataset') {
            updatedBlockDatasetInfo();
        } else if ((kind === 'profile' || kind === 'assignment') && target.name === 'pages') {
            updateStartOptionsFor(kind);
        } else if (kind === 'assignment' && target.name === 'profile') {
            updateAssignmentMode();
        } else if (kind === 'page' && (target.dataset.pageLayoutTarget || target.name === 'fallback')) {
            updatePageFallbackAndPreview();
        }
        markDirty();
    }

    function bindEvents() {
        const reload = one('#library-reload');
        if (reload) reload.addEventListener('click', () => { reloadList(); });
        const plan = one('#plan-reload');
        if (plan) plan.addEventListener('click', () => { loadPlan(); });
        for (const button of all('[data-new-kind]')) {
            button.addEventListener('click', () => beginNew(button.dataset.newKind));
        }
        const add = one('#layout-add-placement');
        if (add) add.addEventListener('click', addPlacement);

        for (const kind of KINDS) {
            const form = one('#' + kind + '-form');
            if (!form) continue;
            form.addEventListener('submit', event => {
                event.preventDefault();
                save(kind);
            });
            form.addEventListener('input', handleFormEvent);
            form.addEventListener('change', handleFormEvent);
            const ready = one('[data-ready]', form);
            if (ready) ready.addEventListener('click', () => { markReady(kind); });
            const close = one('[data-close]', form);
            if (close) close.addEventListener('click', () => {
                if (confirmDiscard()) closeEditor();
            });
        }
    }

    async function init() {
        if (state.initialized) return;
        const panel = one('[data-page-library]');
        if (!panel) return;
        state.initialized = true;
        role = panel.dataset.role || '';
        bindEvents();
        try {
            const result = await refreshObjects();
            if (result.eventsError) {
                setStatus('Page library loaded, but the Events list is unavailable: ' +
                    result.eventsError.message, 'error');
            } else {
                setStatus('Loaded ' + String(state.catalog.length) + ' library objects and ' +
                    String(state.events.length) + ' Events.', '');
            }
        } catch (error) {
            setStatus('Page library load failed: ' + error.message, 'error');
        }
        await Promise.all([loadPlan(), loadEventsModule()]);
    }

    if (doc.readyState === 'loading') {
        doc.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
