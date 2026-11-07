(() => {
 if(window.__pc2Clock) return true;
 const set=window.setTimeout.bind(window),clear=window.clearTimeout.bind(window),timers=new Map();let id=-1000000,fires=0;
 const clock={kind:'TEST ONLY: explicit saved reading-timer callback driver, not real elapsed playback',pending:()=>Array.from(timers.entries()).map(([id,t])=>({id,delay:t.delay})),tick(){if(timers.size!==1)throw Error('expected exactly one reading timer: '+timers.size);const [key,t]=timers.entries().next().value;timers.delete(key);fires++;t.fn(...t.args);return fires;},fires:()=>fires,simulateHidden(value){Object.defineProperty(document,'hidden',{configurable:true,get:()=>value});document.dispatchEvent(new Event('visibilitychange'));},restoreNativeHidden(){delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));}};
 window.setTimeout=(fn,delay,...args)=>{if(typeof fn==='function'&&delay>=8000&&delay<=24000){const key=--id;timers.set(key,{fn,args,delay});return key;}return set(fn,delay,...args);};
 window.clearTimeout=key=>{if(!timers.delete(key))clear(key);};window.__pc2Clock=clock;
 // Retire the already armed real reading timer through the renderer's own resize listener.
 window.dispatchEvent(new Event('resize'));return true;
})()
