let csrf = document.body.dataset.csrf;
const state = {
  drafts: [], settings: null, review: null, user: null, permissions: [], selections: {},
  connection: null, pollTimer: 0,
};

const el = (id) => document.getElementById(id);
const setVisible = (node, visible) => {
  const target = typeof node === 'string' ? el(node) : node;
  if (target) target.classList.toggle('hidden', !visible);
};
const text = (value) => document.createTextNode(String(value == null ? '' : value));

function message(value) {
  const box = el('message');
  box.textContent = value || '';
  box.classList.toggle('hidden', !value);
}

function lines(parent, values) {
  parent.replaceChildren();
  for (const value of values) line(parent, value);
}

function line(parent, value) {
  const item = document.createElement('li');
  item.appendChild(text(value));
  parent.appendChild(item);
  return item;
}

function detail(parent, label, value) {
  const row = document.createElement('p');
  const strong = document.createElement('strong');
  strong.appendChild(text(label + ': '));
  row.appendChild(strong);
  row.appendChild(text(value == null ? '' : value));
  parent.appendChild(row);
  return row;
}

async function api(path, payload, method) {
  const options = {
    method: payload === undefined ? 'GET' : (method || 'POST'),
    credentials: 'same-origin',
    headers: { 'Accept': 'application/json' },
  };
  if (payload !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRF-Token'] = csrf;
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  let value = {};
  try { value = await response.json(); } catch (error) { value = { error: 'invalid_response' }; }
  if (value && typeof value.csrf === 'string') csrf = value.csrf;
  if (!response.ok) throw new Error(value.error || ('http_' + response.status));
  return value;
}

function date(value) {
  return value ? new Date(value * 1000).toLocaleString() : '';
}

function has(permission) {
  return (state.permissions || []).includes(permission);
}

// -- rendering -------------------------------------------------------------

function renderSuspended(suspended) {
  const box = el('suspended');
  box.replaceChildren();
  setVisible('suspended-box', Boolean(suspended && suspended.length));
  for (const item of suspended || []) {
    const row = line(box, `${item.user_id} — suspended, expires ${date(item.expires)}`);
    const button = document.createElement('button');
    button.textContent = 'Return as ' + item.user_id;
    button.addEventListener('click', () => {
      el('return-form').user.value = item.user_id;
      el('return-form').password.focus();
      setVisible('return-form', true);
    });
    row.appendChild(button);
  }
}

function renderMaintenance(data) {
  const box = el('maintenance');
  box.replaceChildren();
  const value = data.maintenance || {};
  detail(box, 'State', value.state || 'unknown');
  if (value.due) detail(box, 'Next due', date(value.due));
  if (value.last_maintenance) detail(box, 'Last recorded', date(value.last_maintenance));
  if (value.warnings && value.warnings.length) {
    detail(box, 'Warnings', value.warnings.map((item) => item.days + 'd').join(', '));
  }
  const authority = data.authority_lifecycle;
  if (authority) {
    if (authority.effective_due) detail(box, 'Earliest known maintenance deadline', date(authority.effective_due));
    for (const item of authority.deadlines || []) {
      detail(box, item.name, `${item.state}: ${date(item.expires)}`);
    }
    if ((authority.unavailable || []).length) detail(box, 'Unavailable local checks', authority.unavailable.join(', '));
    detail(box, 'Coverage', 'Local Maintenance only; remote trust and automatic renewal are not verified here.');
    detail(box, 'Calendar acknowledgement', 'Recording maintenance does not renew certificates or publication permissions.');
  }
  const recovery = data.recovery || {};
  detail(box, 'Recovery', `${recovery.state || 'none'} (generation ${recovery.generation || 0})`);
  setVisible('record-maintenance', has('service.relocate'));
  setVisible('recover-authority-form', has('service.relocate'));
  setVisible('export-authority-request', has('service.relocate'));
  const placement = data.placement || {};
  const box2 = el('relocation');
  box2.replaceChildren();
  detail(box2, 'Mode', placement.mode || 'not configured');
  detail(box2, 'Side', placement.side || '');
  detail(box2, 'Origin', placement.origin || '');
  detail(box2, 'Generation', placement.generation);
  detail(box2, 'Active', placement.active ? 'yes' : 'no');
  detail(box2, 'Handoff completed', placement.handoff ? 'yes' : 'no');
}

function renderSessions(data) {
  const list = el('sessions');
  list.replaceChildren();
  for (const item of data.sessions || []) {
    const label = `${item.user_id} ${item.state}${item.temporary ? ' temporary' : ''} ` +
      `${item.trusted ? 'trusted' : 'untrusted'} last ${date(item.last_contact)}`;
    const row = line(list, label);
    if (item.state !== 'ended') {
      const button = document.createElement('button');
      button.textContent = 'Terminate';
      button.addEventListener('click', async () => {
        try {
          await api('/api/sessions/terminate', { id: item.id });
          message('Session terminated.');
          await refresh();
        } catch (error) { message(error.message); }
      });
      row.appendChild(button);
    }
  }
}

function renderPending(connections) {
  const list = el('pending');
  list.replaceChildren();
  const visible = (connections || []).filter((item) => {
    if (item.approved) return false;
    if (item.kind === 'login') return item.requested_user === (state.user && state.user.id);
    return has('device.enroll');
  });
  setVisible('pending-box', visible.length > 0);
  for (const item of visible) {
    const row = line(list, `${item.kind} request from ${item.summary} — code ${item.code} — ` +
      `expires ${date(item.expires)}`);
    const button = document.createElement('button');
    button.textContent = 'Review';
    button.addEventListener('click', () => reviewConnection(item.code));
    row.appendChild(button);
  }
}

function renderUsers(users) {
  const list = el('users');
  list.replaceChildren();
  for (const user of users) {
    const row = line(list, `${user.id} — ${user.role}${user.blocked ? ' — blocked' : ''}`);
    const block = document.createElement('button');
    block.textContent = user.blocked ? 'Unblock' : 'Block';
    block.addEventListener('click', async () => {
      try {
        await api(user.blocked ? '/api/users/unblock' : '/api/users/block', { user: user.id });
        message(user.blocked ? 'Account unblocked.' : 'Account blocked; drafts and committed publication retained.');
        await refresh();
      } catch (error) { message(error.message); }
    });
    row.appendChild(block);
  }
}

function renderGrants(grants, subject, subjectType) {
  const list = el('grants');
  list.replaceChildren();
  if (!grants.length) line(list, `No grants for ${subjectType} ${subject}.`);
  for (const grant of grants) {
    const row = line(list, `${grant.bundle} in ${grant.groups.join(', ')}`);
    const button = document.createElement('button');
    button.textContent = 'Revoke';
    button.addEventListener('click', async () => {
      try {
        await api('/api/grants/revoke', {
          subject_type: subjectType, subject, bundle: grant.bundle, groups: grant.groups,
        });
        message('Grant revoked.');
        await showGrants(subject, subjectType);
      } catch (error) { message(error.message); }
    });
    row.appendChild(button);
  }
}

async function showGrants(subject, subjectType) {
  const result = await api(`/api/grants?subject=${encodeURIComponent(subject)}` +
    `&subject_type=${encodeURIComponent(subjectType)}`);
  renderGrants(result.grants || [], subject, subjectType);
}

function renderDrafts() {
  const box = el('drafts');
  box.replaceChildren();
  for (const draft of state.drafts) {
    const row = document.createElement('li');
    const label = document.createElement('label');
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = Boolean(state.selections[draft.id]);
    check.disabled = !draft.ready;
    check.addEventListener('change', () => {
      if (check.checked) state.selections[draft.id] = draft.version;
      else delete state.selections[draft.id];
      updateReviewButton();
    });
    label.appendChild(check);
    label.appendChild(text(` ${draft.payload.title || draft.id} — revision ${draft.version} ` +
      `${draft.ready ? 'ready' : 'not ready'}`));
    row.appendChild(label);
    const edit = document.createElement('button');
    edit.textContent = 'Edit';
    edit.addEventListener('click', () => loadDraft(draft));
    row.appendChild(edit);
    box.appendChild(row);
  }
  updateReviewButton();
}

function loadDraft(draft) {
  const form = el('draft-form');
  form.identity.value = draft.id;
  form.title.value = draft.payload.title || '';
  form.short_description.value = draft.payload.short_description || '';
  form.full_description.value = draft.payload.full_description || '';
  form.event_date.value = draft.payload.event_date || '';
  form.place.value = draft.payload.place || '';
  form.sort_order.value = draft.payload.sort_order || 0;
  form.status.value = draft.payload.status || 'hidden';
}

function updateReviewButton() {
  el('review').disabled = Object.keys(state.selections).length === 0 ||
    !has('content.publish');
}

function renderReview(review) {
  const box = el('review-view');
  box.replaceChildren();
  state.review = review;
  detail(box, 'Confirmation', review.confirmation);
  detail(box, 'Package', review.package_id);
  detail(box, 'Revision', review.revision);
  detail(box, 'Policy version', review.policy_version);
  detail(box, 'Signed by', `${review.user_id} (${review.device_id})`);
  detail(box, 'Expires', date(review.expires));
  detail(box, 'Publication SHA-256', review.publication_sha256);
  detail(box, 'Dependencies SHA-256', review.dependencies_sha256);

  const targets = document.createElement('ul');
  for (const target of review.targets) {
    line(targets, `Display ${target.device_id} — profile ${target.profile_id} v` +
      `${target.profile_version} — ${target.mode} mode`);
  }
  detail(box, 'Intended displays', `${review.targets.length}`);
  box.appendChild(targets);

  const settings = document.createElement('dl');
  for (const [name, value] of Object.entries(review.settings || {})) {
    const term = document.createElement('dt');
    term.appendChild(text(name));
    const def = document.createElement('dd');
    def.appendChild(text(value));
    settings.appendChild(term);
    settings.appendChild(def);
  }
  detail(box, 'Settings', '');
  box.appendChild(settings);

  detail(box, 'Events', review.event_count);
  const events = document.createElement('div');
  events.className = 'events';
  for (const event of review.events) {
    const card = document.createElement('article');
    card.className = 'card';
    const title = document.createElement('h3');
    title.appendChild(text(event.title));
    card.appendChild(title);
    detail(card, 'Date', event.event_date);
    detail(card, 'Place', event.place);
    detail(card, 'Status', event.status || 'default');
    detail(card, 'Order', event.sort_order);
    detail(card, 'Short description', event.short_description);
    detail(card, 'Full description', event.full_description);
    detail(card, 'Tags', (event.tags || []).join(', '));
    const media = document.createElement('ul');
    for (const image of event.images || []) line(media, image);
    detail(card, 'Media', (event.images || []).length ? '' : 'none');
    card.appendChild(media);
    events.appendChild(card);
  }
  box.appendChild(events);

  detail(box, 'Package files', (review.package_files || []).length);
  const publish = document.createElement('button');
  publish.textContent = 'Publish exactly this candidate';
  publish.addEventListener('click', async () => {
    publish.disabled = true;
    try {
      const done = await api('/api/publish', { id: state.reviewId, confirm: true });
      if (done.pending) {
        message('The exact candidate is signed and preserved, but distribution needs a retry: ' +
          done.error);
      } else {
        message(`Published generation ${done.distribution.generation}, package ` +
          `${done.distribution.package_id}.`);
      }
      await refresh();
    } catch (error) {
      message(error.message);
      publish.disabled = false;
    }
  });
  box.appendChild(publish);
}

function renderNativeTicket(ticket) {
  const box = el('native-ticket-view');
  box.replaceChildren();
  detail(box, 'Content origin', ticket.content_origin);
  detail(box, 'Maintenance origin', ticket.maintenance_origin);
  detail(box, 'Expires', date(ticket.expires));
  detail(box, 'Handoff', 'The token stays in the link fragment and is never sent to this server.');
  const link = document.createElement('a');
  link.href = ticket.handoff;
  link.rel = 'noopener';
  link.textContent = 'Open native page approval';
  box.appendChild(link);
}

// -- API-driven flows ------------------------------------------------------

let refreshSequence = 0;

async function refresh() {
  const sequence = ++refreshSequence;
  const data = await api('/api/state');
  if (sequence !== refreshSequence) return;
  const placement = data.placement || {};
  el('placement').textContent = placement.mode ?
    `Placement: ${placement.mode}, ${placement.side} side, generation ${placement.generation}` +
    (placement.handoff ? ' (handoff completed)' : '') : 'Placement not configured';
  state.user = data.user || null;
  state.permissions = data.permissions || [];
  renderMaintenance(data);
  renderSuspended(data.suspended);
  if (!data.authenticated) {
    setVisible('login-panel', true);
    setVisible('workspace', false);
    setVisible('lock-panel', false);
    return;
  }
  if (data.state === 'locked') {
    setVisible('login-panel', false);
    setVisible('workspace', false);
    setVisible('lock-panel', true);
    el('resume-form').user.value = data.user.id;
    return;
  }
  setVisible('login-panel', false);
  setVisible('lock-panel', false);
  setVisible('workspace', true);
  setVisible('admin-article', Boolean(data.admin));
  el('who').textContent = `${data.user.id} (${data.user.role})`;
  el('trust').textContent = data.trusted ?
    'Trusted session: exact review, Publish and retained enrollment are available.' :
    'Temporary session: publish and retained enrollment need approval from a trusted session.';
  el('rights').textContent = 'Permissions: ' + (state.permissions.join(', ') || 'none') +
    ' — groups: ' + ((data.groups || []).join(', ') || 'none') +
    ' — terminal admin scope: ' + ((data.admin_scope || []).join(', ') || 'none');
  renderSessions(data);
  renderPending(data.connections);
  if (data.admin) {
    const users = await api('/api/users');
    renderUsers(users.users);
    const teams = await api('/api/teams');
    const box = el('teams');
    box.replaceChildren();
    for (const team of teams.teams) line(box, `${team.id} — ${team.name}`);
    const terminals = await api('/api/terminals');
    const list = el('terminals');
    list.replaceChildren();
    for (const item of terminals.terminals) {
      line(list, `${item.name || item.id} — ${item.approved ? 'approved' : 'pending'}` +
        `${item.retained ? ' retained' : ''} — policy ${item.id}`);
    }
    el('terminal-form').users.value = data.user.id;
    el('terminal-form').groups.value = (data.admin_scope || []).join(',');
  }
  updateReviewButton();
}

async function loadDrafts() {
  const result = await api('/api/drafts');
  state.drafts = result.objects || [];
  state.settings = result.settings || null;
  state.selections = {};
  for (const draft of state.drafts) if (draft.ready) state.selections[draft.id] = draft.version;
  renderDrafts();
  if (state.settings) {
    const form = el('settings-form');
    for (const name of ['site_title', 'tv_slide_duration', 'kiosk_heading', 'kiosk_label',
      'kiosk_description']) {
      if (form[name]) form[name].value = state.settings[name] || '';
    }
  }
  return result;
}

function reviewConnection(code) {
  api('/api/connection/review', { code }).then((result) => {
    const box = el('connection-review');
    box.replaceChildren();
    const item = result.connection;
    detail(box, 'Request', `${item.kind} — ${item.summary}`);
    detail(box, 'Requesting terminal', item.terminal);
    if (item.requested_user) detail(box, 'Requested account', item.requested_user);
    if (item.target_user) detail(box, 'Target account', item.target_user);
    detail(box, 'Origin', item.origin);
    detail(box, 'Code', item.code);
    detail(box, 'Expires', date(item.expires));
    if (item.document) {
      if (item.document.name) detail(box, 'Terminal name', item.document.name);
      detail(box, 'Allowed accounts', (item.document.users || []).join(', ') || 'requested account');
      detail(box, 'Groups', (item.document.groups || []).join(', ') || 'none');
      if ((item.document.targets || []).length) {
        detail(box, 'Display targets', item.document.targets.join(', '));
      }
    }
    const approve = document.createElement('button');
    approve.textContent = 'Approve this exact request';
    approve.addEventListener('click', async () => {
      approve.disabled = true;
      try {
        const done = await api('/api/connection/approve', { code: item.code });
        message(done.kind === 'device' ? 'Device enrolled with signed scope.' :
          'Request approved once.');
        await refresh();
      } catch (error) {
        message(error.message);
        approve.disabled = false;
      }
    });
    const reject = document.createElement('button');
    reject.textContent = 'Reject';
    reject.addEventListener('click', async () => {
      try {
        await api('/api/connection/reject', { code: item.code });
        message('Request rejected.');
        await refresh();
      } catch (error) { message(error.message); }
    });
    box.appendChild(approve);
    box.appendChild(reject);
  }).catch((error) => message(error.message));
}

function startConnection(kind, document) {
  return api('/api/connection/start', {
    kind, summary: navigator.userAgent.slice(0, 100),
    requested_user: kind === 'login' && state.user ? state.user.id : '',
    target_user: kind === 'login' ? '' : (state.user ? state.user.id : ''),
    document,
  });
}

function showConnection(result, note) {
  const box = el('connection');
  box.replaceChildren();
  const img = document.createElement('img');
  img.src = result.qr;
  img.alt = 'Connection QR';
  box.appendChild(img);
  detail(box, 'Manual code', result.code);
  detail(box, 'Expires', date(result.expires));
  detail(box, note, '');
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const value = await api('/api/connection/poll', { code: result.code });
      if (value.state === 'accepted' || value.state === 'approved') {
        clearInterval(state.pollTimer);
        await refresh();
        message(value.state === 'accepted' ? 'This browser is now connected.' :
          'Device request approved.');
      }
    } catch (error) {
      clearInterval(state.pollTimer);
      message(error.message);
    }
  }, 2000);
}

