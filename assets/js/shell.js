/* ==========================================================================
   Shared application shell: sidebar, mobile navigation, footer.
   ========================================================================== */
'use strict';

const Shell = (() => {
  const NAV = [
    { href: '/', key: 'admin', label: 'Admin Panel', sub: 'Combined Dashboard', icon: 'grid' },
    { href: '/tressa', key: 'tressa', label: 'Tressa', sub: 'USA Medicare Training', icon: 'book' },
    { href: '/foundation', key: 'foundation', label: 'Foundation', sub: 'Health & Status', icon: 'home' },
    { href: '/playground', key: 'playground', label: 'Voice Playground', sub: 'Mic → Response Loop', icon: 'mic' },
    { href: '/analytics', key: 'analytics', label: 'Analytics', sub: 'Latency & Usage', icon: 'chart' },
  ];

  // Everything this project consumes from Deepgram lives in this one section.
  const DEEPGRAM_NAV = [
    { href: '/deepgram', key: 'deepgram', label: 'Compliance Overview', sub: 'Account • Agents • Voices', icon: 'bolt' },
    { href: '/agents', key: 'agents', label: 'Agent Studio', sub: 'Voice Agent Builder', icon: 'layers' },
    { href: '/lab', key: 'lab', label: 'Voice Lab', sub: 'STT • LLM • TTS', icon: 'flask' },
  ];

  const LIVEKIT_NAV = [
    { href: '/livekit', key: 'livekit', label: 'LiveKit Cloud', sub: 'Rooms • Dispatch • Tokens', icon: 'radio' },
    { href: '/livekit#builder', key: 'livekit-builder', label: 'Agent Builder', sub: 'Build & Deploy', icon: 'code' },
  ];

  const DELIVERY_NAV = [
    { href: '/testing', key: 'testing', label: 'Scenario Testing', sub: 'Regression & QA', icon: 'clipboard' },
    { href: '/security', key: 'security', label: 'Security', sub: 'Secrets & Retention', icon: 'shield' },
    { href: '/telephony', key: 'telephony', label: 'Telephony', sub: 'Mock SIP / VICIdial', icon: 'phone' },
    { href: '/docs', key: 'docs', label: 'Docs & Hardening', sub: 'Launch Checklist', icon: 'book' },
  ];

  const NAV_GROUPS = [
    { id: 'deepgram', label: 'Deepgram', items: DEEPGRAM_NAV, accent: true, accordion: true, toggle: 'Deepgram Compliance' },
    { id: 'livekit', label: 'LiveKit', items: LIVEKIT_NAV, accent: true, accordion: true, toggle: 'LiveKit Cloud' },
    { id: 'workspace', label: 'Workspace', items: NAV },
    { id: 'delivery', label: 'Quality & Delivery', items: DELIVERY_NAV },
  ];

  const ACCORDION_GROUPS = NAV_GROUPS.filter((g) => g.accordion);
  const ALL_NAV = [...NAV, ...DEEPGRAM_NAV, ...LIVEKIT_NAV, ...DELIVERY_NAV];
  const DG_KEYS = DEEPGRAM_NAV.map((item) => item.key);
  const LK_KEYS = LIVEKIT_NAV.map((item) => item.key);
  const ACCORDION_STORAGE = {
    deepgram: 'adriene.dgSectionOpen',
    livekit: 'adriene.lkSectionOpen',
  };

  const ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
    grid: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><path d="M12 17v5"/><path d="M8 22h8"/>',
    flask: '<path d="M9 3h6"/><path d="M10 3v6L4.5 19a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 9V3"/><path d="M7.5 14h9"/>',
    clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2"/><path d="m9 13 2 2 4-5"/>',
    chart: '<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="6" rx="1"/><rect x="12" y="7" width="3" height="10" rx="1"/><rect x="17" y="4" width="3" height="13" rx="1"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.7a2 2 0 0 1-.4 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.5 2.7.6a2 2 0 0 1 1.9 2.2Z"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1Z"/>',
    plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    play: '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4V8Z"/>',
    stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
    external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    check: '<path d="m20 6-11 11-5-5"/>',
    x: '<path d="m18 6-12 12"/><path d="m6 6 12 12"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 15H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    duplicate: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v12h14V8"/><path d="M10 12h4"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    'mic-off': '<path d="M2 2l20 20"/><path d="M9 9v3a3 3 0 0 0 5 2.2"/><path d="M15 9.3V5a3 3 0 0 0-5.9-.7"/><path d="M5 10a7 7 0 0 0 11 5.7"/><path d="M12 17v5"/><path d="M8 22h8"/>',
    volume: '<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>',
    'volume-off': '<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/>',
    sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
    server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>',
    code: '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    bot: '<rect x="3" y="8" width="18" height="12" rx="3"/><path d="M12 8V4"/><circle cx="8" cy="14" r="1"/><circle cx="16" cy="14" r="1"/><path d="M9 18h6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    wave: '<path d="M2 12h2l2-6 3 12 3-9 3 7 2-4h5"/>',
    phoneOut: '<path d="M14 2h6v6"/><path d="M22 2 11 13"/><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.7a2 2 0 0 1-.4 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.5 2.7.6a2 2 0 0 1 1.9 2.2Z"/>',
    git: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="m6 9v6a3 3 0 0 0 3 3h6"/><path d="M9 6h6a3 3 0 0 1 3 3v3"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    'chevron-up': '<path d="m18 15-6-6-6 6"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
    radio: '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.25a6 6 0 0 1 0-8.49M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
    moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/>',
    panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  };

  function icon(name, cls = '') {
    const body = ICONS[name] || ICONS.sparkles;
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="${cls}" aria-hidden="true">${body}</svg>`;
  }

  function navItem(item, active) {
    const isActive = item.key === active;
    return `<a href="${item.href}" class="nav-item ${isActive ? 'active' : ''}" ${isActive ? 'aria-current="page"' : ''}>
        <span class="nav-icon">${icon(item.icon)}</span>
        <span class="min-w-0 flex-1">
          <span class="nav-title nav-label-text">${item.label}</span>
          <span class="nav-sub nav-label-text">${item.sub}</span>
        </span>
        ${isActive ? '<span class="text-violet-300 text-[10px]">●</span>' : ''}
      </a>`;
  }

  // Each integration section is a single collapsible button: one click drops
  // the related pages down, the next click folds them back up.
  function accordionOpen(group, active) {
    const keys = group.items.map((item) => item.key);
    if (keys.includes(active)) return true;
    let stored = null;
    try { stored = localStorage.getItem(ACCORDION_STORAGE[group.id]); } catch { stored = null; }
    return stored === '1';
  }

  function accordionSection(group, active) {
    const open = accordionOpen(group, active);
    const keys = group.items.map((item) => item.key);
    const isActive = keys.includes(active);
    const first = group.items[0];
    return `
      <button class="nav-item nav-toggle ${isActive ? 'active' : ''}" type="button"
        data-accordion="${group.id}" aria-expanded="${open}" aria-controls="acc-${group.id}-items">
        <span class="nav-icon">${icon(first.icon)}</span>
        <span class="min-w-0 flex-1 text-left">
          <span class="nav-title nav-label-text">${group.toggle || group.label}</span>
          <span class="nav-sub nav-label-text">${group.items.map((i) => i.label).join(' • ')}</span>
        </span>
        <span class="nav-chevron" data-accordion-chevron>${icon(open ? 'chevron-up' : 'chevron')}</span>
      </button>
      <div class="dg-subitems ${open ? '' : 'hidden'}" id="acc-${group.id}-items">
        ${group.items.map((item) => navItem(item, active)).join('')}
      </div>`;
  }

  function navItems(active) {
    return NAV_GROUPS.map((group) => `
      <div class="nav-group ${group.accent ? 'nav-group-accent' : ''}">
        <div class="nav-group-label">${group.accent ? '<span class="status-dot"></span>' : ''}${group.label}</div>
        ${group.accordion ? accordionSection(group, active) : group.items.map((item) => navItem(item, active)).join('')}
      </div>`).join('');
  }

  function mobileItems(active) {
    return ALL_NAV.map((item) => `<a href="${item.href}" class="mobile-chip ${item.key === active ? 'active' : ''}">
      ${icon(item.icon, 'w-3 h-3')}<span>${item.label}</span>
    </a>`).join('');
  }

  function sidebar(active) {
    return `<aside class="sidebar fixed inset-y-0 left-0 z-40 hidden w-[268px] flex-col lg:flex">
      <div class="px-5 pt-6 pb-5">
        <a href="/" class="flex items-center gap-3 group">
          <div class="brand-mark"><img src="/assets/brand/bpo-nexus-icon.svg" alt="" width="28" height="28" /></div>
          <div class="min-w-0">
            <div class="brand-name">BPO <span class="nexus">NEXUS</span></div>
            <div class="brand-sub">Adriene Voice Playground</div>
          </div>
        </a>
        <div class="mt-4 flex items-center justify-between gap-2">
          <div class="flex min-w-0 items-center gap-2 text-[10.5px] text-slate-400">
            <span class="status-dot" id="shell-status-dot"></span>
            <span id="shell-status-text" class="truncate">Local • Secure • Telephony Off</span>
          </div>
          <div class="flex shrink-0 items-center gap-1.5">
            <button class="theme-toggle-btn" id="theme-toggle" type="button" title="Switch light / dark theme" aria-label="Switch theme">
              <span class="icon-sun">${icon('sun')}</span>
              <span class="icon-moon">${icon('moon')}</span>
            </button>
            <button class="nav-toggle-btn" id="nav-toggle" type="button" title="Collapse / expand the side panel" aria-label="Toggle side panel">
              ${icon('panel')}
            </button>
          </div>
        </div>
      </div>
      <nav class="flex-1 space-y-1 overflow-y-auto px-3 pb-4" aria-label="Main navigation">
        ${navItems(active)}
      </nav>
      <div class="nav-foot-text p-4 pt-0">
        <div class="px-1 text-[9px] leading-relaxed text-slate-500">
          Python stdlib API • SQLite persistence<br/>
          Windows 11 local • v1.0.0 • offline safe<br/>
          All audio stays on <span class="mono">localhost</span>.
        </div>
      </div>
    </aside>`;
  }

  function mobileHeader(active) {
    return `<header class="sticky top-0 z-40 border-b border-white/5 bg-[#0a0e1a] lg:hidden">
      <div class="flex items-center justify-between px-4 pt-3.5">
        <a href="/" class="flex items-center gap-2.5">
          <div class="brand-mark" style="width:34px;height:34px;border-radius:11px;"><img src="/assets/brand/bpo-nexus-icon-small.svg" alt="" width="22" height="22" /></div>
          <div>
            <div class="brand-name" style="font-size:12.5px;">BPO <span class="nexus">NEXUS</span></div>
            <div class="brand-sub" style="font-size:7px;letter-spacing:.18em;">Adriene Voice Playground</div>
          </div>
        </a>
        <div class="flex items-center gap-1.5">
          <button class="theme-toggle-btn" id="theme-toggle-m" type="button" title="Switch light / dark theme" aria-label="Switch theme">
            <span class="icon-sun">${icon('sun')}</span>
            <span class="icon-moon">${icon('moon')}</span>
          </button>
          <button class="nav-toggle-btn" id="sheet-toggle" type="button" title="Open the menu" aria-label="Open menu">
            ${icon('menu')}
          </button>
        </div>
      </div>
      <nav class="flex gap-1.5 overflow-x-auto px-4 py-3" aria-label="Mobile navigation">
        ${mobileItems(active)}
      </nav>
    </header>`;
  }

  function navSheet(active) {
    return `<div class="nav-sheet" id="nav-sheet" role="dialog" aria-modal="true" aria-label="Navigation">
      <div class="nav-sheet-panel">
        <div class="mb-3 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="brand-mark" style="width:34px;height:34px;border-radius:11px;"><img src="/assets/brand/bpo-nexus-icon-small.svg" alt="" width="22" height="22" /></div>
            <div class="brand-name" style="font-size:13px;">BPO <span class="nexus">NEXUS</span></div>
          </div>
          <button class="nav-toggle-btn" id="sheet-close" type="button" aria-label="Close menu">${icon('x')}</button>
        </div>
        ${navItems(active)}
      </div>
    </div>`;
  }

  function footer() {
    return `<footer class="mx-auto max-w-[1400px] px-5 pb-7 pt-2 sm:px-8 lg:px-10">
      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-5 text-[10px] text-slate-400">
        <div class="page-footer-brand">
          <span class="font-semibold" style="color:inherit">BPO Nexus by MMA Digital Labs</span>
          <span class="mx-1.5">•</span>
          <span>Adriene Voice Agent Playground</span>
          <span class="mx-1.5">•</span>
          <span>Windows 11 local</span>
          <span class="mx-1.5">•</span>
          <span>v1.0.0</span>
          <span class="mx-1.5">•</span>
          <span>offline safe</span>
          <span class="mx-1.5">•</span>
          <span>Telephony disabled by default</span>
        </div>
        <div class="flex items-center gap-3">
          <span class="inline-flex items-center gap-1">${icon('shield', 'w-3 h-3')} Secrets backend-only</span>
          <span class="inline-flex items-center gap-1">${icon('database', 'w-3 h-3')} SQLite</span>
        </div>
      </div>
    </footer>`;
  }

  async function mount(active) {
    const host = document.getElementById('sidebar');
    if (host) host.outerHTML = sidebar(active);
    const mobile = document.getElementById('mobile-shell');
    if (mobile) mobile.outerHTML = mobileHeader(active);
    const foot = document.getElementById('footer');
    if (foot) foot.outerHTML = footer();
    document.body.dataset.page = active;

    // Mobile navigation sheet (touch friendly).
    if (!document.getElementById('nav-sheet')) {
      const holder = document.createElement('div');
      holder.innerHTML = navSheet(active);
      document.body.appendChild(holder.firstElementChild);
    }
    const sheetEl = document.getElementById('nav-sheet');
    const openSheet = (open) => {
      document.body.dataset.sheet = open ? 'open' : 'closed';
    };
    const sheetToggle = document.getElementById('sheet-toggle');
    if (sheetToggle) sheetToggle.addEventListener('click', () => openSheet(true));
    const sheetClose = document.getElementById('sheet-close');
    if (sheetClose) sheetClose.addEventListener('click', () => openSheet(false));
    if (sheetEl) sheetEl.addEventListener('click', (event) => {
      if (event.target === sheetEl) openSheet(false);
    });

    // Theme (light / dark) - persisted, applied before first paint by the inline
    // bootstrap in each page.
    const applyTheme = (theme) => {
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('adriene.theme', theme); } catch { /* private mode */ }
    };
    let theme = 'dark';
    try { theme = localStorage.getItem('adriene.theme') || 'dark'; } catch { theme = 'dark'; }
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('#theme-toggle, #theme-toggle-m').forEach((btn) => {
      btn.addEventListener('click', () => {
        applyTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
      });
    });

    // Collapsible side panel (desktop): collapse to a rail, hover to peek open.
    let nav = 'expanded';
    try { nav = localStorage.getItem('adriene.nav') || 'expanded'; } catch { nav = 'expanded'; }
    document.body.dataset.nav = nav;
    const navToggle = document.getElementById('nav-toggle');
    if (navToggle) {
      navToggle.addEventListener('click', () => {
        const next = document.body.dataset.nav === 'collapsed' ? 'expanded' : 'collapsed';
        document.body.dataset.nav = next;
        try { localStorage.setItem('adriene.nav', next); } catch { /* private mode */ }
      });
    }

    // Integration accordions: drop the related pages down / fold them back up.
    document.querySelectorAll('[data-accordion]').forEach((toggle) => {
      toggle.addEventListener('click', () => {
        const group = toggle.dataset.accordion;
        const items = document.getElementById(`acc-${group}-items`);
        if (!items) return;
        const willOpen = items.classList.contains('hidden');
        items.classList.toggle('hidden', !willOpen);
        toggle.setAttribute('aria-expanded', String(willOpen));
        const chevron = toggle.querySelector('[data-accordion-chevron]');
        if (chevron) chevron.innerHTML = icon(willOpen ? 'chevron-up' : 'chevron');
        try { localStorage.setItem(ACCORDION_STORAGE[group], willOpen ? '1' : '0'); } catch { /* private mode */ }
      });
    });

    // Live status from the local API (never blocks the page).
    try {
      const health = await API.health();
      const text = document.getElementById('shell-status-text');
      if (text) text.textContent = `Local • Secure • Telephony ${health.telephony === 'disabled' ? 'Off' : 'On'}`;
      const version = document.getElementById('shell-version');
      if (version) version.textContent = `v${health.version}`;
      if (!health.ok) {
        const dot = document.getElementById('shell-status-dot');
        if (dot) { dot.style.background = '#f87171'; dot.style.boxShadow = '0 0 0 3px rgba(248,113,113,.15)'; }
      }
    } catch {
      const dot = document.getElementById('shell-status-dot');
      if (dot) { dot.style.background = '#f87171'; dot.style.boxShadow = '0 0 0 3px rgba(248,113,113,.15)'; }
      const text = document.getElementById('shell-status-text');
      if (text) text.textContent = 'API offline — start server.py';
    }
  }

  function header({ eyebrow, title, sub, right = '' }) {
    return `<div class="flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0">
        <div class="eyebrow">${eyebrow}</div>
        <h1 class="page-title">${title}</h1>
        <p class="page-sub">${sub}</p>
      </div>
      ${right ? `<div class="flex flex-wrap items-center gap-2 pt-1">${right}</div>` : ''}
    </div>`;
  }

  return { mount, icon, header, NAV };
})();

window.Shell = Shell;
