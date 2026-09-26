/* Abiotic Factor Field Checklist - user interface.
   Needs assets/data.js (window.AF_DATA) and assets/store.js (window.AFStore) loaded first. */
(function () {
  'use strict';

  const DATA = window.AF_DATA;
  const $ = (sel) => document.querySelector(sel);
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const pct = (done, total) => (total ? Math.floor((done / total) * 100) : 0);

  const els = {
    items: $('#items'),
    head: $('#head'),
    nav: $('#nav'),
    overall: $('#overall'),
    chips: $('#chips'),
    banner: $('#banner'),
    profileSelect: $('#profile-select'),
    q: $('#q'),
    optAll: $('#opt-all'),
    optHide: $('#opt-hide'),
    optSpoilers: $('#opt-spoilers'),
    spoilersWrap: $('#opt-spoilers-wrap'),
    live: $('#live'),
    toast: $('#toast'),
    meta: $('#data-meta'),
    dlgProfiles: $('#dlg-profiles'),
    dlgBackup: $('#dlg-backup'),
    dlgConfirm: $('#dlg-confirm'),
    dlgAbout: $('#dlg-about'),
    download: $('#lnk-download'),
    importFile: $('#import-file'),
  };

  if (!DATA || !Array.isArray(DATA.categories) || !DATA.categories.length || !window.AFStore) {
    els.items.innerHTML =
      '<div class="empty"><span class="empty__title">No checklist data found</span>' +
      'Run <code>python tools\\build_data.py</code> in the project folder, then reload this page.</div>';
    return;
  }

  // ------------------------------------------------------------------ data indexes

  const CATS = DATA.categories;
  const catById = new Map(CATS.map((c) => [c.id, c]));
  const itemById = new Map();
  const sectionTitles = new Map();
  CATS.forEach((cat) => {
    cat.items.forEach((item, index) => itemById.set(item.id, { item, cat, index }));
    (cat.sections || []).forEach((s) => sectionTitles.set(cat.id + ':' + s.id, s.title));
  });

  const parser = new DOMParser();
  const htmlText = (html) => (html ? parser.parseFromString(html, 'text/html').body.textContent || '' : '');
  const norm = (s) =>
    String(s || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[\u2018\u2019]/g, "'")
      .toLowerCase();

  // Search text per item. Achievement descriptions are kept apart so redacted
  // (spoiler-protected) entries can't be found through their hidden text.
  const searchBase = new Map();
  const searchSpoiler = new Map();
  CATS.forEach((cat) => {
    cat.items.forEach((it) => {
      const base = [
        it.name,
        sectionTitles.get(cat.id + ':' + it.section),
        it.piece,
        it.type,
        it.trophy,
        it.area,
        ...(it.bonusesHtml || []).map(htmlText),
        ...(it.detailsHtml || []).map(htmlText),
        ...(it.communityHtml || []).map(htmlText),
        ...(it.locationsHtml || []).map(htmlText),
        ...(it.lines || []).map((l) => htmlText(l.html)),
        ...(it.stats || []).map((s) => s.label + ' ' + s.value),
        cat.kind === 'achievement' ? '' : htmlText(it.descHtml), // achievement texts stay spoiler-protected
      ];
      searchBase.set(it.id, norm(base.filter(Boolean).join(' | ')));
      if (cat.kind === 'achievement') {
        const spoiler = [it.descHtml, it.reqHtml, ...(it.notesHtml || [])].map(htmlText);
        searchSpoiler.set(it.id, norm(spoiler.join(' | ')));
      }
    });
  });

  const store = window.AFStore.open();
  const state = {
    cat: null,
    q: '',
    terms: [],
    revealed: new Set(), // hidden achievements revealed during this session
    counts: null,
  };
  let uid = 0;

  // ------------------------------------------------------------------ helpers

  const currentCat = () => catById.get(state.cat);
  const searchAllActive = () => store.prefs.searchAll && state.terms.length > 0;

  function isRedacted(it) {
    return !!it.hidden && !store.prefs.showSpoilers && !store.isChecked(it.id) && !state.revealed.has(it.id);
  }

  function matches(it) {
    if (!state.terms.length) return true;
    const text = searchBase.get(it.id) + (isRedacted(it) ? '' : ' | ' + (searchSpoiler.get(it.id) || ''));
    return state.terms.every((t) => text.includes(t));
  }

  function activeChip(cat) {
    const tag = store.prefs.chips[cat.id] || '';
    return (cat.chips || []).some((c) => c.tag === tag) ? tag : '';
  }

  function visibleItems(cat, chip) {
    return cat.items.filter((it) => {
      if (chip && !(it.tags || []).includes(chip)) return false;
      if (store.prefs.hideCompleted && store.isChecked(it.id)) return false;
      return matches(it);
    });
  }

  function barHTML(done, total, cls, label) {
    const complete = total > 0 && done === total;
    const width = total ? (done / total) * 100 : 0;
    return (
      `<div class="bar ${cls || ''}${complete ? ' is-complete' : ''}" role="progressbar" aria-label="${esc(label)}" ` +
      `aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${done}"><span style="width:${width}%"></span></div>`
    );
  }

  function announce(msg) {
    els.live.textContent = '';
    setTimeout(() => { els.live.textContent = msg; }, 30);
  }

  let toastTimer = null;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 3500);
  }

  // ------------------------------------------------------------------ sidebar

  function renderProfileSelect() {
    const sel = els.profileSelect;
    sel.textContent = '';
    for (const p of store.profiles()) {
      sel.add(new Option(p.name, p.id, false, p.id === store.prefs.activeProfileId));
    }
  }

  function renderOverall() {
    const c = state.counts;
    els.overall.classList.toggle('is-complete', c.total > 0 && c.done === c.total);
    els.overall.innerHTML = `
      <div class="eyebrow">Overall progress</div>
      <div class="overall__nums">
        <span class="overall__done">${c.done}</span><span class="overall__total">/ ${c.total}</span>
        <span class="overall__pct">${pct(c.done, c.total)}%</span>
      </div>
      ${barHTML(c.done, c.total, 'bar--lg', 'Overall progress')}
      <div class="overall__sub"><span><b>${c.done}</b> done</span><span><b>${c.total - c.done}</b> open</span></div>`;
  }

  function renderNav() {
    els.nav.innerHTML = CATS.map((cat) => {
      const c = state.counts.byCat[cat.id];
      const complete = c.total > 0 && c.done === c.total;
      const current = cat.id === state.cat ? ' aria-current="page"' : '';
      return `<li><a class="nav__item${complete ? ' is-complete' : ''}" href="#/${esc(cat.id)}"${current}>
        <span class="nav__code" aria-hidden="true">${esc(cat.code)}</span>
        <span class="nav__body">
          <span class="nav__title">${esc(cat.title)}</span>
          ${barHTML(c.done, c.total, 'bar--sm', cat.title + ' progress')}
          <span class="nav__foot">
            <span class="nav__open">${complete ? 'Complete' : c.total - c.done + ' open'}</span>
            <span class="nav__count"><b>${c.done}</b>/${c.total}</span>
          </span>
        </span></a></li>`;
    }).join('');
  }

  /** GitHub repository of this checklist: from <html data-repo>, or guessed on *.github.io. */
  function repoInfo() {
    let repo = (document.documentElement.dataset.repo || '').trim();
    if (!repo && /\.github\.io$/i.test(location.hostname)) {
      const first = location.pathname.split('/').filter(Boolean)[0];
      if (first && !/\.html?$/i.test(first)) repo = location.hostname.split('.')[0] + '/' + first;
    }
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) return null;
    const url = 'https://github.com/' + repo;
    return { url, zip: url + '/archive/refs/heads/main.zip' };
  }

  function renderMeta() {
    const built = (DATA.generatedAt || '').slice(0, 10);
    els.meta.textContent = built ? `Data built ${built}` : '';
    const repo = repoInfo();
    if (repo) {
      els.download.href = repo.zip;
      els.download.title = 'Download the checklist as a ZIP file (unzip, then open index.html)';
      els.download.hidden = false;
    }
  }

  function renderBanner() {
    const msgs = store.warnings.slice();
    if (!store.persistent) {
      msgs.unshift('This browser blocks local storage for this page, so progress is NOT saved when you close it. ' +
        'Use "Backup & restore" to export it before closing.');
    }
    els.banner.hidden = !msgs.length;
    els.banner.innerHTML = msgs.map((m) => `<p>${esc(m)}</p>`).join('');
  }

  // ------------------------------------------------------------------ header, toolbar, chips

  function renderHead() {
    if (searchAllActive()) {
      let matchCount = 0;
      let catCount = 0;
      CATS.forEach((cat) => {
        const n = visibleItems(cat, '').length;
        matchCount += n;
        if (n) catCount++;
      });
      els.head.classList.remove('is-complete');
      els.head.innerHTML = `
        <div class="head__stripe" aria-hidden="true"></div>
        <div class="head__top">
          <div><div class="eyebrow">Search &middot; all categories</div>
            <h1 class="head__title">&ldquo;${esc(state.q.trim())}&rdquo;</h1></div>
          <div class="head__stats">
            <div class="stat"><span class="stat__num">${matchCount}</span><span class="stat__label">Matches</span></div>
            <div class="stat"><span class="stat__num">${catCount}</span><span class="stat__label">Categories</span></div>
          </div>
        </div>`;
      return;
    }
    const cat = currentCat();
    const c = state.counts.byCat[cat.id];
    const complete = c.total > 0 && c.done === c.total;
    const links = [{ label: 'Wiki page', url: cat.wikiUrl }].concat(cat.links || []);
    const excluded = (DATA.excluded || []).filter((e) => e.category === cat.id);
    els.head.classList.toggle('is-complete', complete);
    els.head.innerHTML = `
      <div class="head__stripe" aria-hidden="true"></div>
      <div class="head__top">
        <div><div class="eyebrow">Category ${esc(cat.code)} &middot; ${c.total} entries</div>
          <h1 class="head__title">${esc(cat.title)}</h1></div>
        <div class="head__stats">
          <div class="stat"><span class="stat__num">${c.done}</span><span class="stat__label">Done</span></div>
          <div class="stat"><span class="stat__num">${c.total - c.done}</span><span class="stat__label">Open</span></div>
          <div class="stat"><span class="stat__num">${pct(c.done, c.total)}%</span><span class="stat__label">Complete</span></div>
        </div>
      </div>
      ${barHTML(c.done, c.total, 'bar--lg', cat.title + ' progress')}
      ${cat.introHtml ? `<p class="head__intro">${cat.introHtml}</p>` : ''}
      ${cat.noteHtml ? `<p class="head__notice">${cat.noteHtml}</p>` : ''}
      <p class="head__links">
        ${links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} &#8599;</a>`).join('')}
        ${excluded.map((e) => `<span class="head__note">Not listed: ${esc(e.name)} &ndash; ${esc(e.reason)}.</span>`).join('')}
      </p>`;
  }

  function renderToolbar() {
    const cat = currentCat();
    els.optHide.checked = store.prefs.hideCompleted;
    els.optAll.checked = store.prefs.searchAll;
    els.optSpoilers.checked = store.prefs.showSpoilers;
    els.spoilersWrap.hidden = !(cat.kind === 'achievement' || store.prefs.searchAll);
    els.q.placeholder = store.prefs.searchAll ? 'Search all categories  ( / )' : `Search ${cat.title}  ( / )`;
  }

  function renderChips() {
    const cat = currentCat();
    if (searchAllActive() || !(cat.chips || []).length) {
      els.chips.hidden = true;
      els.chips.innerHTML = '';
      return;
    }
    const active = activeChip(cat);
    const c = state.counts.byCat[cat.id];
    const chip = (tag, label, n) =>
      `<button type="button" class="chip" data-chip="${esc(tag)}" aria-pressed="${active === tag}">` +
      `${esc(label)}<span class="chip__count">${n.done}/${n.total}</span></button>`;
    els.chips.hidden = false;
    els.chips.innerHTML =
      chip('', 'All', c) + cat.chips.map((ch) => chip(ch.tag, ch.label, c.byTag[ch.tag] || { done: 0, total: 0 })).join('');
  }

  // ------------------------------------------------------------------ items

  function imgHTML(it, cls) {
    const src = it.img || it.imgRemote;
    const fallback = it.img && it.imgRemote ? ` data-fallback="${esc(it.imgRemote)}"` : '';
    const img = src ? `<img src="${esc(src)}"${fallback} alt="" loading="lazy" decoding="async">` : '';
    return `<span class="${cls} imgbox">${img}</span>`;
  }

  function badge(text, mod, title) {
    return `<span class="badge badge--${esc(mod)}"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}</span>`;
  }

  function swatchBadge(it) {
    return `<span class="badge badge--swatch"><span class="swatch" style="--swatch:${esc(it.swatch)}"></span>${esc(it.color)}</span>`;
  }

  function badgesHTML(cat, it) {
    const b = [];
    if (cat.kind === 'achievement') {
      if (it.hidden) b.push(badge('Hidden', 'hidden', 'Hidden achievement - its details stay secret until unlocked.'));
      if (it.type === 'Unskippable') b.push(badge('Unskippable', 'unskippable', 'Unlocked through required story progress.'));
      else if (it.type) b.push(badge(it.type, 'skippable', 'Can be missed - you have to go for it.'));
      if (it.trophy) b.push(badge(it.trophy, 'tier-' + it.trophy.toLowerCase(), 'Trophy tier on consoles - a hint at the difficulty.'));
    } else if (cat.kind === 'armor') {
      if (it.tier) b.push(badge(`Tier ${it.tier}/${it.tierCount}`, 'upgrade', 'Upgrade tier within this line (Enhancement Bench).'));
      else b.push(badge('Non-upgradable', 'plain'));
    } else if (cat.kind === 'tv') {
      b.push(badge('CH ' + String(itemById.get(it.id).index + 1).padStart(2, '0'), 'chan'));
    } else if (cat.kind === 'mask') {
      if (it.swatch) b.push(swatchBadge(it));
      if ((it.tags || []).includes('unique')) b.push(badge('Unique', 'unique', 'Only found at specific spots - and not every time.'));
      else b.push(badge('Common', 'plain', 'Found in many places across the facility.'));
    } else if (cat.kind === 'variant') {
      if (it.swatch) b.push(swatchBadge(it));
      if ((it.tags || []).includes('seed-only')) b.push(badge('Seed only', 'plain', 'Can only be grown from its seed.'));
      else b.push(badge('Found in the world', 'unique', 'Also grows somewhere in the world - see Where.'));
    }
    return b.length ? `<span class="badges">${b.join('')}</span>` : '';
  }

  function redactedHTML(it) {
    const width = (html) => Math.max(28, Math.min(96, Math.round(htmlText(html).length * 0.9)));
    const bars = [it.descHtml, it.reqHtml].filter(Boolean)
      .map((h) => `<span class="redacted__bar" style="width:${width(h)}%"></span>`).join('');
    return `<button type="button" class="redacted" data-reveal="${esc(it.id)}" aria-label="Reveal the details of ${esc(it.name)}">` +
      `${bars}<span class="redacted__hint">Classified &middot; click to reveal</span></button>`;
  }

  function detailsHTML(cat, it) {
    if (cat.kind === 'achievement') {
      if (isRedacted(it)) return redactedHTML(it);
      return (
        (it.descHtml ? `<p class="desc">${it.descHtml}</p>` : '') +
        (it.reqHtml ? `<p><span class="label">How</span>${it.reqHtml}</p>` : '') +
        (it.notesHtml || []).map((n) => `<p class="note"><span class="label">Note</span>${n}</p>`).join('')
      );
    }
    if (cat.kind === 'armor') {
      const bonuses = (it.bonusesHtml || []).length
        ? `<ul class="bonuses">${it.bonusesHtml.map((b) => `<li>${b}</li>`).join('')}</ul>`
        : '<p class="muted">No set bonus.</p>';
      return (
        '<div class="stats">' +
        `<span class="kv"><span>Armor</span><b>${esc(it.armor)}</b></span>` +
        `<span class="kv"><span>Weight</span><b>${esc(it.weight)}</b></span>` +
        (it.piece ? `<span class="kv"><span>Chest piece</span><b>${esc(it.piece)}</b></span>` : '') +
        '</div>' + bonuses
      );
    }
    if (cat.kind === 'tv') return (it.detailsHtml || []).map((d) => `<p>${d}</p>`).join('');
    if (cat.kind === 'variant') {
      return (
        (it.descHtml ? `<p class="desc">${it.descHtml}</p>` : '') +
        (it.detailsHtml || []).map((d) => `<p><span class="label">How</span>${d}</p>`).join('') +
        (it.locationsHtml || []).map((d) => `<p><span class="label">Where</span>${d}</p>`).join('')
      );
    }
    if (cat.kind === 'gear' || cat.kind === 'fish') {
      const stats = (it.stats || []).length
        ? '<div class="stats">' + it.stats.map((s) => `<span class="kv"><span>${esc(s.label)}</span><b>${esc(s.value)}</b></span>`).join('') + '</div>'
        : '';
      const lines = (it.lines || []).map((l) => `<p><span class="label">${esc(l.label)}</span>${l.html}</p>`).join('');
      return stats + (it.descHtml ? `<p class="desc">${it.descHtml}</p>` : '') + lines;
    }
    if (cat.kind === 'mask') {
      const wiki = (it.detailsHtml || []).map((d) => `<p><span class="label">Wiki</span>${d}</p>`);
      const community = (it.communityHtml || []).map((d) => `<p><span class="label label--community">Guide</span>${d}</p>`);
      return wiki.concat(community).join('') || '<p class="muted">No location known yet.</p>';
    }
    return '';
  }

  function wikiLink(it, cls, text) {
    if (!it.wiki) return '';
    return `<a class="${cls}" href="${esc(it.wiki)}" target="_blank" rel="noopener noreferrer" ` +
      `title="Open on the wiki" aria-label="${esc(it.name)} on the wiki">${text}</a>`;
  }

  function tileHTML(cat, it) {
    const done = store.isChecked(it.id);
    const id = 'chk' + ++uid;
    return `<li class="tile${done ? ' is-done' : ''}" data-id="${esc(it.id)}">
      <input type="checkbox" class="check" id="${id}" data-id="${esc(it.id)}"${done ? ' checked' : ''}>
      <label class="tile__label" for="${id}">${imgHTML(it, 'tile__img')}
        <span class="tile__name" title="${esc(it.name)}">${esc(it.name)}</span></label>
      <span class="stamp" aria-hidden="true">${esc(cat.doneLabel)}</span>
      ${wikiLink(it, 'tile__wiki', '&#8599;')}
    </li>`;
  }

  function rowHTML(cat, it) {
    const done = store.isChecked(it.id);
    const id = 'chk' + ++uid;
    return `<li class="row row--${esc(cat.kind)}${done ? ' is-done' : ''}" data-id="${esc(it.id)}">
      <input type="checkbox" class="check" id="${id}" data-id="${esc(it.id)}"${done ? ' checked' : ''}>
      <label class="row__icon" for="${id}">${imgHTML(it, 'row__img')}</label>
      <div class="row__content">
        <div class="row__head"><label class="row__name" for="${id}">${esc(it.name)}</label>${badgesHTML(cat, it)}</div>
        <div class="row__details">${detailsHTML(cat, it)}</div>
      </div>
      <div class="row__side">
        <span class="stamp" aria-hidden="true">${esc(cat.doneLabel)}</span>
        ${wikiLink(it, 'row__wiki', 'Wiki &#8599;')}
      </div>
    </li>`;
  }

  function listHTML(cat, items) {
    if (cat.view === 'grid') {
      return `<ul class="grid" style="--tile-aspect:${esc(cat.tileAspect || '1 / 1')}">` +
        items.map((it) => tileHTML(cat, it)).join('') + '</ul>';
    }
    return '<ul class="list">' + items.map((it) => rowHTML(cat, it)).join('') + '</ul>';
  }

  function sectionHTML(cat, section, items) {
    const sc = state.counts.byCat[cat.id].bySection[section.id] || { done: 0, total: 0 };
    let eyebrow = '';
    if (cat.kind === 'armor' && items.some((it) => it.tier)) eyebrow = 'Upgrade line';
    else if (cat.kind === 'mask') eyebrow = 'Area';
    return `<section class="section">
      <h2 class="section__head">${eyebrow ? `<span class="section__eyebrow">${eyebrow}</span>` : ''}
        <span class="section__title">${esc(section.title)}</span>
        <span class="section__count" data-sec="${esc(cat.id + ':' + section.id)}">${sc.done}/${sc.total}</span></h2>
      ${listHTML(cat, items)}
    </section>`;
  }

  function emptyHTML(title, text, complete) {
    return `<div class="empty${complete ? ' is-complete' : ''}"><span class="empty__title">${esc(title)}</span>${esc(text)}</div>`;
  }

  function renderItems() {
    if (searchAllActive()) {
      const groups = CATS.map((cat) => {
        const list = visibleItems(cat, '');
        if (!list.length) return '';
        return `<section class="group">
          <h2 class="group__head"><span class="group__title"><a href="#/${esc(cat.id)}" data-leave-search>${esc(cat.title)}</a></span>
            <span class="group__count">${list.length} match${list.length === 1 ? '' : 'es'}</span></h2>
          ${listHTML(cat, list)}
        </section>`;
      }).join('');
      els.items.innerHTML = groups ||
        emptyHTML('No matches', `Nothing in any category matches "${state.q.trim()}".`);
      return;
    }

    const cat = currentCat();
    const c = state.counts.byCat[cat.id];
    const list = visibleItems(cat, activeChip(cat));
    if (!list.length) {
      if (state.terms.length) {
        els.items.innerHTML = emptyHTML('No matches', `Nothing in ${cat.title} matches "${state.q.trim()}".`);
      } else if (c.total > 0 && c.done === c.total) {
        els.items.innerHTML = emptyHTML('Category complete',
          `All ${c.total} entries are done. Turn off "Hide completed" to see them again.`, true);
      } else {
        els.items.innerHTML = emptyHTML('Nothing open here', 'Everything in this filter is done.', true);
      }
      return;
    }
    const sections = cat.sections || [];
    if (!sections.length) {
      els.items.innerHTML = listHTML(cat, list);
      return;
    }
    const known = new Set(sections.map((s) => s.id));
    const html = sections.map((s) => {
      const sub = list.filter((it) => it.section === s.id);
      return sub.length ? sectionHTML(cat, s, sub) : '';
    });
    const rest = list.filter((it) => !known.has(it.section));
    if (rest.length) html.push(listHTML(cat, rest));
    els.items.innerHTML = html.join('');
  }

  function renderAll() {
    state.counts = store.counts(CATS);
    renderProfileSelect();
    renderOverall();
    renderNav();
    renderHead();
    renderToolbar();
    renderChips();
    renderItems();
    renderBanner();
    updateTitle();
  }

  /** Update every counter after a checkbox change, without touching the item list. */
  function refreshProgress() {
    state.counts = store.counts(CATS);
    renderOverall();
    renderNav();
    renderHead();
    renderChips();
    document.querySelectorAll('[data-sec]').forEach((el) => {
      const [catId, secId] = el.dataset.sec.split(':');
      const sc = state.counts.byCat[catId] && state.counts.byCat[catId].bySection[secId];
      if (sc) el.textContent = `${sc.done}/${sc.total}`;
    });
    renderBanner();
    updateTitle();
  }

  function updateTitle() {
    const cat = currentCat();
    const c = state.counts.byCat[cat.id];
    document.title = `${cat.title} ${c.done}/${c.total} - Abiotic Factor Checklist`;
  }

  // ------------------------------------------------------------------ checking items

  function removeWithAnimation(li) {
    const next = li.nextElementSibling || li.previousElementSibling;
    const list = li.parentElement;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      const hadFocus = li.contains(document.activeElement);
      li.remove();
      if (list && !list.children.length) {
        renderItems();
      } else if (hadFocus && next && next.isConnected) {
        const target = next.querySelector('input.check');
        if (target) target.focus();
      }
    };
    li.classList.add('is-leaving');
    li.addEventListener('animationend', finish, { once: true });
    setTimeout(finish, 450);
  }

  function onToggle(input) {
    const entry = itemById.get(input.dataset.id);
    if (!entry) return;
    const { item, cat } = entry;
    const on = input.checked;
    store.setChecked(item.id, on);
    if (on && item.hidden) state.revealed.add(item.id);

    document.querySelectorAll(`li[data-id="${CSS.escape(item.id)}"]`).forEach((li) => {
      li.classList.toggle('is-done', on);
      const box = li.querySelector('input.check');
      if (box && box !== input) box.checked = on;
      if (cat.kind === 'achievement' && item.hidden) {
        const details = li.querySelector('.row__details');
        if (details) details.innerHTML = detailsHTML(cat, item);
      }
    });

    refreshProgress();
    const c = state.counts.byCat[cat.id];
    announce(`${item.name} ${on ? 'done' : 'not done'}. ${cat.title}: ${c.done} of ${c.total}.`);

    if (on && store.prefs.hideCompleted) {
      const li = input.closest('li[data-id]');
      if (li) removeWithAnimation(li);
    }
  }

  els.items.addEventListener('change', (e) => {
    if (e.target.matches('input.check[data-id]')) onToggle(e.target);
  });

  els.items.addEventListener('click', (e) => {
    const reveal = e.target.closest('[data-reveal]');
    if (reveal) {
      const entry = itemById.get(reveal.dataset.reveal);
      if (!entry) return;
      state.revealed.add(entry.item.id);
      const details = reveal.closest('.row__details');
      if (details) details.innerHTML = detailsHTML(entry.cat, entry.item);
      return;
    }
    if (e.target.closest('[data-leave-search]')) clearSearch();
  });

  // images: local file -> online copy on the wiki -> "NO SIGNAL" placeholder
  document.addEventListener('error', (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement)) return;
    const fallback = img.getAttribute('data-fallback');
    if (fallback) {
      img.removeAttribute('data-fallback');
      img.src = fallback;
      return;
    }
    const box = img.parentElement;
    img.remove();
    if (box) box.classList.add('is-broken');
  }, true);

  // ------------------------------------------------------------------ toolbar events

  function applySearch() {
    state.q = els.q.value;
    state.terms = norm(state.q).split(/\s+/).filter(Boolean);
    renderHead();
    renderToolbar();
    renderChips();
    renderItems();
  }

  function clearSearch() {
    if (!els.q.value) return;
    els.q.value = '';
    applySearch();
  }

  let searchTimer = null;
  els.q.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applySearch, 100);
  });
  els.q.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && els.q.value) {
      e.preventDefault();
      clearTimeout(searchTimer);
      clearSearch();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t instanceof Element && t.closest('input, textarea, select, [contenteditable], dialog')) return;
    e.preventDefault();
    els.q.focus();
    els.q.select();
  });

  els.optHide.addEventListener('change', () => {
    store.setPref('hideCompleted', els.optHide.checked);
    renderItems();
  });
  els.optAll.addEventListener('change', () => {
    store.setPref('searchAll', els.optAll.checked);
    renderHead();
    renderToolbar();
    renderChips();
    renderItems();
    els.q.focus();
  });
  els.optSpoilers.addEventListener('change', () => {
    store.setPref('showSpoilers', els.optSpoilers.checked);
    if (!els.optSpoilers.checked) state.revealed.clear();
    renderItems();
  });

  els.chips.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-chip]');
    if (!btn) return;
    const tag = btn.dataset.chip;
    store.setPref('chips', Object.assign({}, store.prefs.chips, { [state.cat]: tag }));
    renderChips();
    renderItems();
    const again = els.chips.querySelector(`[data-chip="${CSS.escape(tag)}"]`);
    if (again) again.focus();
  });

  els.nav.addEventListener('click', (e) => {
    if (e.target.closest('a') && searchAllActive()) clearSearch();
  });

  els.profileSelect.addEventListener('change', () => {
    if (store.switchProfile(els.profileSelect.value)) {
      state.revealed.clear();
      renderAll();
      toast(`Profile "${store.activeProfile().name}" is active.`);
    }
  });

  // another tab changed the progress
  window.addEventListener('storage', (e) => {
    if (e.key === window.AFStore.KEY_PROGRESS || e.key === null) {
      store.reload();
      renderAll();
    }
  });

  // ------------------------------------------------------------------ routing

  function catFromHash() {
    const m = /^#\/([\w-]+)/.exec(location.hash);
    return m && catById.has(m[1]) ? m[1] : null;
  }

  function route() {
    let id = catFromHash();
    if (!id) {
      id = catById.has(store.prefs.category) ? store.prefs.category : CATS[0].id;
      try {
        history.replaceState(null, '', '#/' + id);
      } catch (e) {
        /* some browsers refuse this on file:// - the hash is only cosmetic */
      }
    }
    const changed = state.cat !== id;
    state.cat = id;
    if (store.prefs.category !== id) store.setPref('category', id);
    renderAll();
    if (changed) window.scrollTo(0, 0);
  }

  window.addEventListener('hashchange', route);

  // ------------------------------------------------------------------ dialogs

  function wireDialog(dlg) {
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg || e.target.closest('[data-close]')) dlg.close();
    });
  }

  function confirmDialog({ title, body, ok, danger }) {
    return new Promise((resolve) => {
      const dlg = els.dlgConfirm;
      dlg.innerHTML = `<div class="dlg">
        <h2 id="dlg-confirm-title">${esc(title)}</h2>
        <p class="dlg__text">${esc(body)}</p>
        <div class="dlg__actions">
          <button type="button" class="btn" data-answer="no">Cancel</button>
          <button type="button" class="btn ${danger ? 'btn--danger-solid' : 'btn--primary'}" data-answer="yes">${esc(ok || 'OK')}</button>
        </div></div>`;
      const onClick = (e) => {
        const b = e.target.closest('[data-answer]');
        if (b) finish(b.dataset.answer === 'yes');
        else if (e.target === dlg) finish(false);
      };
      const onClose = () => finish(false);
      function finish(answer) {
        dlg.removeEventListener('click', onClick);
        dlg.removeEventListener('close', onClose);
        if (dlg.open) dlg.close();
        resolve(answer);
      }
      dlg.addEventListener('click', onClick);
      dlg.addEventListener('close', onClose);
      dlg.showModal();
      dlg.querySelector('[data-answer="no"]').focus();
    });
  }

  // profiles

  function renderProfilesDialog() {
    const profiles = store.profiles();
    const rows = profiles.map((p) => {
      const c = store.counts(CATS, p.id);
      const active = p.id === store.prefs.activeProfileId;
      return `<li class="plist__row${active ? ' is-active' : ''}">
        <input class="input" value="${esc(p.name)}" maxlength="40" data-rename="${esc(p.id)}" aria-label="Name of profile ${esc(p.name)}">
        <span class="plist__count" title="done / total">${c.done}/${c.total}</span>
        ${active ? '<span class="plist__active">Active</span>'
          : `<button type="button" class="btn btn--small" data-activate="${esc(p.id)}">Switch</button>`}
        <button type="button" class="btn btn--small btn--danger" data-delete="${esc(p.id)}"
          ${profiles.length < 2 ? 'disabled title="The last profile cannot be deleted"' : ''}>Delete</button>
      </li>`;
    }).join('');
    els.dlgProfiles.innerHTML = `<div class="dlg">
      <div class="dlg__head"><h2 id="dlg-profiles-title">Profiles</h2>
        <button type="button" class="btn btn--icon" data-close aria-label="Close">&#10005;</button></div>
      <p class="dlg__text">Every profile keeps its own progress &ndash; for example one per world or per player.
        Click a name to rename it.</p>
      <ul class="plist">${rows}</ul>
      <form class="dlg__row" data-create>
        <input class="input" name="name" maxlength="40" placeholder="New profile name" aria-label="New profile name" required>
        <button type="submit" class="btn btn--primary">Create</button>
      </form></div>`;
  }

  function openProfiles() {
    renderProfilesDialog();
    els.dlgProfiles.showModal();
  }

  wireDialog(els.dlgProfiles);

  els.dlgProfiles.addEventListener('click', async (e) => {
    const activate = e.target.closest('[data-activate]');
    if (activate) {
      store.switchProfile(activate.dataset.activate);
      state.revealed.clear();
      renderAll();
      renderProfilesDialog();
      return;
    }
    const del = e.target.closest('[data-delete]');
    if (del && !del.disabled) {
      const id = del.dataset.delete;
      const p = store.progress.profiles[id];
      if (!p) return;
      const n = store.counts(CATS, id).done;
      const ok = await confirmDialog({
        title: 'Delete profile?',
        body: `"${p.name}" and its progress (${n} checked entries) will be deleted. Export a backup first if you are unsure.`,
        ok: 'Delete',
        danger: true,
      });
      if (!ok) return;
      store.deleteProfile(id);
      renderAll();
      renderProfilesDialog();
      toast(`Profile "${p.name}" deleted.`);
    }
  });

  els.dlgProfiles.addEventListener('change', (e) => {
    const input = e.target.closest('[data-rename]');
    if (!input) return;
    store.renameProfile(input.dataset.rename, input.value);
    renderProfileSelect();
    renderProfilesDialog();
  });

  els.dlgProfiles.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('[data-rename]')) {
      e.preventDefault();
      e.target.blur(); // fires "change"
    }
  });

  els.dlgProfiles.addEventListener('submit', (e) => {
    e.preventDefault();
    const form = e.target.closest('[data-create]');
    if (!form) return;
    const name = form.elements.name.value;
    const id = store.createProfile(name);
    store.switchProfile(id);
    state.revealed.clear();
    renderAll();
    renderProfilesDialog();
    toast(`Profile "${store.activeProfile().name}" created and active.`);
  });

  $('#btn-profiles').addEventListener('click', openProfiles);

  // backup & restore

  let pendingImport = null;

  function renderBackupDialog(extraHTML) {
    els.dlgBackup.innerHTML = `<div class="dlg">
      <div class="dlg__head"><h2 id="dlg-backup-title">Backup &amp; restore</h2>
        <button type="button" class="btn btn--icon" data-close aria-label="Close">&#10005;</button></div>
      <p class="dlg__text">Progress is saved automatically, but only in this browser on this PC. Export a backup file
        now and then &ndash; and before clearing browser data or moving to another browser or PC.</p>
      <div class="dlg__actions dlg__actions--start">
        <button type="button" class="btn btn--primary" data-export>Export backup</button>
        <button type="button" class="btn" data-import>Import backup&hellip;</button>
      </div>
      ${store.persistent ? '' : '<p class="dlg__warn">Storage is blocked in this browser: progress is lost when the page is closed. Export before closing!</p>'}
      ${extraHTML || ''}
    </div>`;
  }

  function openBackup() {
    pendingImport = null;
    renderBackupDialog();
    els.dlgBackup.showModal();
  }

  function stamp() {
    const d = new Date();
    const two = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}`;
  }

  function exportBackup() {
    const backup = store.makeBackup(CATS);
    const blob = new Blob([JSON.stringify(backup, null, 1)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `abiotic-checklist-${stamp()}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    toast(`Backup saved as ${a.download} (check your downloads folder).`);
  }

  function importPreviewHTML(parsed) {
    const when = parsed.exportedAt ? new Date(parsed.exportedAt) : null;
    const whenText = when && !isNaN(when) ? when.toLocaleString() : 'unknown date';
    const current = store.profiles().length;
    const rows = parsed.preview.map((p) =>
      `<li><b>${esc(p.name)}</b> &ndash; ${p.done} checked entries` +
      (p.unknown ? ` <span class="muted">(+${p.unknown} for entries that no longer exist)</span>` : '') + '</li>').join('');
    return `<div class="preview">
      <h3>Backup from ${esc(whenText)}</h3>
      <ul>${rows}</ul>
      <p class="dlg__warn">Importing replaces all ${current} current profile${current === 1 ? '' : 's'} in this browser.</p>
      <div class="dlg__actions">
        <button type="button" class="btn" data-import-cancel>Cancel</button>
        <button type="button" class="btn btn--danger-solid" data-import-confirm>Replace all profiles</button>
      </div></div>`;
  }

  wireDialog(els.dlgBackup);

  els.dlgBackup.addEventListener('click', (e) => {
    if (e.target.closest('[data-export]')) exportBackup();
    else if (e.target.closest('[data-import]')) els.importFile.click();
    else if (e.target.closest('[data-import-cancel]')) {
      pendingImport = null;
      renderBackupDialog();
    } else if (e.target.closest('[data-import-confirm]') && pendingImport) {
      store.importReplace(pendingImport);
      const n = pendingImport.preview.length;
      pendingImport = null;
      state.revealed.clear();
      els.dlgBackup.close();
      renderAll();
      toast(`Backup imported: ${n} profile${n === 1 ? '' : 's'}.`);
    }
  });

  els.importFile.addEventListener('change', async () => {
    const file = els.importFile.files[0];
    els.importFile.value = '';
    if (!file) return;
    let parsed;
    if (file.size > 5 * 1024 * 1024) {
      parsed = { error: 'This file is too large to be a checklist backup.' };
    } else {
      try {
        parsed = store.parseBackup(await file.text(), CATS);
      } catch (err) {
        parsed = { error: 'The file could not be read.' };
      }
    }
    if (!els.dlgBackup.open) els.dlgBackup.showModal();
    if (parsed.error) {
      pendingImport = null;
      renderBackupDialog(`<p class="dlg__warn error">${esc(parsed.error)}</p>`);
      return;
    }
    pendingImport = parsed;
    renderBackupDialog(importPreviewHTML(parsed));
  });

  $('#btn-backup').addEventListener('click', openBackup);

  // about & licenses

  function renderAboutDialog() {
    const link = (url, text) => `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    const ccBySa = link('https://creativecommons.org/licenses/by-sa/4.0/', 'CC BY-SA 4.0');
    const pageLink = (p) => link(p.revid ? `${p.url}?oldid=${p.revid}` : p.url, esc(p.page)) +
      (p.revid ? ` <span class="muted">(revision ${esc(p.revid)})</span>` : '');
    const sources = CATS.map((cat) => {
      const s = (DATA.sources || {})[cat.id];
      if (!s) return '';
      const also = (s.also || []).map(pageLink).join(', ');
      return `<li>${pageLink(s)}${also ? ', ' + also : ''} &ndash; used for ${esc(cat.title)}</li>`;
    }).join('');
    const permitted = document.documentElement.dataset.imagePermission === 'granted';
    const repo = repoInfo();
    els.dlgAbout.innerHTML = `<div class="dlg about">
      <div class="dlg__head"><h2 id="dlg-about-title">About &amp; licenses</h2>
        <button type="button" class="btn btn--icon" data-close aria-label="Close">&#10005;</button></div>
      <p class="dlg__text"><b>Abiotic Factor Field Checklist</b> is a free, unofficial fan project. It is not affiliated
        with or endorsed by Deep Field Games, Playstack or wiki.gg.</p>

      <h3>Texts &ndash; ${ccBySa}</h3>
      <p>Item names, descriptions, requirements and locations are adapted from the
        ${link(DATA.wikiBase || 'https://abioticfactor.wiki.gg', 'Abiotic Factor Wiki')} by the Abiotic Factor Wiki
        contributors and licensed under ${ccBySa}. Changes: selected, shortened and reformatted for this checklist.
        The adapted texts are shared under the same license.</p>
      <ul class="about__list">${sources}</ul>
      <p>Additional Lab Mask locations are based on a Reddit community guide, rewritten in our own words.</p>

      <h3>Game images</h3>
      <p>All item icons and screenshots are &copy; Deep Field Games and/or its licensors. All trademarks, including
        &ldquo;Abiotic Factor&rdquo;, belong to their respective owners.
        ${permitted ? 'The images are used with kind permission of Deep Field Games.'
          : 'They are shown only to identify items in this non-commercial fan project; permission from Deep Field Games has been requested.'}
        They are not covered by the licenses above.</p>

      <h3>Code</h3>
      <p>The checklist code (HTML, CSS, JavaScript, build scripts) is released under the MIT License.
        ${repo ? link(repo.url + '/blob/main/LICENSE', 'License text') + ' &middot; ' + link(repo.url, 'Source code on GitHub')
          + ' &middot; ' + link(repo.zip, 'Download (ZIP)') : 'See the LICENSE and CREDITS.md files.'}</p>

      <h3>Privacy</h3>
      <p>No accounts, no cookies, no tracking. Your progress is stored only in this browser (localStorage) and never
        sent anywhere &ndash; use &ldquo;Backup &amp; restore&rdquo; to move it. Links to the wiki open
        abioticfactor.wiki.gg. The online version is hosted on GitHub Pages; see the
        ${link('https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement', 'GitHub Privacy Statement')}.</p>
    </div>`;
  }

  wireDialog(els.dlgAbout);
  document.querySelectorAll('[data-open-about]').forEach((btn) => btn.addEventListener('click', () => {
    renderAboutDialog();
    els.dlgAbout.showModal();
  }));

  // ------------------------------------------------------------------ start

  renderMeta();
  route();
})();