// -- event wiring ----------------------------------------------------------

el('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/login', { user: form.get('user'), password: form.get('password') });
    message('');
    await refresh();
  } catch (error) { message(error.message); }
});

el('return-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/resume', { user: form.get('user'), password: form.get('password') });
    message('Workspace resumed with the account password.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('resume-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/resume', { user: form.get('user'), password: form.get('password') });
    message('Workspace unlocked.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('lock').addEventListener('click', async () => {
  try {
    await api('/api/lock', {});
    message('Workspace locked; content is hidden until the password is entered.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('switch').addEventListener('click', async () => {
  try {
    await api('/api/suspend', {});
    window.location.reload();
  } catch (error) { message(error.message); }
});

el('lock-switch').addEventListener('click', async () => {
  try {
    await api('/api/suspend', {});
    window.location.reload();
  } catch (error) { message(error.message); }
});

el('lock-logout').addEventListener('click', async () => {
  try {
    await api('/api/logout', {});
    window.location.reload();
  } catch (error) { message(error.message); }
});

el('logout').addEventListener('click', async () => {
  try {
    await api('/api/logout', {});
    window.location.reload();
  } catch (error) { message(error.message); }
});

el('terminate-all').addEventListener('click', async () => {
  try {
    await api('/api/sessions/terminate-terminal', {});
    window.location.reload();
  } catch (error) { message(error.message); }
});

el('rotate').addEventListener('click', async () => {
  try {
    await api('/api/rotate', {});
    message('Session secret rotated; old copies of this cookie no longer work.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('start-login').addEventListener('click', async () => {
  try {
    const result = await startConnection('login');
    showConnection(result, 'Ask a trusted session of this account to approve this code.');
  } catch (error) { message(error.message); }
});

el('review-connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  reviewConnection(String(form.get('code') || '').trim().toUpperCase());
});

el('load-drafts').addEventListener('click', async () => {
  try {
    await loadDrafts();
    message('Drafts loaded; ready revisions are selected for review.');
  } catch (error) { message(error.message); }
});

el('draft-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const values = new FormData(form);
  const identity = String(values.get('identity'));
  const draft = state.drafts.find((item) => item.id === identity);
  try {
    const result = await api('/api/draft', {
      identity, expected_version: draft ? draft.version : 0,
      dependencies: draft ? draft.dependencies : {},
      payload: {
        title: values.get('title'), short_description: values.get('short_description') || '',
        full_description: values.get('full_description') || '',
        event_date: values.get('event_date') || '', place: values.get('place') || '',
        sort_order: Number(values.get('sort_order') || 0), status: values.get('status') || 'hidden',
        images: draft ? (draft.payload.images || []) : [],
        tags: draft ? (draft.payload.tags || []) : [],
      },
    });
    await api('/api/draft/ready', { identity, version: result.version_number });
    message('Draft saved and marked ready as revision ' + result.version_number + '.');
    await loadDrafts();
  } catch (error) { message(error.message); }
});

el('settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = new FormData(event.target);
  try {
    const payload = {};
    for (const name of ['site_title', 'tv_slide_duration', 'kiosk_heading', 'kiosk_label',
      'kiosk_description']) payload[name] = values.get(name) || '';
    const expected = state.settings ? Number(state.settings.version || 0) : 0;
    const result = await api('/api/settings', { expected_version: expected, values: payload });
    state.settings = Object.assign({}, state.settings, payload, { version: result.version_number });
    message('Settings saved as revision ' + result.version_number + '.');
  } catch (error) { message(error.message); }
});

el('review').addEventListener('click', async () => {
  try {
    const selected = {};
    for (const draft of state.drafts) {
      if (state.selections[draft.id]) selected[draft.id] = state.selections[draft.id];
    }
    const result = await api('/api/review', { selected, parents: [] });
    message('Exact frozen candidate reviewed. Publish signs only this candidate.');
    state.reviewId = result.id;
    renderReview(result.review);
  } catch (error) { message(error.message); }
});

el('page-native-ticket').addEventListener('click', async () => {
  if (!has('content.publish')) {
    message('Publishing pages requires the content.publish permission.');
    return;
  }
  try {
    const result = await api('/api/page/native-ticket', { parents: [] });
    renderNativeTicket(result);
    message('Native handoff prepared. Open it in the trusted Windows or Android publisher.');
  } catch (error) { message(error.message); }
});

el('record-maintenance').addEventListener('click', async () => {
  try {
    const result = await api('/api/maintenance/record', { confirm: true });
    message('Calendar acknowledgement recorded; next calendar due ' + date(result.maintenance.due) + '. Authority deadlines are unchanged.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('recover-authority-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const file = form.elements.package.files[0];
    if (!file || file.size > 131072) throw new Error('Select a public recovery package up to 128 KiB.');
    const bundle = JSON.parse(await file.text());
    const result = await api('/api/maintenance/authority', {
      user: state.user.id, chain: bundle.chain, policy: bundle.policy,
      ...(bundle.lan ? {lan: bundle.lan} : {}),
      root_pin: form.elements.root_pin.value.trim(), confirm: form.elements.confirm.checked
    });
    form.reset();
    message('Existing Maintenance key recovered; policy ' + result.recovered.policy_version +
      (result.delivery_pending ? '. Content delivery pending; retry this import when the service is available.' : '.'));
    await refresh();
  } catch (error) { message(error.message); }
});

el('export-authority-request').addEventListener('click', async () => {
  try {
    const value = await api('/api/maintenance/authority/request');
    const {version, ...bundle} = value;
    const url = URL.createObjectURL(new Blob([JSON.stringify(bundle)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'maintenance-recovery-request.json';
    link.click();
    URL.revokeObjectURL(url);
    message('Public request exported; compare its device fingerprint with the offline administrator. Request expires in 90 seconds.');
  } catch (error) { message(error.message); }
});

el('refresh-state').addEventListener('click', () => refresh().catch((error) => message(error.message)));

el('grant-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const subject = String(form.get('subject'));
  const subjectType = String(form.get('subject_type'));
  try {
    await api('/api/grants', {
      subject_type: subjectType, subject,
      bundle: form.get('bundle'),
      groups: String(form.get('groups')).split(',').map((item) => item.trim()).filter(Boolean),
    });
    message('Grant assigned.');
    await showGrants(subject, subjectType);
  } catch (error) { message(error.message); }
});

el('grant-view-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await showGrants(String(form.get('subject')), String(form.get('subject_type')));
  } catch (error) { message(error.message); }
});

el('user-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/users', {
      user: form.get('user'), password: form.get('password'), role: form.get('role'),
    });
    message('Account created.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('team-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/teams', { team: form.get('team'), name: form.get('name') });
    message('Team created.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('membership-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const remove = event.submitter && event.submitter.id === 'membership-remove';
  try {
    await api(remove ? '/api/memberships/remove' : '/api/memberships', {
      team: form.get('team'), user: form.get('user'),
    });
    message(remove ? 'Member removed.' : 'Member added.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('terminal-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('/api/terminal/approve', {
      name: form.get('name'),
      users: String(form.get('users')).split(',').map((item) => item.trim()).filter(Boolean),
      groups: String(form.get('groups')).split(',').map((item) => item.trim()).filter(Boolean),
    });
    message('This terminal is now retained for the listed accounts.');
    await refresh();
  } catch (error) { message(error.message); }
});

el('enroll-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const user = String(form.get('user')).trim();
  try {
    const result = await api('/api/connection/start', {
      kind: 'device', summary: 'enroll ' + user, target_user: user,
      document: {
        name: 'Signing device for ' + user,
        groups: String(form.get('groups')).split(',').map((item) => item.trim()).filter(Boolean),
        targets: String(form.get('targets')).split(',').map((item) => item.trim()).filter(Boolean),
        permissions: ['publish'], role: form.get('role'),
      },
    });
    const box = el('enroll-review');
    box.replaceChildren();
    detail(box, 'Enrollment request', user);
    detail(box, 'Code', result.code);
    const button = document.createElement('button');
    button.textContent = 'Approve enrollment for ' + user;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await api('/api/connection/approve', { code: result.code });
        message('Signing device enrolled with signed scope for ' + user + '.');
        await refresh();
      } catch (error) { message(error.message); button.disabled = false; }
    });
    box.appendChild(button);
  } catch (error) { message(error.message); }
});

refresh().catch((error) => message(error.message));
document.body.dataset.scriptReady = '1';
