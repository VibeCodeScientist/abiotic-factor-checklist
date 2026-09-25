/* Abiotic Factor Field Checklist - progress storage: profiles, preferences and backups.
   No DOM access. Progress lives in localStorage; if that is blocked, everything is kept
   in memory for the session and `persistent` is false. */
(function (global) {
  'use strict';

  const KEY_PROGRESS = 'afChecklist.v1.progress';
  const KEY_PREFS = 'afChecklist.v1.prefs';
  const SCHEMA = 1;
  const BACKUP_FORMAT = 'af-checklist-backup';
  const MAX_NAME = 40;
  const MAX_CHECKED = 20000;

  function memoryStorage() {
    const map = new Map();
    return {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => { map.set(k, String(v)); },
      removeItem: (k) => { map.delete(k); },
    };
  }

  function isUsable(storage) {
    if (!storage) return false;
    try {
      const k = '__afChecklistProbe';
      storage.setItem(k, '1');
      storage.removeItem(k);
      return true;
    } catch (e) {
      return false;
    }
  }

  function newProfileId() {
    return 'p-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7);
  }

  function isPlainObject(v) {
    return !!v && typeof v === 'object' && !Array.isArray(v);
  }

  function cleanName(name, fallback) {
    const s = typeof name === 'string' ? name.replace(/\s+/g, ' ').trim().slice(0, MAX_NAME) : '';
    return s || fallback;
  }

  function cleanChecked(obj) {
    const out = {};
    if (!isPlainObject(obj)) return out;
    let n = 0;
    for (const [key, value] of Object.entries(obj)) {
      if (n >= MAX_CHECKED) break;
      if (key.length > 200) continue;
      if (typeof value === 'number' && isFinite(value) && value > 0) out[key] = value;
      else if (value === true) out[key] = Date.now();
      else continue;
      n++;
    }
    return out;
  }

  function cleanProfiles(obj) {
    const out = {};
    if (!isPlainObject(obj)) return out;
    let i = 0;
    for (const [id, p] of Object.entries(obj)) {
      if (!isPlainObject(p)) continue;
      i++;
      const safeId = /^[\w-]{1,64}$/.test(id) && !out[id] ? id : newProfileId();
      out[safeId] = {
        name: cleanName(p.name, 'Profile ' + i),
        created: typeof p.created === 'number' && isFinite(p.created) ? p.created : Date.now() + i,
        checked: cleanChecked(p.checked),
      };
    }
    return out;
  }

  class Store {
    constructor(storage) {
      this.warnings = [];
      this.persistent = isUsable(storage);
      this.storage = this.persistent ? storage : memoryStorage();
      this.readOnly = false; // set when the saved data comes from a newer app version
      this.progress = this._loadProgress();
      this.prefs = this._loadPrefs();
      this._ensureProfile();
    }

    _warn(msg) {
      if (!this.warnings.includes(msg)) this.warnings.push(msg);
    }

    _read(key) {
      let raw = null;
      try {
        raw = this.storage.getItem(key);
      } catch (e) {
        return null;
      }
      if (raw == null) return null;
      try {
        return JSON.parse(raw);
      } catch (e) {
        try { this.storage.setItem(key + '.corrupt-' + Date.now(), raw); } catch (e2) { /* ignore */ }
        this._warn('Saved data was damaged and has been reset. A copy of the damaged data was kept in the browser storage.');
        return null;
      }
    }

    _write(key, value) {
      if (this.readOnly && key === KEY_PROGRESS) return false;
      try {
        this.storage.setItem(key, JSON.stringify(value));
        return true;
      } catch (e) {
        this._warn('Progress could not be saved (' + ((e && e.name) || 'storage error') + '). Export a backup to keep it.');
        return false;
      }
    }

    _loadProgress() {
      const obj = this._read(KEY_PROGRESS);
      if (obj && typeof obj.schema === 'number' && obj.schema > SCHEMA) {
        this.readOnly = true;
        this._warn('Progress was saved by a newer version of this checklist - changes made here will not be saved.');
      }
      return { schema: SCHEMA, profiles: cleanProfiles(obj && obj.profiles) };
    }

    _loadPrefs() {
      const p = this._read(KEY_PREFS) || {};
      return {
        activeProfileId: typeof p.activeProfileId === 'string' ? p.activeProfileId : null,
        category: typeof p.category === 'string' ? p.category : null,
        hideCompleted: !!p.hideCompleted,
        showSpoilers: !!p.showSpoilers,
        searchAll: !!p.searchAll,
        chips: isPlainObject(p.chips) ? p.chips : {},
      };
    }

    _ensureProfile() {
      if (!Object.keys(this.progress.profiles).length) {
        this.progress.profiles[newProfileId()] = { name: 'Main', created: Date.now(), checked: {} };
        this._write(KEY_PROGRESS, this.progress);
      }
      if (!this.progress.profiles[this.prefs.activeProfileId]) {
        this.prefs.activeProfileId = this.profiles()[0].id;
        this.savePrefs();
      }
    }

    /** Re-read progress from storage (e.g. after another tab changed it). */
    reload() {
      if (!this.persistent) return;
      this.progress = this._loadProgress();
      this._ensureProfile();
    }

    // Re-read before every change so two open tabs don't overwrite each other's progress.
    _mutate(fn) {
      if (!this.readOnly) this.reload();
      const result = fn(this.progress);
      this._write(KEY_PROGRESS, this.progress);
      return result;
    }

    savePrefs() {
      this._write(KEY_PREFS, this.prefs);
    }

    setPref(key, value) {
      this.prefs[key] = value;
      this.savePrefs();
    }

    // ---------------------------------------------------------------- profiles & progress

    profiles() {
      return Object.entries(this.progress.profiles)
        .map(([id, p]) => ({ id, name: p.name, created: p.created }))
        .sort((a, b) => a.created - b.created || a.name.localeCompare(b.name));
    }

    activeProfile() {
      return this.progress.profiles[this.prefs.activeProfileId];
    }

    isChecked(itemId) {
      const p = this.activeProfile();
      return !!(p && p.checked[itemId]);
    }

    setChecked(itemId, on) {
      this._mutate((prog) => {
        const p = prog.profiles[this.prefs.activeProfileId];
        if (!p) return;
        if (on) {
          if (!p.checked[itemId]) p.checked[itemId] = Date.now();
        } else {
          delete p.checked[itemId];
        }
      });
    }

    /** Done/total overall, per category, per section and per tag. Unknown ids are ignored. */
    counts(categories, profileId) {
      const p = this.progress.profiles[profileId || this.prefs.activeProfileId];
      const checked = (p && p.checked) || {};
      const add = (map, key, d) => {
        const c = map[key] || (map[key] = { done: 0, total: 0 });
        c.total++;
        c.done += d;
      };
      const res = { done: 0, total: 0, byCat: {} };
      for (const cat of categories) {
        const c = { done: 0, total: 0, bySection: {}, byTag: {} };
        for (const it of cat.items) {
          const d = checked[it.id] ? 1 : 0;
          c.total++;
          c.done += d;
          if (it.section) add(c.bySection, it.section, d);
          for (const tag of it.tags || []) add(c.byTag, tag, d);
        }
        res.byCat[cat.id] = c;
        res.done += c.done;
        res.total += c.total;
      }
      return res;
    }

    createProfile(name) {
      const id = newProfileId();
      this._mutate((prog) => {
        const n = Object.keys(prog.profiles).length + 1;
        prog.profiles[id] = { name: cleanName(name, 'Profile ' + n), created: Date.now(), checked: {} };
      });
      return id;
    }

    renameProfile(id, name) {
      this._mutate((prog) => {
        const p = prog.profiles[id];
        if (p) p.name = cleanName(name, p.name);
      });
    }

    deleteProfile(id) {
      if (Object.keys(this.progress.profiles).length <= 1) return false;
      this._mutate((prog) => { delete prog.profiles[id]; });
      if (!this.progress.profiles[this.prefs.activeProfileId]) {
        this.prefs.activeProfileId = this.profiles()[0].id;
        this.savePrefs();
      }
      return true;
    }

    switchProfile(id) {
      if (!this.progress.profiles[id]) return false;
      this.prefs.activeProfileId = id;
      this.savePrefs();
      return true;
    }

    // ---------------------------------------------------------------- backups

    makeBackup(categories) {
      const summary = {};
      for (const p of this.profiles()) {
        const c = this.counts(categories, p.id);
        summary[p.id] = { name: p.name, done: c.done, total: c.total };
      }
      return {
        format: BACKUP_FORMAT,
        schema: SCHEMA,
        exportedAt: new Date().toISOString(),
        activeProfileId: this.prefs.activeProfileId,
        profiles: JSON.parse(JSON.stringify(this.progress.profiles)),
        summary, // for people reading the file; ignored on import
      };
    }

    /** Validate a backup file's text. Returns {error} or {backup, preview, exportedAt}. */
    parseBackup(text, categories) {
      let obj;
      try {
        obj = JSON.parse(text);
      } catch (e) {
        return { error: 'This file is not valid JSON.' };
      }
      if (!isPlainObject(obj) || obj.format !== BACKUP_FORMAT) {
        return { error: 'This file is not an Abiotic Factor checklist backup.' };
      }
      if (typeof obj.schema !== 'number' || obj.schema > SCHEMA) {
        return { error: 'This backup was made by a newer version of the checklist.' };
      }
      const profiles = cleanProfiles(obj.profiles);
      const ids = Object.keys(profiles);
      if (!ids.length) return { error: 'The backup does not contain any profiles.' };
      const known = new Set();
      categories.forEach((cat) => cat.items.forEach((it) => known.add(it.id)));
      const preview = ids.map((id) => {
        const keys = Object.keys(profiles[id].checked);
        const done = keys.filter((k) => known.has(k)).length;
        return { id, name: profiles[id].name, done, unknown: keys.length - done };
      });
      return {
        backup: { profiles, activeProfileId: profiles[obj.activeProfileId] ? obj.activeProfileId : ids[0] },
        preview,
        exportedAt: typeof obj.exportedAt === 'string' ? obj.exportedAt : null,
      };
    }

    /** Replace all profiles with the ones from a parsed backup. */
    importReplace(parsed) {
      this.readOnly = false;
      this.progress = { schema: SCHEMA, profiles: parsed.backup.profiles };
      this._write(KEY_PROGRESS, this.progress);
      this.prefs.activeProfileId = parsed.backup.activeProfileId;
      this.savePrefs();
    }
  }

  function open() {
    let storage = null;
    try {
      storage = global.localStorage;
    } catch (e) {
      storage = null; // access itself can throw when storage is blocked
    }
    return new Store(storage);
  }

  global.AFStore = { open, Store, KEY_PROGRESS, KEY_PREFS, SCHEMA, BACKUP_FORMAT };
})(window);
