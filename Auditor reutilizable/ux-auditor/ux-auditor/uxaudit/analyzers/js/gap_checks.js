// UX-Auditor · comprobaciones de los «huecos» del estado del arte.
// Cubre lo que no evalúan Lighthouse, axe-core, WAVE ni Pa11y: patrones oscuros, banner de cookies,
// calidad (no solo presencia) de textos alternativos y nombres, multimedia, campos obligatorios,
// jerarquía de llamadas a la acción, texto justificado/mayúsculas, espaciado de texto y más.
// Se ejecuta en el mismo mundo aislado que dom_checks.js y reutiliza sus utilidades.
(() => {
  if (globalThis.__uxgap) return true;
  const H = globalThis.__uxh;
  if (!H) throw new Error('dom_checks.js no cargado');
  const { gcs, text, sel, visible, result, add, accessibleName, INTERACTIVE_SEL } = H;
  const norm = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

  // ───────── A11Y-NOMBRE-EN-ETIQUETA (WCAG 2.5.3) ─────────
  // axe-core tiene esta regla marcada como «experimental» y desactivada por defecto.
  function labelInName() {
    const r = result('A11Y-NOMBRE-EN-ETIQUETA');
    for (const el of H.interactiveElements().slice(0, 800)) {
      if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) continue;
      const visibleText = norm(text(el, 200));
      if (visibleText.length < 2 || !/\p{L}{2,}/u.test(visibleText)) continue; // solo iconos
      const name = norm(accessibleName(el));
      add(r, name.includes(visibleText), el, `texto visible «${visibleText.slice(0, 40)}» no está en el nombre accesible «${name.slice(0, 50)}»`);
    }
    return [r];
  }

  // ───────── A11Y-CALIDAD-ALT (WCAG 1.1.1, calidad) ─────────
  const ALT_FILE = /\.(jpe?g|png|gif|webp|avif|svg|bmp|tiff?)$/i;
  const ALT_CAMERA = /^(img|image|dsc|dscn|pxl|photo|foto|pic|screenshot|captura|whatsapp image)[\s_-]?\d/i;
  const ALT_GENERIC = new Set(['imagen', 'image', 'img', 'foto', 'fotografia', 'photo', 'picture', 'icono', 'icon', 'logo',
    'banner', 'grafico', 'graphic', 'spacer', 'untitled', 'sin titulo', 'placeholder', 'alt', 'thumbnail', 'miniatura', 'default']);
  const ALT_REDUNDANT = /^(imagen|foto|fotografia|image|photo|picture|grafico|icono) (de|del|of)\b/i;
  function altQuality() {
    const r = result('A11Y-CALIDAD-ALT');
    for (const img of Array.from(document.querySelectorAll('img[alt], input[type=image][alt], area[alt]')).slice(0, 600)) {
      const alt = (img.getAttribute('alt') || '').trim();
      if (!alt) continue;                      // alt="" = decorativa (correcto) o lo detecta axe
      if (img.localName === 'img' && !visible(img)) continue;
      const n = norm(alt);
      let problem = null;
      if (ALT_FILE.test(alt) || ALT_CAMERA.test(alt)) problem = 'parece un nombre de fichero';
      else if (ALT_GENERIC.has(n)) problem = 'es genérico y no describe la imagen';
      else if (ALT_REDUNDANT.test(n)) problem = 'empieza por «imagen de…», redundante para el lector de pantalla';
      else if (alt.length > 150) problem = `es demasiado largo (${alt.length} caracteres); usa una descripción larga aparte`;
      else if (/^[\W\d_]+$/u.test(alt)) problem = 'no contiene palabras';
      add(r, !problem, img, `alt="${alt.slice(0, 60)}": ${problem}`);
    }
    return [r];
  }

  // ───────── A11Y-MULTIMEDIA (WCAG 1.2.2, 1.4.2, 2.2.2) ─────────
  function media() {
    const r = result('A11Y-MULTIMEDIA');
    for (const v of Array.from(document.querySelectorAll('video, audio')).slice(0, 50)) {
      if (v.localName === 'video' && !visible(v)) continue;
      const autoplay = v.autoplay || v.hasAttribute('autoplay');
      const muted = v.muted || v.hasAttribute('muted');
      const controls = v.hasAttribute('controls');
      const captions = !!v.querySelector('track[kind=captions], track[kind=subtitles]');
      const problems = [];
      if (autoplay && !muted) problems.push('se reproduce solo con sonido');
      if (autoplay && !controls) problems.push('se mueve sola sin controles para pausar');
      if (!controls && !autoplay) problems.push('no tiene controles');
      if (v.localName === 'video' && !muted && !captions) problems.push('no tiene subtítulos (<track kind="captions">)');
      add(r, problems.length === 0, v, `<${v.localName}> ${problems.join(', ')}`);
    }
    for (const f of Array.from(document.querySelectorAll('iframe[src]')).slice(0, 50)) {
      const src = f.getAttribute('src') || '';
      if (!/youtube|youtu\.be|vimeo|dailymotion|twitch/i.test(src)) continue;
      const auto = /[?&]autoplay=1/i.test(src);
      const mute = /[?&](mute|muted)=1/i.test(src);
      add(r, !(auto && !mute), f, 'vídeo incrustado con reproducción automática y sonido');
    }
    return [r];
  }

  // ───────── FORM-OBLIGATORIOS (WCAG 3.3.2 / 1.3.1) ─────────
  const REQ_TEXT = /(\*|obligatori|requerid|required|necesari)/i;
  function requiredFields() {
    const r = result('FORM-OBLIGATORIOS');
    const fields = Array.from(document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea'))
      .filter((el) => visible(el)).slice(0, 400);
    for (const el of fields) {
      const programmatic = el.required || el.getAttribute('aria-required') === 'true';
      const labelText = el.labels ? Array.from(el.labels).map((l) => text(l, 200)).join(' ') : '';
      const form = el.form || el.closest('form, fieldset');
      const legendNote = form ? REQ_TEXT.test(text(form.querySelector('legend, p, .note, .ayuda, small') || null, 300)) &&
        /(todos|all)\b/i.test(text(form, 2000)) : false;
      const visual = REQ_TEXT.test(labelText) || legendNote;
      if (programmatic && !visual) add(r, false, el, `campo obligatorio sin indicarlo en la etiqueta («${labelText.slice(0, 40)}»)`);
      else if (!programmatic && /\*/.test(labelText)) add(r, false, el, `la etiqueta marca * pero el campo no tiene required ni aria-required («${labelText.slice(0, 40)}»)`);
      else if (programmatic || /\*/.test(labelText)) add(r, true, el, '');
    }
    return [r];
  }

  // ───────── VIS-TEXTO-COGNITIVO (WCAG 1.4.8 AAA · COGA) ─────────
  function cognitiveText() {
    const r = result('VIS-TEXTO-COGNITIVO');
    for (const { el, len } of H.textBlocks()) {
      if (len < 60) continue;
      const s = gcs(el);
      const t = text(el, 400);
      const letters = t.replace(/[^\p{L}]/gu, '');
      const caps = s.textTransform === 'uppercase' || (letters.length > 30 && letters === letters.toUpperCase());
      const justified = s.textAlign === 'justify' && len >= 80;
      const italicLong = s.fontStyle === 'italic' && len >= 200;
      const problems = [justified && 'texto justificado (ríos de espacios)', caps && 'bloque largo en MAYÚSCULAS',
        italicLong && 'párrafo largo en cursiva'].filter(Boolean);
      add(r, problems.length === 0, el, `${problems.join(', ')}: «${t.slice(0, 50)}»`);
    }
    return [r];
  }

  // ───────── INT-CTA-COMPITEN (ley de Hick · jerarquía visual) ─────────
  function isFilled(el) {
    const bg = gcs(el).backgroundColor;
    const m = bg.match(/rgba?\(([^)]+)\)/);
    if (!m) return false;
    const parts = m[1].split(',').map((x) => parseFloat(x));
    return parts.length < 4 || parts[3] > 0.5;
  }
  function ctaCompetition() {
    const vh = window.innerHeight;
    const ctas = [];
    for (const el of Array.from(document.querySelectorAll('a[href], button, input[type=submit], [role=button]')).slice(0, 600)) {
      if (!visible(el)) continue;
      const rc = el.getBoundingClientRect();
      if (rc.top + window.scrollY > vh || rc.width * rc.height < 1200) continue;
      if (el.closest('nav, [role=navigation], header nav')) continue;
      if (!isFilled(el)) continue;
      const parentBg = el.parentElement ? gcs(el.parentElement).backgroundColor : '';
      if (gcs(el).backgroundColor === parentBg) continue;
      ctas.push({ el, bg: gcs(el).backgroundColor, label: norm(accessibleName(el)).slice(0, 40) });
    }
    const groups = new Map();
    for (const c of ctas) { if (!groups.has(c.bg)) groups.set(c.bg, new Map()); groups.get(c.bg).set(c.label, c.el); }
    let worst = null;
    for (const [, labels] of groups) if (!worst || labels.size > worst.size) worst = labels;
    const n = worst ? worst.size : 0;
    const value = n <= 2 ? 1 : (n === 3 ? 0.5 : 0);
    return [{ id: 'INT-CTA-COMPITEN', value: ctas.length ? value : null, measured: `${n} llamadas a la acción con el mismo peso visual en la primera pantalla`,
      items: value < 1 ? Array.from(worst.entries()).slice(0, 8).map(([l, e]) => ({ s: sel(e), d: `CTA «${l}» compite con otras ${n - 1} iguales` })) : [] }];
  }

  // ───────── Patrones oscuros (DSA art. 25 · AEPD · Directiva 2005/29/CE) ─────────
  const ACCEPT = /\b(aceptar|acepto|aceptar todo|aceptar todas|accept|accept all|allow|allow all|permitir|permitir todas|de acuerdo|agree|consentir|entendido|vale|ok|got it)\b/i;
  const REJECT = /\b(rechazar|rechazo|rechazar todo|rechazar todas|reject|reject all|deny|denegar|decline|no acepto|no aceptar|solo (las )?necesarias|s[oó]lo (las )?necesarias|only necessary|necessary only|essential only|solo esenciales|continuar sin aceptar|refuse|no,? gracias)\b/i;
  const CONSENT_CONTAINER = /(cookie|consent|gdpr|cmp|didomi|onetrust|cookiebot|usercentrics|iubenda|quantcast|privacy|privacidad|galleta)/i;

  function cookieBanner() {
    const r = { id: 'ETI-COOKIES-RECHAZO', value: null, measured: 'sin banner de cookies', items: [] };
    const candidates = Array.from(document.querySelectorAll('div, section, aside, dialog, [role=dialog], [role=alertdialog], form, footer')).filter((el) => {
      if (!visible(el)) return false;
      const marker = `${el.id} ${el.className && el.className.baseVal === undefined ? el.className : ''} ${el.getAttribute('aria-label') || ''}`;
      const s = gcs(el);
      const floating = s.position === 'fixed' || s.position === 'sticky' || el.localName === 'dialog' || /dialog/.test(el.getAttribute('role') || '');
      const t = text(el, 1500);
      return (CONSENT_CONTAINER.test(marker) || floating) && /(cookie|galleta|consentimiento|consent)/i.test(t) && t.length < 3000;
    });
    if (!candidates.length) return [r];
    // el contenedor más interior que siga teniendo botones
    candidates.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
    const banner = candidates.find((c) => c.querySelector('button, a, [role=button], input[type=button], input[type=submit]'));
    if (!banner) return [r];
    const controls = Array.from(banner.querySelectorAll('button, a, [role=button], input[type=button], input[type=submit]')).filter(visible);
    const accept = controls.find((c) => ACCEPT.test(accessibleName(c)) && !REJECT.test(accessibleName(c)));
    const reject = controls.find((c) => REJECT.test(accessibleName(c)));
    if (!accept) { r.measured = 'banner sin botón de aceptar identificable'; return [r]; }
    if (!reject) {
      r.value = 0; r.measured = 'banner con «Aceptar» pero sin «Rechazar» en la primera capa';
      r.items = [{ s: sel(banner), d: `Botón «${accessibleName(accept).slice(0, 30)}» sin opción equivalente para rechazar` }];
      return [r];
    }
    const a = accept.getBoundingClientRect(), b = reject.getBoundingClientRect();
    const areaRatio = (b.width * b.height) / Math.max(1, a.width * a.height);
    const fs = parseFloat(gcs(reject).fontSize) / Math.max(1, parseFloat(gcs(accept).fontSize));
    const fillDiff = isFilled(accept) && !isFilled(reject);
    const problems = [];
    if (areaRatio < 0.6) problems.push(`«Rechazar» ocupa el ${Math.round(areaRatio * 100)} % del área de «Aceptar»`);
    if (fs < 0.9) problems.push('«Rechazar» tiene letra más pequeña');
    if (fillDiff) problems.push('«Aceptar» está destacado (relleno) y «Rechazar» no');
    r.value = problems.length === 0 ? 1 : (problems.length === 1 ? 0.5 : 0);
    r.measured = problems.length ? problems.join('; ') : 'aceptar y rechazar con el mismo peso visual';
    r.items = problems.length ? [{ s: sel(reject), d: problems.join('; ') }] : [];
    return [r];
  }

  const OPT_IN = /(newsletter|bolet[ií]n|publicidad|comercial|marketing|ofertas|promoci|terceros|partners|socios|novedades|suscrib|subscribe|personaliz|anal[ií]tic|seguimiento|tracking|advertis|anuncios|perfil)/i;
  function preselection() {
    const r = result('ETI-PRESELECCION');
    const boxes = Array.from(document.querySelectorAll('input[type=checkbox], [role=switch], [role=checkbox]')).slice(0, 300);
    for (const el of boxes) {
      const label = norm(accessibleName(el) || (el.closest('label') ? text(el.closest('label'), 200) : ''));
      if (!OPT_IN.test(label)) continue;
      if (/(necesari|esencial|tecnica|essential|strictly)/i.test(label)) continue;
      const checked = el.checked === true || el.getAttribute('aria-checked') === 'true';
      add(r, !checked, el, `casilla premarcada: «${label.slice(0, 60)}»`);
    }
    return [r];
  }

  const SHAME = /(no,? gracias,? (no|prefiero|me gusta|quiero|odio)|prefiero (pagar|seguir pagando|perder|no ahorrar|quedarme sin)|no me importa (perder|pagar|mi)|no quiero (ahorrar|descuentos|ofertas|mejorar|estar informad|ganar)|soy (rico|millonari)|no,? (me gusta|prefiero) pagar|me gusta pagar|renuncio a|i (don.?t|do not) (want|like) (to save|savings|deals|discounts)|no thanks,? i|i prefer (paying|to pay)|i.?m not interested in (saving|improving)|i.?ll pay full price|no,? i (hate|don.?t care)|i don.?t care about)/i;
  function confirmshaming() {
    const r = result('ETI-CONFIRMSHAMING');
    for (const el of Array.from(document.querySelectorAll('button, a, [role=button], input[type=button], input[type=submit], label')).slice(0, 1500)) {
      if (!visible(el)) continue;
      const t = accessibleName(el).trim();
      if (!t || t.length > 120) continue;
      const decline = /^(no|nope|skip|omitir|cerrar|close|ahora no|not now|m[aá]s tarde|later|quiz[aá]s)/i.test(t) || /(gracias|thanks)/i.test(t);
      if (!decline && !SHAME.test(t)) continue;
      add(r, !SHAME.test(t), el, `texto que culpabiliza al rechazar: «${t.slice(0, 80)}»`);
    }
    return [r];
  }

  const URGENCY = /((oferta|promoci[oó]n|descuento|precio|rebaja|deal|sale|offer).{0,40}(termina|acaba|expira|caduca|ends|expires)|termina en \d|acaba en \d|quedan? (s[oó]lo )?\d+ (unidades|plazas|habitaciones|entradas|left)|s[oó]lo quedan|[uú]ltimas? \d+ (unidades|plazas)|\d+ personas? (est[aá]n? viendo|lo est[aá]n? mirando|han comprado|han reservado)|only \d+ left|\d+ (people|others) (are )?(viewing|looking|watching)|ends in \d|hurry|date prisa|[uú]ltimas horas|last chance|[uú]ltima oportunidad|alta demanda|high demand)/i;
  const CLOCK = /\b\d{1,2}\s*[:hH]\s*\d{2}(\s*[:mM]\s*\d{2})?\b/;
  let clocks = null;
  function urgencyStart() {
    clocks = new Map();
    for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 6000)) {
      if (el.children.length > 6) continue;
      const t = text(el, 60);
      if (t && CLOCK.test(t) && visible(el)) clocks.set(el, t);
    }
    return clocks.size;
  }
  function urgencyEnd() {
    const r = { id: 'ETI-URGENCIA', value: 1, measured: 'sin mensajes de urgencia o escasez', items: [] };
    const hits = [];
    for (const [el, before] of clocks || []) {
      if (!el.isConnected) continue;
      const now = text(el, 60);
      if (now !== before && CLOCK.test(now) && !el.closest('[role=timer][aria-live]')) hits.push({ s: sel(el), d: `cuenta atrás: «${before}» → «${now}»` });
    }
    for (const { el } of H.textBlocks()) {
      const t = text(el, 300);
      if (URGENCY.test(t)) hits.push({ s: sel(el), d: `mensaje de presión: «${t.slice(0, 80)}»` });
      if (hits.length > 20) break;
    }
    const n = hits.length;
    if (n) { r.value = n === 1 ? 0.5 : 0; r.measured = `${n} elementos de urgencia o escasez (posible patrón oscuro: verifica que son reales)`; r.items = hits.slice(0, 15); }
    return [r];
  }


  // ───────── Steve Krug · «No me hagas pensar» ─────────
  // Prueba del tronco (trunk test): ¿qué sitio es?, ¿en qué página estoy?, ¿cuáles son las secciones?,
  // ¿dónde estoy dentro del sitio?, ¿cómo busco? (la búsqueda solo se exige en sitios con mucho contenido).
  function trunkTest() {
    const missing = [];
    const header = document.querySelector('header, [role=banner]');
    const topLinks = Array.from(document.querySelectorAll('a[href]')).filter((a) => visible(a) && a.getBoundingClientRect().top + window.scrollY < 200);
    const homeLike = (a) => {
      try {
        const u = new URL(a.getAttribute('href'), location.href);
        const here = new URL(location.href);
        return u.origin === here.origin && (u.pathname === '/' || /\/(index|inicio|home)\.(html?|php)$/i.test(u.pathname) ||
          u.pathname === here.pathname.replace(/[^/]*$/, ''));
      } catch (_) { return false; }
    };
    const brand = (a) => /(logo|brand|marca|site-?title|site-?name|navbar-brand)/i.test(`${a.id} ${typeof a.className === 'string' ? a.className : ''}`) ||
      !!a.querySelector('img, svg, [class*=logo]');
    const siteId = (header ? Array.from(header.querySelectorAll('a[href]')).filter(visible) : topLinks).some((a) => brand(a) || homeLike(a));
    if (!siteId) missing.push('¿Qué sitio es? Falta un logotipo o nombre del sitio enlazado a la portada en la cabecera');
    const h1 = Array.from(document.querySelectorAll('h1')).find((h) => visible(h) && text(h).length > 2);
    if (!h1) missing.push('¿En qué página estoy? Falta un título de página visible (h1)');
    const nav = Array.from(document.querySelectorAll('nav, [role=navigation]')).find((n) => visible(n) && n.querySelectorAll('a[href]').length >= 2);
    if (!nav) missing.push('¿Cuáles son las secciones principales? Falta una navegación principal visible');
    else {
      const navLinks = Array.from(nav.querySelectorAll('a[href]')).filter(visible);
      const marked = navLinks.some((a) => a.hasAttribute('aria-current') && a.getAttribute('aria-current') !== 'false') ||
        navLinks.some((a) => /(^|\s)(active|current|selected|is-active|activo|actual)(\s|$)/i.test(`${typeof a.className === 'string' ? a.className : ''} ${a.parentElement && typeof a.parentElement.className === 'string' ? a.parentElement.className : ''}`)) ||
        !!document.querySelector('nav[aria-label*=breadcrumb i], nav[aria-label*=migas i], .breadcrumb, [itemtype*=BreadcrumbList]');
      if (!marked) missing.push('¿Dónde estoy? El menú no marca la sección actual (aria-current) ni hay migas de pan');
    }
    const manyLinks = document.querySelectorAll('a[href]').length > 40;
    const search = document.querySelector('input[type=search], [role=search], search, form[action*=search i], form[action*=busca i], input[name=q], input[name=s], input[name*=search i], input[name*=busca i]');
    if (manyLinks && !search) missing.push('¿Cómo busco? Un sitio con tanto contenido necesita un buscador visible');
    const total = manyLinks ? 5 : 4;
    const value = missing.length === 0 ? 1 : (missing.length === 1 ? 0.5 : 0);
    return [{ id: 'NAV-PRUEBA-TRONCO', value, measured: `prueba del tronco: ${total - missing.length} de ${total} preguntas respondidas a simple vista`,
      items: missing.map((d) => ({ s: 'body', d })) }];
  }

  // «No me castigues por no hacerlo a tu manera»: formatos rígidos en teléfonos, tarjetas y códigos.
  const FORMAT_CASES = [
    [/(tel|phone|movil|móvil|telefono|teléfono|celular)/i, '600123456', ['600 123 456', '600-123-456', '+34 600 123 456'], 'teléfono'],
    [/(card|tarjeta|cc-?num)/i, '4111111111111111', ['4111 1111 1111 1111', '4111-1111-1111-1111'], 'tarjeta'],
    [/(iban|cuenta)/i, 'ES9121000418450200051332', ['ES91 2100 0418 4502 0005 1332'], 'IBAN'],
  ];
  function formatPunish() {
    const r = result('FORM-FORMATO-LIBRE');
    for (const el of Array.from(document.querySelectorAll('input')).filter(visible).slice(0, 300)) {
      const hint = `${el.type} ${el.name} ${el.id} ${el.getAttribute('autocomplete') || ''} ${el.labels ? Array.from(el.labels).map((l) => text(l, 60)).join(' ') : ''}`;
      const kind = FORMAT_CASES.find(([re]) => re.test(hint) || (re.source.startsWith('(tel') && el.type === 'tel'));
      if (!kind) continue;
      const [, plain, formatted, label] = kind;
      const problems = [];
      const pattern = el.getAttribute('pattern');
      if (pattern) {
        let re = null;
        try { re = new RegExp(`^(?:${pattern})$`, 'v'); } catch (_) { try { re = new RegExp(`^(?:${pattern})$`, 'u'); } catch (__) { re = null; } }
        if (re && re.test(plain) && !formatted.some((f) => re.test(f))) problems.push(`el patrón rechaza «${formatted[0]}» con espacios o guiones`);
      }
      const max = parseInt(el.getAttribute('maxlength') || '0', 10);
      if (max > 0 && max < formatted[0].length) problems.push(`maxlength=${max} no deja escribir «${formatted[0]}»`);
      if (!pattern && !max) continue;
      add(r, problems.length === 0, el, `${label}: ${problems.join('; ')}`);
    }
    return [r];
  }

  // «Omite las palabras innecesarias»: texto de bienvenida (happy talk) e instrucciones que nadie lee.
  const HAPPY = /^(bienvenid[oa]s? (a|al)\b|te damos la bienvenida|nos complace|estamos encantados|welcome to\b|we are (proud|delighted|pleased)|somos (una|un) (empresa|equipo|referente) (l[ií]der|joven|din[aá]mic))/i;
  const INSTRUCTIONS = /\b(haga|haz|pulse|pulsa|click|clic) (clic )?(aqu[ií]|en (el|este) (bot[oó]n|enlace))|\bclick (here|the button below)\b|para continuar,? (haga|haz|pulse|pulsa)/i;
  function happyTalk() {
    const hits = [];
    const els = Array.from(document.querySelectorAll('h1, h2, h3, main p, main li, p')).filter(visible).slice(0, 400);
    for (const el of els) {
      const t = text(el, 300);
      if (HAPPY.test(t)) hits.push({ s: sel(el), d: `texto de bienvenida que no aporta información: «${t.slice(0, 70)}»` });
      else if (INSTRUCTIONS.test(t)) hits.push({ s: sel(el), d: `instrucciones innecesarias: «${t.slice(0, 70)}»` });
      if (hits.length >= 10) break;
    }
    const n = hits.length;
    return [{ id: 'VIS-PALABRAS-INNECESARIAS', value: n === 0 ? 1 : (n === 1 ? 0.5 : 0),
      measured: n ? `${n} fragmentos de texto innecesario (Krug: «omite las palabras innecesarias»)` : 'sin texto de relleno detectado', items: hits }];
  }


  // Krug «que lo clicable sea evidente» + WCAG 1.4.1: enlaces dentro del texto distinguibles sin depender solo del color.
  function parseRGB(c) { const m = (c || '').match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return p.slice(0, 3); }
  function lum(rgb) { return rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); })
    .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0); }
  function ratio(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function linkDistinct() {
    const r = result('INT-ENLACES-DISTINGUIBLES');
    for (const a of Array.from(document.querySelectorAll('p a[href], li a[href], td a[href], dd a[href], blockquote a[href], figcaption a[href]')).slice(0, 600)) {
      if (!visible(a)) continue;
      const block = a.closest('p, li, td, dd, blockquote, figcaption');
      if (!block || text(block, 2000).length <= text(a, 2000).length + 10) continue;   // no es un enlace dentro de texto
      const sa = gcs(a), sb = gcs(block);
      const underline = /underline/.test(sa.textDecorationLine) || (parseFloat(sa.borderBottomWidth) > 0 && sa.borderBottomStyle !== 'none');
      const weight = Math.abs((parseInt(sa.fontWeight, 10) || 400) - (parseInt(sb.fontWeight, 10) || 400)) >= 300;
      const bg = sa.backgroundColor !== sb.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(sa.backgroundColor);
      const ca = parseRGB(sa.color), cb = parseRGB(sb.color);
      const contrast = ca && cb ? ratio(ca, cb) : 21;
      add(r, underline || weight || bg || contrast >= 3, a,
        `enlace «${text(a, 40)}» sin subrayar y con contraste ${contrast.toFixed(2)}:1 respecto al texto (mínimo 3:1)`);
    }
    return [r];
  }

  // ───────── datos para análisis en Python ─────────
  function readabilityText() {
    const root = document.querySelector('main, [role=main], article') || document.body;
    const parts = [];
    let total = 0;
    for (const el of root.querySelectorAll('p, li, dd, blockquote, td, figcaption, h1, h2, h3')) {
      if (!visible(el) || el.closest('nav, footer, [role=navigation], [aria-hidden=true]')) continue;
      const t = text(el, 4000);
      if (t.split(/\s+/).length < 6) continue;
      parts.push(/[.!?…:;]$/.test(t) ? t : t + '.');
      total += t.length;
      if (total > 30000) break;
    }
    return { lang: (document.documentElement.lang || '').slice(0, 10).toLowerCase(), text: parts.join(' ').slice(0, 30000) };
  }

  const HELP = /(contacto|contact|ayuda|help|soporte|support|faq|preguntas frecuentes|atenci[oó]n al cliente|chat)/i;
  function navSignature() {
    const nav = Array.from(document.querySelectorAll('header nav, nav, [role=navigation]')).find((n) => visible(n) && !n.closest('footer'));
    const links = nav ? Array.from(nav.querySelectorAll('a[href]')).filter(visible).map((a) => norm(accessibleName(a)).slice(0, 40)).filter(Boolean).slice(0, 40) : [];
    const all = Array.from(document.querySelectorAll('header a[href], nav a[href], footer a[href]')).filter(visible).map((a) => norm(accessibleName(a)).slice(0, 40));
    const help = all.filter((t) => HELP.test(t));
    return { links, help: help.slice(0, 5), helpPos: help.length ? all.indexOf(help[0]) / Math.max(1, all.length) : null };
  }

  // ───────── espaciado de texto y tamaño de letra del usuario ─────────
  let clipBase = null;
  function clippedNow() {
    const out = new Map();
    for (const { el } of H.textBlocks().slice(0, 2500)) {
      let box = el;
      for (let i = 0; i < 4 && box && box !== document.body; i++, box = box.parentElement) {
        const s = gcs(box);
        const scrollable = /(auto|scroll)/.test(s.overflowY) || /(auto|scroll)/.test(s.overflowX);
        if (scrollable) break;                       // el contenido sigue siendo accesible con scroll
        // Alto fijo: el texto se recorta (overflow hidden) o se desborda y se solapa (overflow visible).
        const vSpill = box.clientHeight > 0 && box.scrollHeight > box.clientHeight + 3;
        const hSpill = /(hidden|clip)/.test(s.overflowX) && box.scrollWidth > box.clientWidth + 3;
        if (vSpill || hSpill) {
          out.set(box, `${vSpill ? box.scrollHeight : box.scrollWidth}px de contenido en ${vSpill ? box.clientHeight : box.clientWidth}px`);
          break;
        }
        if (s.textOverflow === 'ellipsis' && box.scrollWidth > box.clientWidth + 1) { out.set(box, 'texto cortado con «…»'); break; }
      }
    }
    return out;
  }
  function clipStart() { clipBase = clippedNow(); return clipBase.size; }
  function clipEnd(ruleId) {
    const r = result(ruleId);
    const now = clippedNow();
    const blocks = H.textBlocks().filter((b) => b.len >= 3).length;
    r.total = Math.max(blocks, 1);
    r.passed = r.total;
    for (const [box, detail] of now) {
      if (clipBase && clipBase.has(box)) continue;
      r.passed = Math.max(0, r.passed - 1);
      if (r.items.length < 25) r.items.push({ s: sel(box), d: `texto cortado o solapado: ${detail} («${text(box, 40)}»)` });
    }
    return [r];
  }
  function textSize() {
    const sizes = [];
    for (const { el, len } of H.textBlocks()) if (len >= 20) sizes.push([parseFloat(gcs(el).fontSize) || 16, len]);
    if (!sizes.length) return null;
    sizes.sort((a, b) => a[0] - b[0]);
    const half = sizes.reduce((a, [, c]) => a + c, 0) / 2;
    let acc = 0;
    for (const [fs, c] of sizes) { acc += c; if (acc >= half) return fs; }
    return sizes[sizes.length - 1][0];
  }
  function backgroundSignature() {
    const pick = (el) => (el ? `${gcs(el).backgroundColor}|${gcs(el).color}` : '');
    return [pick(document.documentElement), pick(document.body), pick(document.querySelector('main, [role=main]')),
      pick(document.querySelector('header'))].join('#');
  }
  function visibleTextLength() {
    let n = 0;
    for (const { len } of H.textBlocks()) n += len;
    const rotate = Array.from(document.querySelectorAll('body *')).slice(0, 4000).some((el) =>
      el.children.length < 4 && /(gira|rota|voltea|rotate|turn) (tu|el|your|the)? ?(dispositivo|m[oó]vil|tel[eé]fono|device|phone|pantalla|screen)/i.test(text(el, 120)) && visible(el));
    return { chars: n, rotate };
  }

  globalThis.__uxgap = {
    run(opts) {
      const out = [];
      const safe = (fn) => { try { out.push(...fn()); } catch (e) { out.push({ id: '__error', d: String(e && e.message || e).slice(0, 200) }); } };
      [labelInName, altQuality, media, requiredFields, cognitiveText, ctaCompetition, cookieBanner, preselection, confirmshaming,
        trunkTest, formatPunish, happyTalk, linkDistinct].forEach(safe);
      return out;
    },
    urgencyStart, urgencyEnd, readabilityText, navSignature, clipStart, clipEnd, textSize, backgroundSignature, visibleTextLength,
  };
  return true;
})();
