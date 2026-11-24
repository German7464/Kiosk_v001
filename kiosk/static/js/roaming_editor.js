'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let csrf = document.body.dataset.csrf, loaded = null, poll = null;
  const notice = message => { $('notice').textContent = message; };
  async function api(path, value) {
    const options = {credentials:'same-origin', cache:'no-store'};
    if (value !== undefined) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(value)});
    const response = await fetch('/editor'+path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Operation refused');
    return result;
  }
  const run = action => async event => { if (event) event.preventDefault(); try { await action(); } catch (error) { notice(error.message); } };
  if ($('login')) $('login').onclick = run(async () => {
    clearTimeout(poll);
    const result = await api('/login/start', {});
    $('qr').src=result.qr; $('qr').hidden=false;
    $('context').textContent=result.context.origin+' — Login — confirmation '+result.confirmation;
    $('login-link').href='kiosk://roaming/login#origin='+encodeURIComponent(result.context.origin)
      +'&token='+encodeURIComponent(result.token);
    $('login-link').hidden=false;
    const check=async () => {
      try {
        const state=await api('/login/poll',{token:result.token});
        if (state.state==='accepted') { location.reload(); return; }
        poll=setTimeout(check,2000);
      } catch(error) { $('qr').hidden=true;notice(error.message+'; create a new QR.'); }
    };
    poll=setTimeout(check,2000);
  });
  function load(object) {
    loaded=object;
    $('identity').value=object.id; $('version').value=object.version;
    for(const name of ['title','short_description','full_description','event_date','place','sort_order']) $(name).value=object.payload[name];
    $('visibility').value=object.payload.status;
  }
  async function refresh() {
    const result=await api('/objects'); $('objects').replaceChildren();
    for(const object of result.objects) {
      const row=document.createElement('p'), button=document.createElement('button');
      button.textContent=object.id+' v'+object.version+' — '+object.author+' — '+(object.ready?'Ready':'In progress')+' — published v'+object.published_version;
      button.onclick=()=>load(object); row.append(button); $('objects').append(row);
    }
  }
  if ($('refresh')) {
    $('refresh').onclick=run(refresh); run(refresh)();
    $('event-form').onsubmit=run(async () => {
      const identity=$('identity').value;
      const payload={};
      for(const name of ['title','short_description','full_description','event_date','place']) payload[name]=$(name).value;
      payload.sort_order=Number($('sort_order').value);payload.status=$('visibility').value;
      payload.images=loaded?.id===identity?loaded.payload.images:[];
      payload.tags=loaded?.id===identity?loaded.payload.tags:[];
      const result=await api('/objects/'+encodeURIComponent(identity),{expected_version:Number($('version').value),payload,dependencies:loaded?.id===identity?loaded.dependencies:{}});
      $('version').value=result.version;notice('Draft saved. Displays unchanged.');await refresh();
    });
    $('ready').onclick=run(async () => {
      await api('/objects/'+encodeURIComponent($('identity').value)+'/ready',{version:Number($('version').value)});
      notice('Exact version marked ready; not published.');await refresh();
    });
    $('logout').onclick=run(async () => {await api('/logout',{});location.reload();});
    $('sessions').onclick=run(async () => {
      const result=await api('/sessions');$('session-list').replaceChildren();
      for(const item of result.sessions) {
        const button=document.createElement('button');
        button.textContent='Session '+item.id.slice(0,8)+' — '+new Date(item.issued*1000).toISOString()+(item.revoked?' — ended':' — terminate');
        button.disabled=!!item.revoked;
        button.onclick=run(async () => {await api('/sessions/terminate',{id:item.id});button.disabled=true;notice('Session terminated.');});
        $('session-list').append(button);
      }
    });
    let settings=null;
    const loadSettings=async()=>{
      settings=await api('/native/settings');
      for(const name of ['site_title','interface_language','tv_slide_duration','kiosk_heading'])
        $(name).value=settings.values[name]||'';
      $('settings_version').value=settings.version;
    };
    if ($('settings-form')) {
      run(loadSettings)();
      $('settings-form').onsubmit=run(async event => {
        event.preventDefault();
        const values={};
        for(const name of ['site_title','interface_language','tv_slide_duration','kiosk_heading'])
          if ($(name).value!=='') values[name]=$(name).value;
        const result=await api('/native/settings',{expected_version:Number($('settings_version').value),values});
        $('settings_version').value=result.version;notice('Display settings saved as draft defaults.');
      });
    }
    if ($('targets')) {
      let eligibleTargets=[];
      $('targets').onclick=run(async()=>{
        const result=await api('/native/targets');$('target-list').replaceChildren();
        eligibleTargets=result.targets||[];
        for(const target of eligibleTargets){
          const row=document.createElement('p');
          row.textContent=target.device_id+' - '+target.profile_id+' v'+target.profile_version
            +' - '+target.mode+' (included)';
          $('target-list').append(row);
        }
        if(!eligibleTargets.length)notice('No eligible display; enroll displays first.');
      });
      let parents=[], activeCandidate=null, pollStatus=null;
      const watch=async id=>{
        activeCandidate=id; clearTimeout(pollStatus);
        const check=async()=>{
          if(activeCandidate!==id)return;
          try{
            const state=await api('/native/candidates/'+id+'/status');
            if(state.distribution){
              $('distribution').textContent='Signed and distributed — generation '+state.distribution.generation
                +', '+state.distribution.targets+' approved display(s).';
              $('retry').hidden=true;
              return;
            }
            if(state.approved){
              $('distribution').textContent='Signed approval stored; distribution pending. Retry or wait for the displays.';
              $('retry').hidden=false;
            } else {
              $('distribution').textContent='Waiting for explicit Publish in an authorized native app.';
              $('retry').hidden=true;
            }
          }catch(error){$('distribution').textContent=error.message;}
          pollStatus=setTimeout(check,3000);
        };
        check();
      };
      $('retry').onclick=run(async()=>{
        if(!activeCandidate)return;
        await api('/native/distribute',{id:activeCandidate});
        notice('Distribution retried.'); watch(activeCandidate);
      });
      $('prepare').onclick=run(async()=>{
        const objects=(await api('/objects')).objects.filter(item=>item.ready);
        if(!objects.length)return notice('No ready draft revision.');
        const selected={};for(const item of objects) selected[item.id]=item.version;
        if(!eligibleTargets.length)return notice('Load the eligible displays first.');
        const targets=eligibleTargets;
        const result=await api('/native/prepare',{selected,targets,parents});
        parents=[result.id];
        $('candidate').textContent='Candidate '+result.confirmation+' — revision '+result.revision
          +' — package '+result.package_id.slice(0,12)+'… — confirmation '+result.id.slice(0,8).toUpperCase();
        $('candidate-link').href=result.link;$('candidate-link').hidden=false;
        $('candidate-qr').src=result.qr;$('candidate-qr').hidden=false;
        notice('Prepared. Sign it in your authorized app; no administrator step is needed.');
        watch(result.id);
      });
    }
  }
})();
