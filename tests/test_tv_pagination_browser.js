"use strict";
// Real Chrome layout with controlled reading timers; no npm/browser-driver dependency.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");
const {spawn} = require("node:child_process");
const {setTimeout: sleep} = require("node:timers/promises");
const root = path.resolve(process.argv[2]);
const evidence = path.resolve(process.argv[3]);
fs.mkdirSync(evidence, {recursive: true});
const preparations = JSON.parse(fs.readFileSync(path.join(root, "preparations.json")));
const chromePath = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "kiosk-tv-pagination-"));
const results = [];
let chrome, socket, server;
let browserExit;
(async () => {
    server = http.createServer((request, response) => {
        const file = path.resolve(root, "." + decodeURIComponent(new URL(request.url, "http://localhost").pathname));
        if (!file.startsWith(root + path.sep)) { response.writeHead(403).end(); return; }
        fs.readFile(file, (error, bytes) => {
            if (error) { response.writeHead(404).end(); return; }
            const types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json"};
            response.setHeader("Content-Type", types[path.extname(file)] || "application/octet-stream");
            response.end(bytes);
        });
    });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", "--no-first-run",
        "--no-default-browser-check", `--user-data-dir=${profile}`, "about:blank"], {windowsHide: true, stdio: "ignore"});
    browserExit = new Promise(resolve => chrome.once("exit", resolve));
    const portFile = path.join(profile, "DevToolsActivePort");
    let port;
    for (let tries = 0; tries < 100; tries++) {
        try { port = fs.readFileSync(portFile, "utf8").split("\n")[0]; } catch (error) {
            if (!["ENOENT", "EBUSY", "EACCES"].includes(error.code)) throw error;
        }
        if (port) break;
        await sleep(100);
    }
    assert.ok(port, "Chrome did not publish a debugging port");
    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    fs.writeFileSync(path.join(evidence, "browser.json"), JSON.stringify(version, null, 2));
    const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let sequence = 0;
    const pending = new Map();
    socket.onmessage = ({data}) => {
        const message = JSON.parse(data);
        if (message.id && pending.has(message.id)) {
            const call = pending.get(message.id); pending.delete(message.id);
            clearTimeout(call.timeout);
            message.error ? call.reject(new Error(JSON.stringify(message.error))) : call.resolve(message.result);
        }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++sequence;
        const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 10000);
        pending.set(id, {resolve, reject, timeout}); socket.send(JSON.stringify({id, method, params}));
    });
    const evaluate = async expression => {
        const result = await send("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
        assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
        return result.result.value;
    };
    await send("Page.enable");
    await send("Page.addScriptToEvaluateOnNewDocument", {source: `
        window.__readingTimers = new Map(); window.__wallTimerEvents = []; let serial = -1;
        const original = window.setTimeout.bind(window), clear = window.clearTimeout.bind(window);
        window.setTimeout = (fn, ms, ...args) => {
            if (ms >= 8000 && location.search.includes('wall-clock=1')) {
                const started = performance.now();
                return original(() => { __wallTimerEvents.push({ms, elapsed:performance.now()-started}); fn(...args); }, ms);
            }
            if (ms >= 8000) { const id = serial--; __readingTimers.set(id, {fn: () => fn(...args), ms}); return id; }
            return original(fn, ms, ...args);
        };
        window.clearTimeout = id => { __readingTimers.delete(id); clear(id); };
        window.__advancePart = () => {
            const entry = __readingTimers.entries().next().value;
            if (!entry) return false;
            __readingTimers.delete(entry[0]); entry[1].fn(); return true;
        };
    `});
    const snapshot = `(() => {
        const card = document.getElementById('card'), content = card.querySelector('.tv-text');
        const context = card.querySelector('.tv-context');
        const image = card.querySelector('.event-image,.image-placeholder');
        const rect = image && image.getBoundingClientRect();
        const data = JSON.parse(document.getElementById('bootstrap').textContent).data;
        return {layout:card.getAttribute('data-tv-layout'), counter:document.getElementById('counter').textContent,
            part:card.querySelector('.tv-part')?.textContent, text:content?.textContent, context:context?.textContent,
            fits:!content || content.scrollHeight <= content.clientHeight+1 && content.scrollWidth <= content.clientWidth+1,
            viewport:[innerWidth,innerHeight], document:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],
            image:rect && [rect.x,rect.y,rect.width,rect.height], timers:[...__readingTimers.values()].map(x=>x.ms),
            source:data.events[0], settings:data.settings};
    })()`;
    for (const [width, height] of [[914,363], [411,866], [1920,1080]]) {
        await send("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile: false});
        for (const name of Object.keys(preparations)) {
            const report = preparations[name].report;
            const relative = `${name}/${report.views.tv.path}/index.html`;
            await send("Page.navigate", {url: `http://127.0.0.1:${server.address().port}/${relative}`});
            for (let tries = 0; tries < 100; tries++) {
                if (await evaluate("document.readyState === 'complete' && !!document.querySelector('.tv-copy,.empty')")) break;
                await sleep(50);
            }
            const first = await evaluate(snapshot);
            assert.ok(first.fits, `${name}/${width} first page overflow`);
            assert.ok(first.document[0] <= width+1 && first.document[1] <= height+1, `${name}/${width} document overflow`);
            const pages = [];
            if (first.layout === "paginated") {
                const expected = first.context === undefined
                    ? [first.source.event_date || 'Date to be announced', first.source.title,
                        first.source.short_description || first.source.full_description || 'No description available',
                        first.source.place || 'Place to be announced'].join('')
                    : first.source.short_description || first.source.full_description;
                let state = first;
                for (let guard = 0; guard < 300; guard++) {
                    assert.ok(state.fits, `${name}/${width} part overflow`);
                    assert.deepEqual(state.image, first.image, 'image moved during pagination');
                    assert.equal(state.counter, first.counter, 'event changed before all text was shown');
                    assert.equal(state.timers.length, 1);
                    assert.ok(state.timers[0] >= 8000 && state.timers[0] <= 24000);
                    pages.push(state.text);
                    if (pages.join('') === expected) break;
                    assert.ok(expected.startsWith(pages.join('')), 'text lost/reordered');
                    assert.equal(await evaluate('__advancePart()'), true);
                    state = await evaluate(snapshot);
                }
                assert.equal(pages.join(''), expected, `${name}/${width} text not fully traversed`);
                await evaluate('__advancePart()');
                const next = await evaluate(snapshot);
                if (name === 'two-events') assert.equal(next.counter, '2 / 2');
                else assert.equal(next.part, 'Part 1', 'single event must repeat from first part');
            } else if (name === 'empty' || name === 'control') assert.equal(first.timers.length, 0);
            const capture = await send('Page.captureScreenshot', {format:'png'});
            fs.writeFileSync(path.join(evidence, `${name}-${width}x${height}.png`), Buffer.from(capture.data, 'base64'));
            results.push({name,width,height,layout:first.layout,parts:pages.length,first});
        }
    }
    // Real resize reflows from part1; hidden documents must not retain a reading timer.
    const relative = `long-text-tags/${preparations['long-text-tags'].report.views.tv.path}/index.html`;
    await send('Page.navigate', {url:`http://127.0.0.1:${server.address().port}/${relative}`});
    await sleep(150);
    await evaluate('__advancePart()');
    await send('Emulation.setDeviceMetricsOverride', {width:500,height:700,deviceScaleFactor:1,mobile:false});
    await sleep(250);
    assert.equal((await evaluate(snapshot)).part, 'Part 1');
    await evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))");
    assert.equal(await evaluate('__readingTimers.size'), 0);
    await evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))");
    assert.equal(await evaluate('__readingTimers.size'), 1);
    // One actual reading interval, without accelerated/manual timer callbacks.
    await send('Page.navigate', {url:`http://127.0.0.1:${server.address().port}/${relative}?wall-clock=1`});
    let wall = [];
    for (let tries=0; tries<280; tries++) {
        wall = await evaluate('window.__wallTimerEvents || []');
        if (wall.length) break;
        await sleep(100);
    }
    assert.ok(wall.length > 0, 'real reading timer never fired');
    assert.ok(wall[0].elapsed >= wall[0].ms-50 && wall[0].elapsed < wall[0].ms+2000);
    assert.equal((await evaluate(snapshot)).part, 'Part 2');
    fs.writeFileSync(path.join(evidence,'wall-clock.json'),JSON.stringify(wall,null,2));
    fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(results,null,2));
    console.log(`PASS ${results.length} real Chrome layout cases; lossless parts, last-part ordering, timer bounds, resize and visibility. Timers advanced by test driver; not wall-clock timing acceptance.`);
})().catch(error => { console.error(error); process.exitCode=1; }).finally(async () => {
    if (socket) socket.close();
    if (chrome) { chrome.kill(); await Promise.race([browserExit,sleep(5000)]); }
    if (server) await new Promise(resolve=>server.close(resolve));
    // Chrome owns this unique temporary profile; retained if Windows still holds files.
    assert.equal(path.dirname(profile), path.resolve(os.tmpdir()));
    assert.ok(path.basename(profile).startsWith("kiosk-tv-pagination-"));
    try { fs.rmSync(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100}); } catch {}
});
