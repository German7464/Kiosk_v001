(() => {
 const payload='<img src=x onerror="window.__pc2Injected=1"><script>window.__pc2Injected=1</script> literal';
 const d=document.implementation.createHTMLDocument('detached test only');
 for(const [id,tag] of [['card','article'],['home','section'],['events','section'],['inactivity','aside'],['counter','span'],['previous','button'],['next','button'],['tags','nav'],['heading','h1'],['version','span'],['home-button','button'],['open-events','button'],['home-label','p'],['home-heading','h2'],['home-description','p']]){let n=d.createElement(tag);n.id=id;d.body.appendChild(n);}
 d.getElementById('home').hidden=true;
 const fakeWindow={clearTimeout(){},clearInterval(){},setTimeout(){return 0;},setInterval(){return 0;},addEventListener(){}};
 mountEventsView(d,fakeWindow,{data:{events:[{id:1,title:payload,short_description:payload,full_description:'unused',place:payload,tag_ids:[]}],tags:[],settings:{},content_version:1},labels:{},media:{},mode:'kiosk'});
 const textSafe=['.event-title','.event-description','.event-place'].every(s=>d.querySelector(s).textContent===payload&&d.querySelector(s).childElementCount===0)&&d.querySelectorAll('img,script,iframe').length===0;
 const value='Start \uD83D\uDC69\u200D\uD83D\uDD2C e\u0301 words remain exact. '+payload+' LongUnbrokenWordLongUnbrokenWord \u0422\u0435\u043A\u0441\u0442 END';
 const container=document.createElement('div'),pager=createEventsTextPager([{tag:'p',className:'sample',value}],(tag,cls)=>{let n=document.createElement(tag);n.className=cls;return n;},()=>container.textContent.length<=31);
 const boundaries=new Set([0,value.length]);if(typeof Intl.Segmenter==='function')for(const s of new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(value))boundaries.add(s.index+s.segment.length);
 let combined='',parts=[],safe=true;for(let i=0;i<100&&pager.more();i++){let result=pager.next(container);if(!result.progressed){safe=false;break;}let piece=container.textContent;combined+=piece;parts.push(piece);safe=safe&&container.querySelector('p').childElementCount===0&&!/[\uD800-\uDBFF]$/.test(piece)&&(typeof Intl.Segmenter!=='function'||boundaries.has(combined.length));}
 return JSON.stringify({kind:'AUXILIARY shared mount/pager in detached DOM, synthetic code-unit capacity31; not stored fixture or attached-layout conformance',pass:textSafe&&safe&&combined===value&&!pager.more(),textNodeProtection:textSafe,graphemeBoundaries:safe,exactConcatenation:combined===value,parts,executedMarkup:window.__pc2Injected===1});
})()
