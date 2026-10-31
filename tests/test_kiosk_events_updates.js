const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('kiosk/static/js/kiosk_events.js', 'utf8');
function fixture() {
    const timers = new Map();
    let counter = 0, offline = true, version = 1, malformed = false, hung = false;
    let requests = [], applied = [], delayed = [];
    const context = vm.createContext({
        AbortController,
        window: {
            setTimeout(callback, delay) { timers.set(++counter, {callback, delay}); return counter; },
            clearTimeout(id) { timers.delete(id); },
        },
        fetch: async url => {
            requests.push(url);
            if (offline) throw Error('offline');
            return {ok: true, json: () => hung ? new Promise(resolve => delayed.push({url, resolve})) : Promise.resolve(
                url === '/api/version' ? {content_version: version} : url === '/api/events'
                    ? {events: malformed ? [{}] : [{id: 1, title: 'Card', tags: []}]} : {tags: []})};
        },
        applyEventsData(v, e) { applied.push(e); vm.runInContext(`currentContentVersion = ${v.content_version}`, context); },
        randomUpdateDelay: () => 0, labels: {versionLabel: 'Version'}, contentVersion: {},
    });
    vm.runInContext('let currentContentVersion = null; let updatePending = false; ' + source.slice(source.indexOf('let loadInProgress'), source.indexOf('previousButton.addEventListener')), context);
    const run = code => vm.runInContext(code, context);
    async function settle() { for (let i=0;i<80;i++) await Promise.resolve(); }
    return {run, requests, applied, timers, settle,
        async releaseDelayed(oldVersion) {
            for (const {url, resolve} of delayed.splice(0)) resolve(url === '/api/version'
                ? {content_version: oldVersion} : url === '/api/events'
                    ? {events: [{id: 99, title: 'Stale card', tags: []}]} : {tags: []});
            await settle();
        },
        set(options) { if ('offline' in options) offline=options.offline; if ('version' in options) version=options.version; if ('malformed' in options) malformed=options.malformed; if ('hung' in options) hung=options.hung; },
        async advance(delay) { for (const [id,t] of [...timers]) if(t.delay===delay) {timers.delete(id);t.callback();} await settle(); },
    };
}
(async () => {
    const f=fixture();
    await assert.rejects(f.run('loadKioskEventsPage()'));
    await assert.rejects(f.run('pollKioskVersion()'));
    f.set({offline:false});
    await f.run('pollKioskVersion()');
    await f.run('pollKioskVersion()');
    assert.equal([...f.timers.values()].filter(t=>t.delay===0).length,1);
    await f.advance(0);
    assert.equal(f.applied.length,1);
    assert.equal(f.run('currentContentVersion'),1);
    f.set({version:2,malformed:true});
    await assert.rejects(f.run('loadKioskEventsPage()'));
    assert.equal(f.applied.length,1);
    f.set({malformed:false});
    await f.run('loadKioskEventsPage()');
    assert.equal(f.run('currentContentVersion'),2);
    f.set({version:1});
    await assert.rejects(f.run('loadKioskEventsPage()'));
    assert.equal(f.run('currentContentVersion'),2);
    f.set({version:3,hung:true});
    const pending=f.run('loadKioskEventsPage()');
    const rejected=assert.rejects(pending,/timed out/);
    await f.settle();
    const count=f.requests.length;
    await f.run('pollKioskVersion()');
    await f.run('loadKioskEventsPage()');
    assert.equal(f.requests.length,count);
    await f.advance(10000);
    await rejected;
    f.set({hung:false});
    await f.run('loadKioskEventsPage()');
    assert.equal(f.run('currentContentVersion'),3);
    assert.equal(f.timers.size,0);
    const appliedBeforeLateReply=f.applied.length;
    await f.releaseDelayed(1);
    assert.equal(f.applied.length,appliedBeforeLateReply);
    assert.equal(f.run('currentContentVersion'),3);
    f.set({version:4});
    await f.run('pollKioskVersion()');
    await f.advance(0);
    assert.equal(f.run('currentContentVersion'),4);
    assert.equal(f.applied.length,appliedBeforeLateReply+1);
    assert.equal(f.timers.size,0);
    console.log('PASS: kiosk failure recovery, queued retry guard, validation, stale generation, body deadline, late replies after timeout and ordinary subsequent polling');
})().catch(error=>{console.error(error);process.exitCode=1;});
