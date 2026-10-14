// UX-Auditor · comprobaciones propias sobre el DOM.
// Se ejecuta en un mundo aislado: comparte el DOM con la página pero no su JavaScript,
// así que la página no puede sustituir getComputedStyle, Array.prototype, etc.
// Nunca hace clic, no escribe en campos ni envía formularios.
(() => {
  if (globalThis.__ux) return true;

  const LIMIT = 25;
  const gcs = (el) => window.getComputedStyle(el);
  const INTERACTIVE_SEL = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=switch]', '[role=tab]',
    '[role=menuitem]', '[role=menuitemcheckbox]', '[role=menuitemradio]', '[role=option]', '[role=slider]',
    '[role=combobox]', '[role=spinbutton]', '[tabindex]:not([tabindex="-1"])',
    '[contenteditable=""]', '[contenteditable=true]',
  ].join(',');
  const INTERACTIVE_ROLES = new Set(['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem',
    'menuitemcheckbox', 'menuitemradio', 'option', 'slider', 'combobox', 'spinbutton', 'textbox', 'searchbox', 'treeitem']);
  const EMOJI = /(?![©®‼⁉™ℹ↔-↙↩↪Ⓜ〰〽㊗㊙])\p{Extended_Pictographic}/u;
  const GENERIC_LINKS = new Set(['aqui', 'aquí', 'click aqui', 'click aquí', 'haz clic aquí', 'haz click aquí', 'pulsa aquí',
    'clic aquí', 'leer más', 'leer mas', 'más', 'mas', 'ver más', 'ver mas', 'más información', 'mas informacion',
    'más info', 'info', 'enlace', 'link', 'here', 'click here', 'read more', 'more', 'learn more', 'more info',
    'continuar', 'continue', 'ir', 'go', 'detalles', 'details', '+', '»', '>', '→']);

  // ───────── utilidades ─────────
  const text = (el, max = 80) => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim().slice(0, max);

  function sel(el) {
    if (!(el instanceof Element)) return '';
    const parts = [];
    let e = el;
    while (e && e.nodeType === 1 && parts.length < 5) {
      if (e.id && /^[A-Za-z][\w-]{0,60}$/.test(e.id)) {
        try { if (document.querySelectorAll('#' + CSS.escape(e.id)).length === 1) { parts.unshift('#' + e.id); break; } } catch (_) {}
      }
      let p = e.localName;
      const cls = Array.from(e.classList).filter((c) => /^[A-Za-z_][\w-]{0,40}$/.test(c)).slice(0, 2);
      if (cls.length) p += '.' + cls.join('.');
      const parent = e.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.localName === e.localName);
        if (same.length > 1) p += `:nth-of-type(${same.indexOf(e) + 1})`;
      }
      parts.unshift(p);
      e = parent;
    }
    return parts.join(' > ').slice(0, 300);
  }

  function rectOf(el) { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom }; }

  function hiddenByAncestor(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = gcs(e);
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') return true;
      if (parseFloat(s.opacity) === 0) return true;
      if (e.hasAttribute('hidden') || e.getAttribute('aria-hidden') === 'true' || e.hasAttribute('inert')) return true;
    }
    return false;
  }

  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (r.bottom < -window.scrollY - 5 || r.right < -5) return false; // fuera de pantalla (técnica «sr-only» por posición)
    const s = gcs(el);
    if (s.clipPath && s.clipPath.includes('inset(50%)')) return false;
    if (s.clip && s.clip !== 'auto' && r.width <= 2 && r.height <= 2) return false;
    return !hiddenByAncestor(el);
  }

  function isDisabled(el) { return el.disabled === true || el.getAttribute('aria-disabled') === 'true'; }

  function result(id) { return { id, passed: 0, total: 0, items: [] }; }
  function add(r, ok, el, detail) {
    r.total++;
    if (ok) r.passed++;
    else if (r.items.length < LIMIT) r.items.push({ s: sel(el), d: String(detail).slice(0, 200) });
  }

  function accessibleName(el) {
    const label = el.getAttribute('aria-label');
    if (label && label.trim()) return label.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean).map((n) => text(n, 200)).join(' ').trim();
      if (t) return t;
    }
    if (el.labels && el.labels.length) {
      const lt = Array.from(el.labels).map((l) => text(l, 200)).join(' ').trim();
      if (lt) return lt;
    }
    let t = text(el, 200);
    if (!t) t = Array.from(el.querySelectorAll('img[alt]')).map((i) => i.alt).join(' ').trim();
    if (!t && el.localName === 'input') t = (el.value && /^(submit|button|reset)$/.test(el.type) ? el.value : el.placeholder || '').trim();
    return t || (el.getAttribute('title') || '').trim();
  }

  function interactiveElements() {
    return Array.from(document.querySelectorAll(INTERACTIVE_SEL)).slice(0, 1500)
      .filter((el) => !isDisabled(el) && visible(el));
  }

  function isInlineTextLink(el) {
    if (el.localName !== 'a') return false;
    const s = gcs(el);
    if (!s.display.startsWith('inline') || s.display === 'inline-block' || s.display === 'inline-flex') return false;
    const block = el.closest('p, li, td, dd, blockquote, figcaption, label, span, small');
    if (!block) return false;
    return text(block, 2000).length > text(el, 2000).length + 10;
  }

  function targetRect(el) {
    // Para casillas y radios, el área efectiva incluye su <label>.
    if (el.localName === 'input' && /^(checkbox|radio)$/.test(el.type)) {
      const lbl = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
      if (lbl && visible(lbl)) {
        const a = el.getBoundingClientRect(), b = lbl.getBoundingClientRect();
        const x = Math.min(a.left, b.left), y = Math.min(a.top, b.top);
        const r = Math.max(a.right, b.right), bt = Math.max(a.bottom, b.bottom);
        return { x, y, w: r - x, h: bt - y, r, b: bt };
      }
    }
    return rectOf(el);
  }

  function dist(a, b) { // distancia entre rectángulos (0 si se tocan)
    const dx = Math.max(0, Math.max(a.x, b.x) - Math.min(a.r, b.r));
    const dy = Math.max(0, Math.max(a.y, b.y) - Math.min(a.b, b.b));
    return Math.hypot(dx, dy);
  }
  function pointRectDist(px, py, b) {
    const dx = Math.max(b.x - px, 0, px - b.r); const dy = Math.max(b.y - py, 0, py - b.b);
    return Math.hypot(dx, dy);
  }

  // ───────── D2 · interacción ─────────
  function targets(mobile) {
    const wcag = result('INT-OBJETIVO-WCAG');
    const touch = result('INT-OBJETIVO-TACTIL');
    const spacing = result('INT-ESPACIADO');
    const els = interactiveElements().filter((el) => !isInlineTextLink(el) && !(el.localName === 'input' && el.type === 'range'));
    const list = els.slice(0, 400).map((el) => ({ el, r: targetRect(el) }));
    for (const t of list) {
      const { w, h } = t.r;
      const small = w < 24 || h < 24;
      let ok = !small;
      if (small) { // excepción de espaciado de WCAG 2.5.8
        const cx = t.r.x + w / 2, cy = t.r.y + h / 2;
        ok = list.every((o) => {
          if (o === t || o.el.contains(t.el) || t.el.contains(o.el)) return true;
          const oSmall = o.r.w < 24 || o.r.h < 24;
          if (oSmall) return Math.hypot(cx - (o.r.x + o.r.w / 2), cy - (o.r.y + o.r.h / 2)) >= 24;
          return pointRectDist(cx, cy, o.r) >= 12;
        });
      }
      add(wcag, ok, t.el, `${Math.round(w)}×${Math.round(h)} px «${accessibleName(t.el).slice(0, 40)}»`);
      if (mobile) {
        add(touch, w >= 43.5 && h >= 43.5, t.el, `${Math.round(w)}×${Math.round(h)} px «${accessibleName(t.el).slice(0, 40)}»`);
        let near = null;
        for (const o of list) {
          if (o === t || o.el.contains(t.el) || t.el.contains(o.el)) continue;
          const d = dist(t.r, o.r);
          const overlap = d === 0 && !(t.r.r <= o.r.x || o.r.r <= t.r.x || t.r.b <= o.r.y || o.r.b <= t.r.y);
          if (overlap) continue;
          const tooSmall = Math.min(t.r.w, t.r.h, o.r.w, o.r.h) < 44;
          if (d < 8 && tooSmall) { near = o; break; }
        }
        add(spacing, !near, t.el, near ? `a menos de 8 px de «${accessibleName(near.el).slice(0, 30)}»` : '');
      }
    }
    return mobile ? [wcag, touch, spacing] : [wcag];
  }

  function clickSemantics(desktop) {
    const r = result('INT-CLIC-NO-SEMANTICO');
    const cursor = result('INT-CURSOR');
    const all = Array.from(document.body ? document.body.querySelectorAll('*') : []).slice(0, 5000);
    for (const el of all) {
      const tag = el.localName;
      if (['html', 'body', 'svg', 'path', 'use', 'g', 'option'].includes(tag)) continue;
      const s = gcs(el);
      const hasOnclick = el.hasAttribute('onclick');
      const pointer = s.cursor === 'pointer';
      if (!pointer && !hasOnclick) continue;
      const parent = el.parentElement;
      const inherited = pointer && !hasOnclick && parent && gcs(parent).cursor === 'pointer';
      if (inherited) continue;
      if (!visible(el)) continue;
      const role = (el.getAttribute('role') || '').trim();
      const semantic = el.matches(INTERACTIVE_SEL) || INTERACTIVE_ROLES.has(role) || tag === 'label';
      if (semantic) continue;
      if (el.closest('a[href], button, [role=button], [role=link], label, summary')) continue;
      if (el.querySelector('a[href], button, [role=button], [role=link], input, select, textarea')) continue;
      add(r, false, el, `<${tag}> ${hasOnclick ? 'con onclick' : 'con cursor:pointer'} sin role ni tabindex («${text(el, 40)}»)`);
    }
    // Total = elementos interactivos reales + falsos; los reales cuentan como correctos.
    const real = interactiveElements();
    r.total += real.length; r.passed += real.length;
    if (desktop) {
      for (const el of real) {
        if (el.matches('input:not([type=button]):not([type=submit]):not([type=reset]):not([type=checkbox]):not([type=radio]):not([type=image]):not([type=file]):not([type=color]), textarea, [contenteditable], select, [role=combobox], [role=textbox], [role=slider], [role=spinbutton]')) continue;
        if (el.matches('[tabindex]') && !el.matches('a, button, [role]')) continue;
        if (el.matches('input[type=checkbox], input[type=radio]')) continue;
        add(cursor, gcs(el).cursor === 'pointer', el, `cursor: ${gcs(el).cursor} en «${accessibleName(el).slice(0, 40)}»`);
      }
      return [r, cursor];
    }
    return [r];
  }

  // ───────── D4 · tipografía y diseño visual ─────────
  function textBlocks() {
    const out = []; const seen = new Set();
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
    let n; let count = 0;
    while ((n = walker.nextNode()) && count < 4000) {
      const t = n.nodeValue.replace(/\s+/g, ' ').trim();
      if (t.length < 2) continue;
      const el = n.parentElement;
      if (!el || seen.has(el) || ['script', 'style', 'noscript', 'template', 'title'].includes(el.localName)) continue;
      seen.add(el); count++;
      if (!visible(el)) continue;
      out.push({ el, len: Array.from(el.childNodes).filter((c) => c.nodeType === 3).reduce((a, c) => a + c.nodeValue.trim().length, 0) });
    }
    return out;
  }

  function typography(mobile, desktop) {
    const small = result('VIS-TAM-TEXTO');
    const lh = result('VIS-INTERLINEADO');
    const len = result('VIS-LONGITUD-LINEA');
    const families = new Map(); const colors = new Map();
    const sizes = [];
    const blocks = textBlocks();
    for (const { el, len: chars } of blocks) {
      const s = gcs(el);
      const fs = parseFloat(s.fontSize) || 16;
      add(small, fs >= 11.5, el, `${fs.toFixed(1)} px: «${text(el, 50)}»`);
      if (chars >= 40) sizes.push([fs, chars]);
      const fam = (s.fontFamily.split(',')[0] || '').replace(/["']/g, '').trim().toLowerCase();
      if (fam) families.set(fam, (families.get(fam) || 0) + chars);
      colors.set(s.color, (colors.get(s.color) || 0) + chars);
      if (chars >= 80 && /^(p|li|dd|blockquote|div|article|section|td|figcaption|span)$/.test(el.localName)) {
        const lineH = s.lineHeight === 'normal' ? fs * 1.2 : parseFloat(s.lineHeight);
        const ratio = lineH / fs;
        add(lh, ratio >= 1.39, el, `interlineado ${ratio.toFixed(2)}: «${text(el, 40)}»`);
        if (desktop) {
          const r = el.getBoundingClientRect();
          if (r.height > lineH * 2.5) {
            const cpl = r.width / (fs * 0.5);
            add(len, cpl <= 90, el, `≈${Math.round(cpl)} caracteres por línea`);
          }
        }
      }
    }
    const out = [small, lh];
    if (desktop) out.push(len);
    // Familias: solo las que suponen ≥ 2 % del texto (ignora iconos/logos sueltos).
    const totalChars = Array.from(families.values()).reduce((a, b) => a + b, 0) || 1;
    const fams = Array.from(families.entries()).filter(([, c]) => c / totalChars >= 0.02).map(([f]) => f);
    const famValue = fams.length <= 3 ? 1 : (fams.length === 4 ? 0.5 : 0);
    out.push({ id: 'VIS-FUENTES', value: blocks.length ? famValue : null, measured: `${fams.length} familias: ${fams.slice(0, 6).join(', ')}`,
      items: famValue < 1 ? [{ s: 'body', d: fams.join(', ').slice(0, 200) }] : [] });
    const totalC = Array.from(colors.values()).reduce((a, b) => a + b, 0) || 1;
    const cols = Array.from(colors.entries()).filter(([, c]) => c / totalC >= 0.005).length;
    const colValue = cols <= 8 ? 1 : (cols <= 12 ? 0.5 : 0);
    out.push({ id: 'VIS-COLORES-TEXTO', value: blocks.length ? colValue : null, measured: `${cols} colores de texto distintos`,
      items: colValue < 1 ? [{ s: 'body', d: `${cols} colores de texto (recomendado ≤ 8)` }] : [] });
    if (mobile) {
      let base = null;
      if (sizes.length) { // mediana ponderada por caracteres
        sizes.sort((a, b) => a[0] - b[0]);
        const half = sizes.reduce((a, [, c]) => a + c, 0) / 2;
        let acc = 0;
        for (const [fs, c] of sizes) { acc += c; if (acc >= half) { base = fs; break; } }
      }
      out.push({ id: 'VIS-TEXTO-BASE', value: base === null ? null : (base >= 15.5 ? 1 : (base >= 14 ? 0.5 : 0)),
        measured: base === null ? 'sin bloques de texto' : `texto base ${base.toFixed(1)} px`,
        items: base !== null && base < 15.5 ? [{ s: 'body', d: `Tamaño de texto predominante ${base.toFixed(1)} px` }] : [] });
    }
    return out;
  }

  function emojiIcons() {
    const r = result('VIS-EMOJI-ICONOS');
    const els = Array.from(document.querySelectorAll(`${INTERACTIVE_SEL}, h1, h2, h3, h4, h5, h6, nav li, li > span:first-child`)).slice(0, 1500);
    for (const el of els) {
      if (!visible(el)) continue;
      const t = text(el, 120);
      if (!t) continue;
      const first = Array.from(t)[0] || '';
      const onlyEmoji = t.replace(/[\s️‍]/g, '').split('').every((c) => EMOJI.test(c) || /[\uD800-\uDFFF]/.test(c));
      const bad = EMOJI.test(first) || (onlyEmoji && EMOJI.test(t));
      add(r, !bad, el, `«${t.slice(0, 40)}»`);
    }
    return [r];
  }

  function overflow(viewportName) {
    const doc = document.documentElement;
    const width = window.innerWidth;
    const scrollW = Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const r = result('VIS-DESBORDAMIENTO');
    const culprits = scrollW > width + 1 ? overflowCulprits(width) : [];
    r.total = 1; r.passed = scrollW > width + 1 ? 0 : 1;
    if (!r.passed) r.items = culprits.length ? culprits : [{ s: 'html', d: `ancho del documento ${scrollW} px > ${width} px` }];
    return [r];
  }

  function overflowCulprits(width) {
    const out = [];
    const scrollable = (e) => { for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const ox = gcs(a).overflowX; if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true; } return false; };
    for (const el of Array.from(document.body ? document.body.querySelectorAll('*') : []).slice(0, 5000)) {
      const rc = el.getBoundingClientRect();
      if (rc.right > width + 1 && rc.width > 0 && !scrollable(el) && visible(el)) {
        // nos quedamos con el elemento más externo que desborda
        if (out.some((o) => o.el.contains(el))) continue;
        out.push({ el, w: Math.round(rc.width), right: Math.round(rc.right) });
        if (out.length >= LIMIT) break;
      }
    }
    return out.map((o) => ({ s: sel(o.el), d: `<${o.el.localName}> termina en ${o.right} px (ancho ${o.w} px)` }));
  }

  // ───────── D5 · formularios ─────────
  const PURPOSE = [
    [/e-?mail|correo/i, 'email', 'email'],
    [/(tel|phone|movil|móvil|telefono|teléfono|celular)/i, 'tel', 'tel'],
    [/(apellido|surname|last.?name|family)/i, 'family-name', null],
    [/(nombre|first.?name|given|full.?name|^name$|your.?name)/i, 'name', null],
    [/(cp|postal|zip|codigo.?postal|código.?postal)/i, 'postal-code', 'numeric'],
    [/(direcci|address|street|calle)/i, 'street-address', null],
    [/(ciudad|city|localidad|poblaci)/i, 'address-level2', null],
    [/(pais|país|country)/i, 'country-name', null],
    [/(usuario|user.?name|login)/i, 'username', null],
    [/(tarjeta|card.?number|cc-?num)/i, 'cc-number', 'numeric'],
  ];
  function purposeOf(el) {
    if (el.type === 'password') return ['current-password', null];
    if (el.type === 'email') return ['email', null];
    if (el.type === 'tel') return ['tel', null];
    const hint = `${el.name || ''} ${el.id || ''} ${el.getAttribute('autocomplete') || ''} ${el.placeholder || ''}`;
    for (const [re, ac, type] of PURPOSE) if (re.test(hint)) return [ac, type];
    return null;
  }

  function visibleLabel(el) {
    if (el.labels) for (const l of el.labels) if (visible(l) && text(l).length > 0) return true;
    const by = el.getAttribute('aria-labelledby');
    if (by) for (const id of by.split(/\s+/)) { const n = document.getElementById(id); if (n && visible(n) && text(n)) return true; }
    if (el.localName === 'input' && /^(submit|button|reset|image)$/.test(el.type)) return true;
    return false;
  }

  function forms() {
    const labels = result('FORM-ETIQUETA-VISIBLE');
    const auto = result('FORM-AUTOCOMPLETE');
    const types = result('FORM-TIPO-ENTRADA');
    const paste = result('FORM-PEGAR');
    const groups = result('FORM-GRUPOS');
    const submit = result('FORM-ENVIO');
    const controls = Array.from(document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea'))
      .slice(0, 500).filter((el) => visible(el) || (el.type === 'checkbox' || el.type === 'radio'));
    for (const el of controls) {
      if (el.type === 'checkbox' || el.type === 'radio') continue; // se valoran como grupo
      const inSearch = el.type === 'search' || el.closest('[role=search], search');
      const ok = visibleLabel(el) || (inSearch && accessibleName(el));
      add(labels, ok, el, el.placeholder ? `solo placeholder «${el.placeholder.slice(0, 40)}»` : 'sin etiqueta visible');
      const p = el.localName === 'input' ? purposeOf(el) : null;
      if (p) {
        const ac = (el.getAttribute('autocomplete') || '').trim().toLowerCase();
        add(auto, ac !== '' && ac !== 'off' && ac !== 'nope', el, ac ? `autocomplete="${ac}"` : `falta autocomplete="${p[0]}"`);
        if (p[1] && el.type === 'text' && !el.getAttribute('inputmode')) {
          add(types, false, el, `type="text" para un dato tipo ${p[1]} (usa type="${p[1] === 'numeric' ? 'text" inputmode="numeric' : p[1]}")`);
        } else if (p[1]) add(types, true, el, '');
      }
      if (el.type === 'password' || el.type === 'email' || (p && p[0] === 'username')) {
        let blocked = /return\s+false|preventDefault/i.test(el.getAttribute('onpaste') || '');
        if (!blocked) {
          try { // evento sintético: no inserta texto ni cambia el valor del campo
            const dt = new DataTransfer(); dt.setData('text/plain', 'x');
            const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
            blocked = !el.dispatchEvent(ev);
          } catch (_) {}
        }
        add(paste, !blocked, el, `se bloquea pegar en el campo ${el.type}`);
      }
    }
    // grupos de radios / casillas
    const byName = new Map();
    for (const el of document.querySelectorAll('input[type=radio][name], input[type=checkbox][name]')) {
      const key = `${el.form ? 'f' : 'x'}:${el.type}:${el.name}`;
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key).push(el);
    }
    for (const [, els] of byName) {
      if (els.length < 2 || !els.some(visible)) continue;
      const fs = els[0].closest('fieldset');
      const legend = fs && fs.querySelector('legend');
      const group = els[0].closest('[role=radiogroup], [role=group]');
      const ok = (legend && text(legend)) || (group && accessibleName(group));
      add(groups, !!ok, els[0], `grupo «${els[0].name}» (${els.length} opciones) sin fieldset/legend`);
    }
    for (const f of document.querySelectorAll('form')) {
      if (!visible(f) || !f.querySelector('input:not([type=hidden]), select, textarea')) continue;
      const hasSubmit = f.querySelector('button:not([type]), button[type=submit], input[type=submit], input[type=image]') ||
        (f.id && document.querySelector(`[form="${CSS.escape(f.id)}"][type=submit]`));
      add(submit, !!hasSubmit, f, 'formulario sin botón de envío');
    }
    return [labels, auto, types, paste, groups, submit];
  }

  // ───────── D6 · navegación ─────────
  function navigation(mobile, desktop) {
    const out = [];
    const title = (document.title || '').trim();
    const generic = /^(document|untitled|sin t[ií]tulo|react app|vite app|home|inicio|index|page|p[aá]gina|new tab|my app|app)$/i;
    const tv = !title ? 0 : (generic.test(title) || title.length < 10 || title.length > 70 ? 0.5 : 1);
    out.push({ id: 'NAV-TITULO', value: tv, measured: title ? `«${title.slice(0, 80)}» (${title.length} caracteres)` : 'sin título',
      items: tv < 1 ? [{ s: 'title', d: title ? `«${title.slice(0, 80)}»: genérico o de longitud inadecuada` : 'La página no tiene <title>' }] : [] });

    const lm = result('NAV-LANDMARKS');
    const mains = Array.from(document.querySelectorAll('main, [role=main]')).filter((m) => !m.closest('[hidden]'));
    add(lm, mains.length === 1, document.body, mains.length === 0 ? 'no hay <main>' : `hay ${mains.length} regiones main`);
    const links = Array.from(document.querySelectorAll('a[href]')).filter(visible);
    const outside = links.filter((a) => !a.closest('main, [role=main]')).length;
    if (outside >= 5) add(lm, !!document.querySelector('nav, [role=navigation]'), document.body, `${outside} enlaces fuera de <main> sin <nav>`);
    out.push(lm);

    const anchors = result('NAV-ANCLAS-ROTAS');
    for (const a of links.slice(0, 1500)) {
      const href = a.getAttribute('href') || '';
      if (/^\s*javascript:/i.test(href) || href.trim() === '#') {
        add(anchors, a.getAttribute('role') === 'button', a, `href="${href.slice(0, 40)}" (falso enlace: usa <button>)`);
      } else if (href.startsWith('#')) {
        const id = decodeURIComponent(href.slice(1));
        const ok = id === 'top' || !!document.getElementById(id) || !!document.getElementsByName(id).length;
        add(anchors, ok, a, `destino «${href.slice(0, 60)}» inexistente`);
      }
    }
    out.push(anchors);

    const purpose = result('NAV-TEXTO-ENLACES');
    const blank = result('NAV-NUEVA-VENTANA');
    for (const a of links.slice(0, 1500)) {
      const name = accessibleName(a).toLowerCase().replace(/[.:…!]+$/, '').trim();
      if (name) {
        const ok = !GENERIC_LINKS.has(name) || a.hasAttribute('aria-describedby') || (a.title && a.title.trim().length > 10);
        add(purpose, ok, a, `texto genérico «${name.slice(0, 40)}»`);
      }
      if ((a.getAttribute('target') || '').toLowerCase() === '_blank') {
        const hint = `${name} ${(a.title || '')} ${Array.from(a.querySelectorAll('[aria-label],[title],img[alt]')).map((n) => n.getAttribute('aria-label') || n.title || n.alt).join(' ')}`.toLowerCase();
        add(blank, /(nueva (ventana|pesta)|new (window|tab)|extern|abre en|opens in)/.test(hint), a, `«${name.slice(0, 40)}» se abre en otra pestaña sin avisar`);
      }
    }
    out.push(purpose, blank);

    if (desktop) {
      const menu = result('NAV-MENU');
      for (const nav of Array.from(document.querySelectorAll('nav, [role=navigation]')).filter(visible)) {
        const list = nav.querySelector('ul, ol, [role=menubar], [role=list]');
        const items = list ? Array.from(list.children).filter(visible) : Array.from(nav.querySelectorAll('a[href]')).filter(visible);
        if (items.length < 2) continue;
        if (nav.closest('footer')) continue;
        add(menu, items.length <= 7, nav, `${items.length} opciones en el primer nivel`);
      }
      out.push(menu);
    }
    if (mobile) {
      const bar = result('NAV-BARRA-INFERIOR');
      for (const el of Array.from(document.querySelectorAll('nav, [role=navigation], [role=tablist], footer, div, ul')).slice(0, 3000)) {
        const s = gcs(el);
        if (s.position !== 'fixed' && s.position !== 'sticky') continue;
        const r = el.getBoundingClientRect();
        if (r.bottom < window.innerHeight - 4 || r.height > 140 || r.width < window.innerWidth * 0.8 || !visible(el)) continue;
        const items = Array.from(el.querySelectorAll(INTERACTIVE_SEL)).filter(visible).length;
        if (items < 2) continue;
        add(bar, items <= 5, el, `${items} opciones en la barra inferior`);
      }
      out.push(bar);
    }
    return out;
  }

  // ───────── D3 · recursos (parte DOM) ─────────
  function images() {
    const dims = result('PERF-IMG-DIMENSIONES');
    const lazy = result('PERF-IMG-LAZY');
    const over = result('PERF-IMG-SOBREDIMENSION');
    const vh = window.innerHeight;
    const dpr = window.devicePixelRatio || 1;
    for (const img of Array.from(document.images).slice(0, 600)) {
      if (!img.currentSrc && !img.src) continue;
      const r = img.getBoundingClientRect();
      const s = gcs(img);
      if (s.display === 'none') continue;
      const hasDims = (img.getAttribute('width') && img.getAttribute('height')) || (s.aspectRatio && s.aspectRatio !== 'auto') ||
        (s.position === 'absolute' || s.position === 'fixed') || (s.height && s.height.endsWith('px') && img.style.height);
      add(dims, !!hasDims, img, `«${(img.currentSrc || img.src).split('/').pop().slice(0, 60)}» sin width/height`);
      const absTop = r.top + window.scrollY;
      if (absTop > vh * 1.5) add(lazy, img.loading === 'lazy', img, `imagen a ${Math.round(absTop)} px sin loading="lazy"`);
      if (img.complete && img.naturalWidth > 400 && r.width > 0) {
        const needed = r.width * dpr * 1.5;
        add(over, img.naturalWidth <= needed, img, `${img.naturalWidth} px de ancho real para ${Math.round(r.width)} px mostrados`);
      }
    }
    const fonts = result('PERF-FUENTES');
    try {
      const seen = new Set();
      document.fonts.forEach((f) => {
        if (f.status !== 'loaded' && f.status !== 'loading') return;
        const key = `${f.family}|${f.weight}|${f.style}`;
        if (seen.has(key) || seen.size > 200) return;
        seen.add(key);
        fonts.total++;
        if (['swap', 'optional', 'fallback'].includes(f.display)) fonts.passed++;
        else if (fonts.items.length < LIMIT) fonts.items.push({ s: '@font-face', d: `${f.family.replace(/["']/g, '')} ${f.weight}: font-display ${f.display}` });
      });
    } catch (_) {}
    return [dims, lazy, over, fonts];
  }

  // ───────── teclado (llamadas desde Python entre pulsaciones de Tab) ─────────
  const focusState = { baseline: new Map(), steps: [], stuck: 0, last: null, done: false, candidates: [] };
  const FOCUS_PROPS = ['outlineStyle', 'outlineWidth', 'outlineColor', 'boxShadow', 'borderTopColor', 'borderBottomColor',
    'borderBottomWidth', 'backgroundColor', 'color', 'textDecorationLine', 'transform'];
  function snapshot(el) {
    // Solo cuenta lo que se VE: un color de contorno con outline:none o un borde de 0 px no es un indicador.
    const s = gcs(el);
    const outline = s.outlineStyle === 'none' || parseFloat(s.outlineWidth) === 0 ? 'none' : `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}`;
    const border = ['Top', 'Right', 'Bottom', 'Left'].map((side) =>
      parseFloat(s[`border${side}Width`]) === 0 || s[`border${side}Style`] === 'none' ? '0' : `${s[`border${side}Width`]} ${s[`border${side}Color`]}`).join(',');
    return [outline, border, s.boxShadow, s.backgroundColor, s.color, s.textDecorationLine, s.textDecorationThickness, s.transform].join('|');
  }

  function deepActive() {
    let a = document.activeElement;
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    return a;
  }

  function prepareFocus() {
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    window.scrollTo(0, 0);
    focusState.baseline = new Map(); focusState.steps = []; focusState.stuck = 0; focusState.last = null; focusState.done = false;
    const cands = Array.from(document.querySelectorAll(INTERACTIVE_SEL))
      .filter((el) => !isDisabled(el) && el.tabIndex >= 0 && visible(el) && !el.closest('[inert]'));
    focusState.candidates = cands.slice(0, 600);
    for (const el of focusState.candidates) focusState.baseline.set(el, [snapshot(el), el.parentElement ? snapshot(el.parentElement) : '']);
    const main = document.querySelector('main, [role=main]');
    let before = 0;
    if (main) for (const el of cands) { if (main.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING) before++; }
    return { candidates: focusState.candidates.length, beforeMain: before, hasMain: !!main };
  }

  function obscured(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > window.innerHeight) return false;
    const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 2, r.top + 2], [r.right - 2, r.top + 2],
      [r.left + 2, r.bottom - 2], [r.right - 2, r.bottom - 2]];
    let covered = 0;
    for (const [x, y] of pts) {
      if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) { covered++; continue; }
      const top = document.elementFromPoint(x, y);
      if (top && top !== el && !el.contains(top) && !top.contains(el)) {
        let fixed = false;
        for (let a = top; a && a !== document.body; a = a.parentElement) {
          const p = gcs(a).position; if (p === 'fixed' || p === 'sticky') { fixed = true; break; }
        }
        if (fixed) covered++;
      }
    }
    return covered === pts.length;
  }

  function recordFocus() {
    const el = deepActive();
    if (!el || el === document.body || el === document.documentElement) {
      if (focusState.steps.length) focusState.done = true;
      return { done: focusState.done, empty: true };
    }
    // Primero detectamos la trampa: Tab no avanza (mismo elemento en pulsaciones consecutivas).
    if (el === focusState.last && el.localName !== 'iframe') {
      focusState.stuck++;
      return { done: false, stuck: focusState.stuck };
    }
    focusState.stuck = 0;
    if (focusState.steps.length && focusState.steps[0].el === el) { focusState.done = true; return { done: true }; }
    focusState.last = el;
    const base = focusState.baseline.get(el);
    let changed = true;
    if (base) {
      const parentNow = el.parentElement ? snapshot(el.parentElement) : '';
      const s = gcs(el);
      const outlineOk = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1;
      changed = outlineOk || snapshot(el) !== base[0] || parentNow !== base[1];
    } else {
      const s = gcs(el);
      changed = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1) || s.boxShadow !== 'none';
    }
    const href = el.getAttribute && el.getAttribute('href');
    const rr = el.getBoundingClientRect();
    let fixedPos = false;
    for (let a = el; a && a !== document.body; a = a.parentElement) {
      const p = gcs(a).position; if (p === 'fixed' || p === 'sticky') { fixedPos = true; break; }
    }
    focusState.steps.push({ el, changed, obscured: obscured(el), href, fixedPos,
      top: rr.top + window.scrollY, left: rr.left + window.scrollX, h: rr.height,
      skipTarget: href && href.startsWith('#') && href.length > 1 && !!document.getElementById(decodeURIComponent(href.slice(1))) });
    return { done: false, stuck: focusState.stuck };
  }

  function focusSummary(info) {
    const visibleR = result('A11Y-FOCO-VISIBLE');
    const hiddenR = result('A11Y-FOCO-OCULTO');
    const reach = result('A11Y-TECLADO-ALCANCE');
    const trap = result('A11Y-TRAMPA-TECLADO');
    const skip = result('NAV-SALTAR');
    const order = result('A11Y-ORDEN-FOCO');
    const seen = new Set();
    // Orden del foco (WCAG 2.4.3): saltos hacia atrás dentro de la misma columna visual.
    const flow = focusState.steps.filter((s) => !s.fixedPos && s.el.localName !== 'iframe' && !(s.href && s.href.startsWith('#') && s === focusState.steps[0]));
    for (let i = 1; i < flow.length; i++) {
      const a = flow[i - 1], b = flow[i];
      const back = b.top < a.top - Math.max(40, a.h) && b.left <= a.left + 24;
      add(order, !back, b.el, `el foco salta hacia arriba: de «${accessibleName(a.el).slice(0, 30)}» a «${accessibleName(b.el).slice(0, 30)}»`);
    }
    for (const st of focusState.steps) {
      if (seen.has(st.el)) continue;
      seen.add(st.el);
      if (st.el.localName === 'iframe') continue;
      add(visibleR, st.changed, st.el, `sin indicador visible de foco («${accessibleName(st.el).slice(0, 40)}»)`);
      add(hiddenR, !st.obscured, st.el, `el foco queda tapado por un elemento fijo («${accessibleName(st.el).slice(0, 40)}»)`);
    }
    // Alcance: candidatos que deberían recibir el foco (si no completamos el ciclo, solo los anteriores al último alcanzado).
    const reachedList = focusState.steps.map((s) => s.el);
    const lastReached = reachedList[reachedList.length - 1];
    for (const el of focusState.candidates) {
      if (el.closest('iframe')) continue;
      let reached = seen.has(el) || reachedList.some((r) => r.contains(el) || el.contains(r));
      if (!reached && el.localName === 'input' && el.type === 'radio' && el.name) {
        reached = reachedList.some((r) => r.localName === 'input' && r.type === 'radio' && r.name === el.name && r.form === el.form);
      }
      if (!reached && !focusState.done && lastReached && (lastReached.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      add(reach, reached, el, `no se alcanza con Tab («${accessibleName(el).slice(0, 40)}»)`);
    }
    const trapped = info && info.trapped;
    add(trap, !trapped, trapped ? lastReached : document.body, 'el foco queda atrapado: Tab no avanza');
    if (info && info.hasMain && info.beforeMain >= 3) {
      const first = focusState.steps[0];
      add(skip, !!(first && first.skipTarget), first ? first.el : document.body,
        first ? `el primer elemento con foco es «${accessibleName(first.el).slice(0, 40)}», no un enlace para saltar al contenido` : 'sin elementos con foco');
    }
    return [visibleR, hiddenR, reach, trap, skip, order];
  }

  // ───────── movimiento ─────────
  function runningAnimations() {
    try {
      return document.getAnimations().filter((a) => {
        if (a.playState !== 'running') return false;
        const t = a.effect && a.effect.getTiming ? a.effect.getTiming() : {};
        const dur = typeof t.duration === 'number' ? t.duration : 0;
        return dur > 200 || t.iterations === Infinity;
      }).length;
    } catch (_) { return 0; }
  }

  globalThis.__uxh = { gcs, text, sel, visible, hiddenByAncestor, isDisabled, result, add, accessibleName,
    interactiveElements, textBlocks, overflowCulprits, INTERACTIVE_SEL, EMOJI };

  globalThis.__ux = {
    run(opts) {
      const mobile = !!opts.mobile; const desktop = !mobile;
      const out = [];
      const safe = (fn, ...a) => { try { out.push(...fn(...a)); } catch (e) { out.push({ id: '__error', d: String(e && e.message || e).slice(0, 200) }); } };
      safe(targets, mobile);
      safe(clickSemantics, desktop);
      safe(typography, mobile, desktop);
      safe(emojiIcons);
      safe(overflow, opts.viewport);
      safe(forms);
      safe(navigation, mobile, desktop);
      safe(images);
      return out;
    },
    prepareFocus, recordFocus, focusSummary, runningAnimations,
    reflow() { const w = window.innerWidth; const sw = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
      return { width: w, scrollWidth: sw, culprits: sw > w + 1 ? overflowCulprits(w) : [] }; },
    pageInfo() { return { title: (document.title || '').slice(0, 200), lang: document.documentElement.lang || '', url: location.href.slice(0, 2048) }; },
  };
  return true;
})();
