/* global pywebview, RGC_CATALOG */

(function () {
  "use strict";

  const state = {
    creations: [],
    active: null,
    focused: "form",
    open: { form: true, viewer: false, library: false, control: false, "image-edit": false, "video-edit": false, "prompt-editor": false },
    minimized: { form: false, viewer: false, library: false, control: false, "image-edit": false, "video-edit": false, "prompt-editor": false },
    maximized: { form: false, viewer: false, library: false, control: false, "image-edit": false, "video-edit": false, "prompt-editor": false },
    // Back → front. Focus moves a window to the end; others keep their relative order.
    windowZOrder: ["form", "viewer", "library", "control", "image-edit", "video-edit", "prompt-editor"],
    preMaximizeRect: {},
    generating: false,
    soundEnabled: true,
    soundVolume: 100,
    crtEnabled: false,
    uiScale: 1,
    uiFont: "inter",
    uiFontSize: 13,
    retiredGeminiModels: [],
    config: null,
    viewerTab: "doc",
    speechPlaying: false,
    settingsPage: "models",
    archiveSort: { key: "created", dir: "desc" },
    presets: [],
    creationTypes: [],
    studioBasis: null, // { creationId, modality, fileUrl, mimeType, title, layout }
    studioBasisWidth: 280, // persisted as ui.studio_basis_width
    studioTools: [], // selected Gemini tool aliases for this session
    geminiToolsCatalog: null, // from bootstrap / list_gemini_tools
    studioAddToolOpen: false,
    studioEnableTools: false,
    savedPrompts: [],
    promptEditor: {
      selectedId: "",
      editing: false,
      snapshotName: "",
      snapshotBody: "",
    },
    studioCaret: { fieldId: "studio-prompt", start: 0, end: 0 },
    appTheme: "light",
    customTheme: {
      desktopColor: "#ffffff",
      windowColor: "#ffffff",
      titleColor: "#000000",
      textColor: "#000000",
      font: "sans",
    },
  };

  /**
   * Open-source UI fonts loaded from Bunny Fonts (Google Fonts mirror) on demand.
   */
  const UI_FONTS = {
    inter: {
      label: "Inter",
      stack: 'Inter, "Segoe UI", Tahoma, sans-serif',
      google: "Inter:400,700",
    },
    roboto: {
      label: "Roboto",
      stack: 'Roboto, "Segoe UI", Tahoma, sans-serif',
      google: "Roboto:400,700",
    },
    "open-sans": {
      label: "Open Sans",
      stack: '"Open Sans", "Segoe UI", Tahoma, sans-serif',
      google: "Open+Sans:400,700",
    },
    lato: {
      label: "Lato",
      stack: 'Lato, "Segoe UI", Tahoma, sans-serif',
      google: "Lato:400,700",
    },
    montserrat: {
      label: "Montserrat",
      stack: 'Montserrat, "Segoe UI", Tahoma, sans-serif',
      google: "Montserrat:400,700",
    },
    "source-sans-3": {
      label: "Source Sans 3",
      stack: '"Source Sans 3", "Segoe UI", Tahoma, sans-serif',
      google: "Source+Sans+3:400,700",
    },
    nunito: {
      label: "Nunito",
      stack: 'Nunito, "Segoe UI", Tahoma, sans-serif',
      google: "Nunito:400,700",
    },
    poppins: {
      label: "Poppins",
      stack: 'Poppins, "Segoe UI", Tahoma, sans-serif',
      google: "Poppins:400,700",
    },
    raleway: {
      label: "Raleway",
      stack: 'Raleway, "Segoe UI", Tahoma, sans-serif',
      google: "Raleway:400,700",
    },
    ubuntu: {
      label: "Ubuntu",
      stack: 'Ubuntu, "Segoe UI", Tahoma, sans-serif',
      google: "Ubuntu:400,700",
    },
    "noto-sans": {
      label: "Noto Sans",
      stack: '"Noto Sans", "Segoe UI", Tahoma, sans-serif',
      google: "Noto+Sans:400,700",
    },
    "work-sans": {
      label: "Work Sans",
      stack: '"Work Sans", "Segoe UI", Tahoma, sans-serif',
      google: "Work+Sans:400,700",
    },
    "ibm-plex-sans": {
      label: "IBM Plex Sans",
      stack: '"IBM Plex Sans", "Segoe UI", Tahoma, sans-serif',
      google: "IBM+Plex+Sans:400,700",
    },
    "pt-sans": {
      label: "PT Sans",
      stack: '"PT Sans", "Segoe UI", Tahoma, sans-serif',
      google: "PT+Sans:400,700",
    },
    "fira-sans": {
      label: "Fira Sans",
      stack: '"Fira Sans", "Segoe UI", Tahoma, sans-serif',
      google: "Fira+Sans:400,700",
    },
    rubik: {
      label: "Rubik",
      stack: 'Rubik, "Segoe UI", Tahoma, sans-serif',
      google: "Rubik:400,700",
    },
    "dm-sans": {
      label: "DM Sans",
      stack: '"DM Sans", "Segoe UI", Tahoma, sans-serif',
      google: "DM+Sans:400,700",
    },
    "libre-franklin": {
      label: "Libre Franklin",
      stack: '"Libre Franklin", "Segoe UI", Tahoma, sans-serif',
      google: "Libre+Franklin:400,700",
    },
    merriweather: {
      label: "Merriweather",
      stack: 'Merriweather, Georgia, "Times New Roman", serif',
      google: "Merriweather:400,700",
    },
    "source-serif-4": {
      label: "Source Serif 4",
      stack: '"Source Serif 4", Georgia, "Times New Roman", serif',
      google: "Source+Serif+4:400,700",
    },
  };

  // Legacy stacks for Viewer document themes (not app chrome)
  const UI_FONT_STACKS = {
    sans: UI_FONTS.inter.stack,
    serif: 'Georgia, "Times New Roman", Times, serif',
    mono: '"Courier New", Courier, monospace',
  };

  const FONT_STACKS = {
    mono: '"Courier New", Courier, monospace',
    serif: 'Georgia, "Times New Roman", serif',
    sans: UI_FONTS.inter.stack,
  };

  const _loadedUiFontLinks = Object.create(null);
  const UI_FONT_SIZE_MIN = 11;
  const UI_FONT_SIZE_MAX = 22;
  const UI_FONT_SIZE_DEFAULT = 13;
  const UI_FONT_SIZE_OPTIONS = [11, 12, 13, 14, 16, 18];

  function resolveUiFontKey(font) {
    const raw = String(font || "").trim().toLowerCase();
    if (UI_FONTS[raw]) return raw;
    // Legacy custom_theme.font values
    if (raw === "serif") return "merriweather";
    if (raw === "mono") return "ibm-plex-sans";
    if (raw === "sans" || raw === "retro-pixel") return "inter";
    return "inter";
  }

  function ensureUiFontLoaded(fontKey) {
    const key = resolveUiFontKey(fontKey);
    const meta = UI_FONTS[key];
    if (!meta || !meta.google || _loadedUiFontLinks[key]) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href =
      "https://fonts.bunny.net/css?family=" + meta.google + "&display=swap";
    link.dataset.uiFont = key;
    document.head.appendChild(link);
    _loadedUiFontLinks[key] = link;
  }

  function applyUiFont(fontKey) {
    const key = resolveUiFontKey(fontKey);
    const meta = UI_FONTS[key] || UI_FONTS.inter;
    state.uiFont = key;
    ensureUiFontLoaded(key);
    document.documentElement.style.setProperty("--ui-font", meta.stack);
    document.documentElement.setAttribute("data-ui-font", key);
    if ($("#ui-font")) $("#ui-font").value = key;
  }

  function parseUiFontSize(raw) {
    const n = Number(raw);
    if (!Number.isFinite(n)) return UI_FONT_SIZE_DEFAULT;
    return Math.round(Math.max(UI_FONT_SIZE_MIN, Math.min(UI_FONT_SIZE_MAX, n)));
  }

  function applyUiFontSize(size) {
    const px = parseUiFontSize(size);
    state.uiFontSize = px;
    document.documentElement.style.setProperty("--ui-font-size", px + "px");
    document.documentElement.setAttribute("data-ui-font-size", String(px));
    const sel = $("#ui-font-size");
    if (sel) {
      const values = Array.from(sel.options).map((opt) => Number(opt.value));
      if (!values.includes(px)) {
        const opt = document.createElement("option");
        opt.value = String(px);
        opt.textContent = px + " px";
        sel.appendChild(opt);
      }
      sel.value = String(px);
    }
  }

  function fillUiFontSizeSelect() {
    const sel = $("#ui-font-size");
    if (!sel) return;
    const prev = parseUiFontSize(sel.value || state.uiFontSize || UI_FONT_SIZE_DEFAULT);
    const labels = {
      11: "Small (11)",
      12: "12",
      13: "Default (13)",
      14: "14",
      16: "Large (16)",
      18: "Extra large (18)",
    };
    sel.innerHTML = "";
    const sizes = UI_FONT_SIZE_OPTIONS.slice();
    if (!sizes.includes(prev)) sizes.push(prev);
    sizes.sort((a, b) => a - b);
    sizes.forEach((px) => {
      const opt = document.createElement("option");
      opt.value = String(px);
      opt.textContent = labels[px] || px + " px";
      sel.appendChild(opt);
    });
    sel.value = String(prev);
  }

  function fillUiFontSelect() {
    const sel = $("#ui-font");
    if (!sel) return;
    const prev = resolveUiFontKey(sel.value || state.uiFont || "inter");
    sel.innerHTML = "";
    Object.keys(UI_FONTS).forEach((key) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = UI_FONTS[key].label;
      opt.style.fontFamily = UI_FONTS[key].stack;
      sel.appendChild(opt);
    });
    sel.value = prev;
  }

  function fontStackFromStyle(fontStyle) {
    // Legacy theme font styles (kept for older exports / callers).
    // Viewer display uses currentUiFontStack() / var(--ui-font) instead.
    const s = (fontStyle || "").toLowerCase();
    if (s === "dos-vga" || s === "workbench" || s === "pixel" || s === "mono") {
      return FONT_STACKS.mono;
    }
    if (s === "serif-parchment" || s === "serif") return FONT_STACKS.serif;
    return FONT_STACKS.sans;
  }

  function currentUiFontStack() {
    const key = resolveUiFontKey(state.uiFont || "inter");
    return (UI_FONTS[key] || UI_FONTS.inter).stack;
  }

  /** Palette overrides ported from retro_web_app CreationViewerWindow */
  const THEMES = {
    "apple2-green": {
      themeName: "Apple II Phosphor Green",
      bgColor: "#000000",
      cardBg: "#021802",
      textColor: "#00ff33",
      accentColor: "#00aa22",
      headerBg: "#012001",
      fontStyle: "dos-vga",
    },
    "apple2-amber": {
      themeName: "Apple II Phosphor Amber",
      bgColor: "#000000",
      cardBg: "#1a1000",
      textColor: "#ffb000",
      accentColor: "#cc8800",
      headerBg: "#2a1800",
      fontStyle: "dos-vga",
    },
    "sinclair-spectrum": {
      themeName: "Timex Sinclair / ZX Spectrum",
      bgColor: "#000000",
      cardBg: "#ffffff",
      textColor: "#000000",
      accentColor: "#d00000",
      headerBg: "#1a1a1a",
      fontStyle: "dos-vga",
    },
    c64: {
      themeName: "Commodore 64 Blue & Cyan",
      bgColor: "#352879",
      cardBg: "#403285",
      textColor: "#a297e0",
      accentColor: "#6c5eb5",
      headerBg: "#352879",
      fontStyle: "dos-vga",
    },
    workbench: {
      themeName: "Commodore Amiga Workbench 1.3",
      bgColor: "#0055aa",
      cardBg: "#ffffff",
      textColor: "#000000",
      accentColor: "#ffaa00",
      headerBg: "#0055aa",
      fontStyle: "workbench",
    },
    atari2600: {
      themeName: "Atari 2600 Woodgrain & Sunset",
      bgColor: "#2d1606",
      cardBg: "#3d2210",
      textColor: "#f8b800",
      accentColor: "#d05800",
      headerBg: "#1f0d02",
      fontStyle: "dos-vga",
    },
    "atari-st": {
      themeName: "Atari ST TOS Desktop",
      bgColor: "#008080",
      cardBg: "#ffffff",
      textColor: "#000000",
      accentColor: "#00a8a8",
      headerBg: "#005555",
      fontStyle: "dos-vga",
    },
    "amstrad-cpc": {
      themeName: "Amstrad CPC Color Palette",
      bgColor: "#000080",
      cardBg: "#0000a0",
      textColor: "#ffff00",
      accentColor: "#00ffff",
      headerBg: "#000060",
      fontStyle: "dos-vga",
    },
    "bbc-micro": {
      themeName: "BBC Micro / Acorn Palette",
      bgColor: "#600000",
      cardBg: "#1a0000",
      textColor: "#ffff00",
      accentColor: "#ff3333",
      headerBg: "#400000",
      fontStyle: "dos-vga",
    },
    vectrex: {
      themeName: "Vectrex Vector Monitor",
      bgColor: "#000000",
      cardBg: "#030c1a",
      textColor: "#00ffff",
      accentColor: "#0088ff",
      headerBg: "#001a33",
      fontStyle: "dos-vga",
    },
    gameboy: {
      themeName: "Game Boy Monochromatic Green",
      bgColor: "#0f380f",
      cardBg: "#306230",
      textColor: "#9bbc0f",
      accentColor: "#8bac0f",
      headerBg: "#0f380f",
      fontStyle: "pixel",
    },
    "dos-vga": {
      themeName: "MS-DOS Cyber VGA",
      bgColor: "#000000",
      cardBg: "#051505",
      textColor: "#00ff66",
      accentColor: "#008833",
      headerBg: "#003311",
      fontStyle: "dos-vga",
    },
    nes: {
      themeName: "NES Gray",
      bgColor: "#212121",
      cardBg: "#e0e0e0",
      textColor: "#111111",
      accentColor: "#e52521",
      headerBg: "#7c7c7c",
      fontStyle: "pixel",
    },
    "snes-parchment": {
      themeName: "SNES 16-Bit Parchment",
      bgColor: "#2b1b0e",
      cardBg: "#f4ebd0",
      textColor: "#2b1b0e",
      accentColor: "#8b0000",
      headerBg: "#8b0000",
      fontStyle: "serif-parchment",
    },
    "sega-genesis": {
      themeName: "Sega Genesis / Mega Drive Gold",
      bgColor: "#0a0a14",
      cardBg: "#181828",
      textColor: "#ffd700",
      accentColor: "#0060a8",
      headerBg: "#003060",
      fontStyle: "dos-vga",
    },
    dreamcast: {
      themeName: "Sega Dreamcast Orange & White",
      bgColor: "#ff6600",
      cardBg: "#ffffff",
      textColor: "#111827",
      accentColor: "#ff6600",
      headerBg: "#e65c00",
      fontStyle: "retro-sans",
    },
    "ps1-classic": {
      themeName: "PlayStation 1 Classic Gray",
      bgColor: "#7a818c",
      cardBg: "#1a2332",
      textColor: "#f3f4f6",
      accentColor: "#00439c",
      headerBg: "#0e1726",
      fontStyle: "retro-sans",
    },
    "ps2-darkness": {
      themeName: "PlayStation 2 Deep Space",
      bgColor: "#000511",
      cardBg: "#0a1228",
      textColor: "#e2e8f0",
      accentColor: "#0066cc",
      headerBg: "#001a40",
      fontStyle: "retro-sans",
    },
    "ps3-xmb": {
      themeName: "PlayStation 3 XMB Crimson Wave",
      bgColor: "#120008",
      cardBg: "#1f0a14",
      textColor: "#f3f4f6",
      accentColor: "#dc2626",
      headerBg: "#3b0712",
      fontStyle: "retro-sans",
    },
    "ps4-ps5": {
      themeName: "PlayStation 4 / PS5 Midnight Blue",
      bgColor: "#0a1128",
      cardBg: "#0f172a",
      textColor: "#f8fafc",
      accentColor: "#3b82f6",
      headerBg: "#1e3a8a",
      fontStyle: "retro-sans",
    },
    "xbox-original": {
      themeName: "Original Xbox Matrix Green",
      bgColor: "#031203",
      cardBg: "#0a220a",
      textColor: "#22ff33",
      accentColor: "#107c41",
      headerBg: "#003300",
      fontStyle: "dos-vga",
    },
    "xbox-360": {
      themeName: "Xbox 360 Blade UI Emerald",
      bgColor: "#dce3eb",
      cardBg: "#ffffff",
      textColor: "#0f172a",
      accentColor: "#107c41",
      headerBg: "#107c41",
      fontStyle: "retro-sans",
    },
    "xbox-series": {
      themeName: "Xbox Series X Dark Minimal",
      bgColor: "#0d1117",
      cardBg: "#161b22",
      textColor: "#f0f6fc",
      accentColor: "#107c41",
      headerBg: "#052e16",
      fontStyle: "retro-sans",
    },
    "wii-menu": {
      themeName: "Nintendo Wii Menu Cyan",
      bgColor: "#e8f4f8",
      cardBg: "#ffffff",
      textColor: "#0f172a",
      accentColor: "#00a4e4",
      headerBg: "#00a4e4",
      fontStyle: "retro-sans",
    },
    gamecube: {
      themeName: "Nintendo GameCube Indigo",
      bgColor: "#311042",
      cardBg: "#481e60",
      textColor: "#f3f4f6",
      accentColor: "#facc15",
      headerBg: "#240833",
      fontStyle: "retro-sans",
    },
    "switch-neon": {
      themeName: "Nintendo Switch Joy-Con Neon",
      bgColor: "#18181c",
      cardBg: "#24242c",
      textColor: "#ffffff",
      accentColor: "#ff3c28",
      headerBg: "#00c3e3",
      fontStyle: "retro-sans",
    },
    win98: {
      themeName: "Windows 98 Standard",
      bgColor: "#008080",
      cardBg: "#ffffff",
      textColor: "#000000",
      accentColor: "#000080",
      headerBg: "#000080",
      fontStyle: "retro-sans",
    },
  };

  // Back-compat aliases for older saved Viewer palette selections
  THEMES.amiga = THEMES.workbench;
  THEMES.dos = THEMES["dos-vga"];
  THEMES.xbox = THEMES["xbox-original"];

  /** App shell themes (Control Panel → Display). Separate from Viewer palettes above. */
  const APP_THEME_PRESETS = {
    light: {
      themeName: "Light Mode (Day)",
      bgColor: "#ffffff",
      cardBg: "#ffffff",
      textColor: "#000000",
      accentColor: "#000000",
      headerBg: "#ffffff",
      fontStyle: "sans",
    },
    dark: {
      themeName: "Dark Mode (Night)",
      bgColor: "#000000",
      cardBg: "#000000",
      textColor: "#ffffff",
      accentColor: "#ffffff",
      headerBg: "#000000",
      fontStyle: "sans",
    },
  };

  function resolveAppThemeKey(key) {
    const k = (key || "").trim().toLowerCase();
    if (k === "dark") return "dark";
    return "light";
  }

  function normalizeHexColor(value, fallback) {
    const raw = String(value || "").trim();
    if (/^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toLowerCase();
    if (/^#[0-9a-fA-F]{3}$/.test(raw)) {
      return (
        "#" +
        raw[1] +
        raw[1] +
        raw[2] +
        raw[2] +
        raw[3] +
        raw[3]
      ).toLowerCase();
    }
    return fallback;
  }

  function resolveCustomFontKey(font) {
    const f = String(font || "sans").toLowerCase();
    if (f === "serif" || f === "mono") return f;
    return "sans";
  }

  function getAppThemePalette(themeKey) {
    const key = resolveAppThemeKey(themeKey);
    return APP_THEME_PRESETS[key] || APP_THEME_PRESETS.light;
  }

  /** Desktop is a solid theme color (no patterned wallpaper). */
  function applyAppTheme(themeKey) {
    const key = resolveAppThemeKey(themeKey);
    const t = getAppThemePalette(key);
    state.appTheme = key;

    const root = document.documentElement;
    const isDark = key === "dark";
    const windowBg = isDark ? "#000000" : "#ffffff";
    const text = isDark ? "#ffffff" : "#000000";
    const muted = isDark ? "#b3b3b3" : "#555555";
    const borderLight = isDark ? "#1a1a1a" : "#ffffff";
    const borderMid = isDark ? "#333333" : "#d0d0d0";
    const borderDark = isDark ? "#666666" : "#808080";
    const borderDarker = "#000000";
    const title = windowBg;
    const titleText = text;
    const titleMid = windowBg;
    const titleInactive = isDark ? "#1a1a1a" : "#f2f2f2";
    const titleInactiveMid = titleInactive;
    const titleTextInactive = muted;
    const buttonFace = windowBg;
    const buttonText = text;
    const inputBg = windowBg;
    const inputText = text;
    const accent = text;
    const accentText = windowBg;
    const taskbar = windowBg;
    const highlight = isDark ? "#1a1a1a" : "#f2f2f2";
    const mid = windowBg;
    const deep = windowBg;
    const lightDesktop = !isDark;
    const darkButtons = isDark;

    root.style.setProperty("--desktop-bg", t.bgColor);
    root.style.setProperty("--desktop-bg-mid", mid);
    root.style.setProperty("--desktop-bg-deep", deep);
    root.style.setProperty("--desktop-wallpaper", "none");
    root.style.setProperty("--app-accent", accent);
    root.style.setProperty("--app-header", title);
    root.style.setProperty("--app-card", t.cardBg);
    root.style.setProperty("--app-text", text);
    root.style.setProperty("--icon-fg", lightDesktop ? "#111111" : "#ffffff");
    root.style.setProperty(
      "--icon-shadow",
      lightDesktop ? "rgba(255,255,255,0.7)" : "#000000"
    );
    root.style.setProperty("--icon-glyph-bg", buttonFace);

    root.style.setProperty("--ui-window", windowBg);
    root.style.setProperty("--ui-text", text);
    root.style.setProperty("--ui-muted", muted);
    root.style.setProperty("--ui-title", title);
    root.style.setProperty("--ui-title-mid", titleMid);
    root.style.setProperty("--ui-title-text", titleText);
    root.style.setProperty("--ui-title-inactive", titleInactive);
    root.style.setProperty("--ui-title-inactive-mid", titleInactiveMid);
    root.style.setProperty("--ui-title-text-inactive", titleTextInactive);
    root.style.setProperty("--ui-accent", accent);
    root.style.setProperty("--ui-accent-text", accentText);
    root.style.setProperty("--ui-button", buttonFace);
    root.style.setProperty("--ui-button-text", buttonText);
    root.style.setProperty("--ui-input", inputBg);
    root.style.setProperty("--ui-input-text", inputText);
    root.style.setProperty("--ui-taskbar", taskbar);
    root.style.setProperty("--ui-highlight", highlight);
    root.style.setProperty("--ui-border-light", borderLight);
    root.style.setProperty("--ui-border-mid", borderMid);
    root.style.setProperty("--ui-border-dark", borderDark);
    root.style.setProperty("--ui-border-darker", borderDarker);
    root.style.setProperty("--ui-shadow", borderDark);

    applyUiFont(state.uiFont || "inter");

    const desktop = $("#desktop");
    if (desktop) desktop.setAttribute("data-app-theme", key);
    document.documentElement.setAttribute("data-app-theme", key);
    document.documentElement.setAttribute(
      "data-ui-button-dark",
      darkButtons ? "1" : "0"
    );
    document.documentElement.setAttribute(
      "data-reading-surface",
      key === "dark" ? "dark" : "light"
    );

    if ($("#app-theme") && [...$("#app-theme").options].some((o) => o.value === key)) {
      $("#app-theme").value = key;
    }
  }

  function _normHex(hex) {
    return String(hex || "")
      .replace("#", "")
      .trim()
      .toLowerCase();
  }

  let audioCtx = null;

  function ensureAudioCtx() {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") {
      try {
        audioCtx.resume();
      } catch (_) {
        /* ignore */
      }
    }
    return audioCtx;
  }

  function _tone(ctx, { freq, type, start, dur, peak, attack, release }) {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type || "sine";
    o.frequency.setValueAtTime(freq, start);
    const a = attack != null ? attack : 0.01;
    const vol = Math.max(0, Math.min(1, (Number(state.soundVolume) || 0) / 100));
    const p = Math.max(0.0001, (peak != null ? peak : 0.35) * vol);
    if (vol <= 0) return;
    const end = start + Math.max(a + 0.03, dur);
    g.gain.setValueAtTime(0.0001, start);
    g.gain.exponentialRampToValueAtTime(p, start + a);
    g.gain.exponentialRampToValueAtTime(0.0001, end);
    o.connect(g);
    g.connect(ctx.destination);
    o.start(start);
    o.stop(end + 0.02);
  }

  /** Bright metallic ding (Win95-style notify), not a soft sine beep. */
  function _playDing(ctx, t0) {
    const vol = Math.max(0, Math.min(1, (Number(state.soundVolume) || 0) / 100));
    if (vol <= 0) return;

    // Brief noise strike for the "hit"
    try {
      const dur = 0.035;
      const frames = Math.max(1, Math.floor(ctx.sampleRate * dur));
      const buf = ctx.createBuffer(1, frames, ctx.sampleRate);
      const data = buf.getChannelData(0);
      for (let i = 0; i < frames; i++) {
        data[i] = (Math.random() * 2 - 1) * (1 - i / frames);
      }
      const src = ctx.createBufferSource();
      src.buffer = buf;
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.setValueAtTime(3200, t0);
      bp.Q.setValueAtTime(2.2, t0);
      const ng = ctx.createGain();
      const strikePeak = 0.55 * vol;
      ng.gain.setValueAtTime(0.0001, t0);
      ng.gain.exponentialRampToValueAtTime(Math.max(0.0001, strikePeak), t0 + 0.002);
      ng.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      src.connect(bp);
      bp.connect(ng);
      ng.connect(ctx.destination);
      src.start(t0);
      src.stop(t0 + dur + 0.01);
    } catch (_) {
      /* ignore */
    }

    // Inharmonic partials — reads as a small metal chime, not a beep
    const partials = [
      { freq: 2093.0, peak: 0.52, dur: 0.85, type: "sine" }, // bright fundamental
      { freq: 3135.96, peak: 0.28, dur: 0.55, type: "sine" },
      { freq: 4186.01, peak: 0.16, dur: 0.4, type: "sine" },
      { freq: 1480.0, peak: 0.22, dur: 1.05, type: "triangle" }, // body / ring
      { freq: 5274.0, peak: 0.08, dur: 0.28, type: "sine" },
    ];
    partials.forEach((p) => {
      _tone(ctx, {
        freq: p.freq,
        type: p.type,
        start: t0,
        dur: p.dur,
        peak: p.peak,
        attack: 0.002,
      });
    });
  }

  /**
   * Sparse Win95/98-inspired UI cues (synthesized — no Microsoft WAV assets).
   * Kinds: success (chord), error (stop), notify (ding), cancel (soft drop).
   * Peak levels are audible at 100% volume; Control Panel scales them.
   */
  function playUiSound(kind) {
    if (!state.soundEnabled) return;
    if ((Number(state.soundVolume) || 0) <= 0) return;
    try {
      const ctx = ensureAudioCtx();
      const t0 = ctx.currentTime + 0.01;
      if (kind === "success") {
        // Soft major chord — reminiscent of the classic "Chord" event cue
        const freqs = [523.25, 659.25, 783.99]; // C5 E5 G5
        freqs.forEach((freq, i) => {
          _tone(ctx, {
            freq,
            type: "triangle",
            start: t0 + i * 0.02,
            dur: 0.5 - i * 0.04,
            peak: 0.38,
            attack: 0.015,
          });
        });
        return;
      }
      if (kind === "error") {
        // Low dissonant buzz — critical-stop spirit, not a click chirp
        _tone(ctx, {
          freq: 185,
          type: "sawtooth",
          start: t0,
          dur: 0.24,
          peak: 0.42,
          attack: 0.004,
        });
        _tone(ctx, {
          freq: 155,
          type: "square",
          start: t0 + 0.12,
          dur: 0.3,
          peak: 0.32,
          attack: 0.004,
        });
        return;
      }
      if (kind === "cancel") {
        _tone(ctx, {
          freq: 392,
          type: "triangle",
          start: t0,
          dur: 0.14,
          peak: 0.32,
        });
        _tone(ctx, {
          freq: 311,
          type: "triangle",
          start: t0 + 0.09,
          dur: 0.18,
          peak: 0.26,
        });
        return;
      }
      // notify — metallic ding (also used as volume-slider preview)
      _playDing(ctx, t0);
    } catch (_) {
      /* ignore */
    }
  }

  function clampSoundVolume(raw) {
    const n = Number(raw);
    if (!Number.isFinite(n)) return 100;
    return Math.max(0, Math.min(100, Math.round(n)));
  }

  function syncSoundVolumeLabel(vol) {
    const label = $("#opt-sound-volume-label");
    if (label) label.textContent = clampSoundVolume(vol) + "%";
  }

  function applySoundVolume(raw, { preview } = {}) {
    const vol = clampSoundVolume(raw);
    state.soundVolume = vol;
    if ($("#opt-sound-volume")) $("#opt-sound-volume").value = String(vol);
    syncSoundVolumeLabel(vol);
    if (preview) playUiSound("notify");
  }

  function api() {
    return window.pywebview && window.pywebview.api;
  }

  function waitForApi(timeoutMs) {
    timeoutMs = timeoutMs || 8000;
    return new Promise((resolve) => {
      if (api()) return resolve(api());
      const onReady = () => resolve(api());
      window.addEventListener("pywebviewready", onReady, { once: true });
      setTimeout(() => {
        window.removeEventListener("pywebviewready", onReady);
        resolve(api());
      }, timeoutMs);
    });
  }

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function showToast(msg, durationMs) {
    const el = $("#error-toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showToast._t);
    const ms =
      typeof durationMs === "number"
        ? durationMs
        : String(msg || "").length > 120
          ? 12000
          : 5000;
    showToast._t = setTimeout(() => {
      el.hidden = true;
    }, ms);
  }

  function setProgress(msg) {
    const text = $("#app-status-text") || $("#gen-status-text");
    if (text) text.textContent = msg || "Ready";
  }

  // ── Busy / progress dialog ─────────────────────────────────────────
  const BUSY_HINTS = {
    generate:
      "Creating text, an image, or video from your prompt. You can cancel anytime.",
    default:
      "Gemini usually finishes in seconds.",
  };

  const busy = {
    visible: false,
    showTimer: null,
    elapsedTimer: null,
    startedAt: 0,
    title: "Please wait…",
    activity: null, // "generate" | "other"
    cancellable: false,
    cancelling: false,
    jobId: null,
  };

  function setBusyHint(text) {
    const hintEl = $("#busy-hint");
    if (hintEl) hintEl.textContent = text || BUSY_HINTS.default;
  }

  function setBusyTitle(title) {
    if (!title) return;
    busy.title = title;
    const titleEl = $("#busy-title");
    if (titleEl && (busy.visible || busy.showTimer)) {
      titleEl.textContent = title;
    }
  }

  function showConfirm(title, message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      const overlay = $("#confirm-overlay");
      const titleEl = $("#confirm-title");
      const msgEl = $("#confirm-message");
      const yesBtn = $("#confirm-yes");
      const noBtn = $("#confirm-no");
      if (!overlay || !yesBtn || !noBtn) {
        resolve(window.confirm(message || title));
        return;
      }
      const prevYes = yesBtn.textContent;
      const prevNo = noBtn.textContent;
      if (titleEl) titleEl.textContent = title || "Confirm";
      if (msgEl) msgEl.textContent = message || "";
      yesBtn.textContent = opts.yesLabel || "Yes";
      noBtn.textContent = opts.noLabel || "No";
      overlay.hidden = false;
      detachIme();

      const finish = (value) => {
        overlay.hidden = true;
        yesBtn.textContent = prevYes;
        noBtn.textContent = prevNo;
        yesBtn.removeEventListener("click", onYes);
        noBtn.removeEventListener("click", onNo);
        resolve(value);
      };
      const onYes = () => finish(true);
      const onNo = () => finish(false);
      yesBtn.addEventListener("click", onYes);
      noBtn.addEventListener("click", onNo);
      (opts.focusNo ? noBtn : yesBtn).focus();
    });
  }

  /**
   * Recommend Models dialog — returns "economical" | "balanced" | "quality", or null if cancelled.
   */
  function showRecommendModelsDialog() {
    return new Promise((resolve) => {
      const overlay = $("#recommend-models-overlay");
      const okBtn = $("#recommend-models-ok");
      const cancelBtn = $("#recommend-models-cancel");
      if (!overlay || !okBtn || !cancelBtn) {
        resolve(null);
        return;
      }
      const balanced = $("#recommend-balanced");
      if (balanced) balanced.checked = true;
      overlay.hidden = false;
      detachIme();

      const finish = (value) => {
        overlay.hidden = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtn.removeEventListener("click", onCancel);
        resolve(value);
      };
      const onCancel = () => finish(null);
      const onOk = () => {
        const chosen = document.querySelector(
          'input[name="recommend-criteria"]:checked'
        );
        finish((chosen && chosen.value) || "balanced");
      };
      okBtn.addEventListener("click", onOk);
      cancelBtn.addEventListener("click", onCancel);
      okBtn.focus();
    });
  }

  async function runRecommendModels(provider) {
    const criteria = await showRecommendModelsDialog();
    if (!criteria) return;

    const a = api();
    if (!a) {
      showToast("Python bridge not ready.");
      return;
    }

    const pretty =
      criteria === "economical"
        ? "Economical"
        : criteria === "quality"
          ? "Maximum quality"
          : "Balanced";
    beginBusy(
      "Recommend Models",
      "Finding " + pretty + " models from the live catalog…",
      {
        delayMs: 0,
        percent: 20,
        hint:
          "Queries Google for Gemini Text / Image / Video models — not only the current picker lists.",
      }
    );

    try {
      const res = await a.recommend_models(criteria, "gemini");
      if (!res || !res.ok) {
        showToast((res && res.error) || "Could not recommend models.");
        return;
      }
      applyRecommendedModels(res);
      showToast(res.message || "Models recommended.");
      playUiSound("notify");
    } catch (err) {
      showToast("Recommend Models failed: " + err);
      playUiSound("error");
    } finally {
      endBusy("Ready");
      requestAnimationFrame(() => syncDesktopScrollExtent());
    }
  }

  function applyRecommendedModels(res) {
    const picks = (res && res.picks) || {};
    const models = (res && res.models) || [];
    const provider = (res && res.provider) || "gemini";

    if (provider === "gemini") {
      fillGeminiModalitySelect(
        $("#gemini-text-model"),
        picks.text,
        models,
        "text"
      );
      fillGeminiModalitySelect(
        $("#gemini-image-model"),
        picks.image,
        models,
        "image"
      );
      fillGeminiModalitySelect(
        $("#gemini-video-model"),
        picks.video,
        models,
        "video"
      );
      fillGeminiModalitySelect(
        $("#gemini-audio-model"),
        picks.audio,
        models,
        "audio"
      );
      updateStudioBackendLabel({
        config: {
          backend: { provider: "gemini" },
          gemini: {
            text_model: picks.text,
            image_model: picks.image,
            video_model: picks.video,
            audio_model: picks.audio,
          },
        },
      });
    }
  }

  /**
   * Search Results dialog for ambiguous game titles.
   * Resolves to the selected candidate object, or null if cancelled.
   */
  function showSearchResults(query, candidates) {
    return new Promise((resolve) => {
      const overlay = $("#search-results-overlay");
      const titleEl = $("#search-results-title");
      const msgEl = $("#search-results-message");
      const listEl = $("#search-results-list");
      const cancelBtn = $("#search-results-cancel");
      const items = Array.isArray(candidates) ? candidates : [];

      if (!overlay || !listEl || !cancelBtn) {
        resolve(null);
        return;
      }

      if (titleEl) titleEl.textContent = "Search Results";
      if (msgEl) {
        const q = (query || "").trim();
        msgEl.textContent = q
          ? `Multiple games match "${q}". Select the title you meant:`
          : "Multiple games match. Select the title you meant:";
      }

      const finish = (value) => {
        overlay.hidden = true;
        cancelBtn.removeEventListener("click", onCancel);
        listEl.innerHTML = "";
        resolve(value);
      };
      const onCancel = () => finish(null);

      listEl.innerHTML = "";
      items.forEach((c, idx) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        const btn = document.createElement("button");
        btn.type = "button";
        const name = (c && c.game) || "";
        const metaParts = [];
        if (c && c.year) metaParts.push(String(c.year));
        if (c && c.platform) metaParts.push(String(c.platform));
        if (c && c.note) metaParts.push(String(c.note));
        const titleSpan = document.createElement("span");
        titleSpan.className = "sr-title";
        titleSpan.textContent = name;
        btn.appendChild(titleSpan);
        if (metaParts.length) {
          const metaSpan = document.createElement("span");
          metaSpan.className = "sr-meta";
          metaSpan.textContent = metaParts.join(" · ");
          btn.appendChild(metaSpan);
        }
        btn.addEventListener("click", () => finish(c));
        if (idx === 0) btn.dataset.first = "1";
        li.appendChild(btn);
        listEl.appendChild(li);
      });

      overlay.hidden = false;
      detachIme();
      cancelBtn.addEventListener("click", onCancel);
      const firstBtn = listEl.querySelector("button[data-first]") || cancelBtn;
      firstBtn.focus();
    });
  }

  function studioGeminiBackend() {
    return true;
  }

  function studioToolsEnabled() {
    if (!studioGeminiBackend()) return false;
    const box = $("#studio-enable-tools");
    if (box) return !!box.checked;
    return !!state.studioEnableTools;
  }

  function applyStudioEnableToolsFromConfig() {
    const cfg = state.config || {};
    const gemini = cfg.gemini || {};
    const available = studioGeminiBackend();
    const on = available && !!gemini.use_tools;
    state.studioEnableTools = on;
    const box = $("#studio-enable-tools");
    if (box) {
      box.checked = on;
      box.disabled = !available;
    }
  }

  function studioGoogleSearchEnabled() {
    const cfg = state.config || {};
    const gemini = cfg.gemini || {};
    return gemini.google_search !== false;
  }

  function getGeminiToolsCatalog() {
    if (Array.isArray(state.geminiToolsCatalog) && state.geminiToolsCatalog.length) {
      return state.geminiToolsCatalog;
    }
    return [
      {
        alias: "read_json",
        display_name: "Read JSON",
        summary: "Read and parse a JSON file at an absolute path",
      },
      {
        alias: "write_json",
        display_name: "Write JSON",
        summary: "Write JSON data to a file at an absolute path (overwrites)",
      },
      {
        alias: "read_text",
        display_name: "Read text",
        summary: "Read a text file at an absolute path",
      },
      {
        alias: "write_text",
        display_name: "Write text",
        summary: "Write text to a file at an absolute path (overwrites)",
      },
      {
        alias: "execute_powershell",
        display_name: "Execute PowerShell",
        summary: "Run a .ps1 script at an absolute path; returns stdout, stderr, and exit code",
      },
      {
        alias: "search_gmail",
        display_name: "Search Gmail",
        summary: "Search Gmail with query syntax (unread, shipments, specific senders, etc.)",
      },
      {
        alias: "search_drive",
        display_name: "Search Drive",
        summary: "Search Google Drive files by name, type, or Drive query syntax",
      },
      {
        alias: "create_drive_file",
        display_name: "Create Drive file",
        summary: "Create a Google Drive file (text/plain by default)",
      },
      {
        alias: "read_google_doc",
        display_name: "Read Google Doc",
        summary: "Read the text of a Google Doc by document ID",
      },
      {
        alias: "create_google_doc",
        display_name: "Create Google Doc",
        summary: "Create a Google Doc with an optional initial body",
      },
      {
        alias: "edit_google_doc",
        display_name: "Edit Google Doc",
        summary: "Replace or append text in a Google Doc",
      },
      {
        alias: "list_calendar_events",
        display_name: "List Calendar events",
        summary: "List Google Calendar events in a time range",
      },
      {
        alias: "create_calendar_event",
        display_name: "Create Calendar event",
        summary: "Create a Google Calendar event",
      },
      {
        alias: "edit_calendar_event",
        display_name: "Edit Calendar event",
        summary: "Update an existing Google Calendar event",
      },
      {
        alias: "list_tasks",
        display_name: "List Tasks",
        summary: "List Google Tasks on the default or a named list",
      },
      {
        alias: "create_task",
        display_name: "Create Task",
        summary: "Create a Google Task (title, optional notes and due date/time)",
      },
      {
        alias: "edit_task",
        display_name: "Edit Task",
        summary: "Update or complete a Google Task",
      },
      {
        alias: "browse_web",
        display_name: "Browse Web",
        summary: "Open an http(s) URL, read the page, and follow its links",
      },
    ];
  }

  function toolMeta(alias) {
    const found = getGeminiToolsCatalog().find((t) => t.alias === alias);
    return found || { alias: alias, display_name: alias, summary: "" };
  }

  function syncStudioToolsPanel() {
    const form = $("#create-form");
    const panel = $("#studio-tools-panel");
    const promptWrap = $("#studio-prompt-wrap");
    const searchWrap = $("#studio-search-wrap");
    const toolUseWrap = $("#studio-tool-use-wrap");
    const loadHint = $("#studio-load-hint");
    const available = studioGeminiBackend();
    const enabled = studioToolsEnabled();
    const searchOn = studioGoogleSearchEnabled();
    const box = $("#studio-enable-tools");
    const hint = $("#studio-enable-tools-hint");

    if (box) {
      box.disabled = !available;
      state.studioEnableTools = !!box.checked && available;
    }
    if (hint) {
      hint.textContent =
        "Toggle tools for this Studio session without opening Settings. Settings → Use Tools is the default on launch.";
      hint.classList.toggle("muted", !available);
    }

    if (form) {
      form.classList.toggle("studio-tools-mode", !!enabled);
    }
    if (panel) panel.hidden = !enabled;
    if (promptWrap) promptWrap.hidden = !!enabled;
    if (searchWrap) searchWrap.hidden = !enabled || !searchOn;
    if (toolUseWrap) toolUseWrap.hidden = !enabled;
    if (loadHint) {
      if (!enabled) {
        loadHint.textContent =
          "Menu → Load Text puts text in the prompt. Menu → Load Image / Video sets a media basis on the right (drag the divider to resize) — then describe the change and CREATE. Send a screenshot or clip from Viewer (Use as Basis) or the image/video editor (Save and Send to Creator), then prompt extract the text, transcribe, or extract the layout. After a layout extract, ask Studio to recreate the UI as HTML/CSS or an app (or another mockup if you ask for an image). For a song, Use as Basis reloads the prompt and lyrics as text — not the MP3.";
      } else if (searchOn) {
        loadHint.textContent =
          "Menu → Load Text puts text in Search (optional). Menu → Load Image / Video sets a media basis on the right (drag the divider to resize) — then describe the change and CREATE. Send a screenshot or clip from Viewer (Use as Basis) or the image/video editor (Save and Send to Creator), then prompt extract the text, transcribe, or extract the layout. After a layout extract, ask Studio to recreate the UI as HTML/CSS or an app (or another mockup if you ask for an image). For a song, Use as Basis reloads the prompt and lyrics as text — not the MP3.";
      } else {
        loadHint.textContent =
          "Google Search is off — only Tool Use runs. Menu → Load Image / Video sets a media basis on the right (drag the divider to resize) — then describe the change and CREATE. Send a screenshot or clip from Viewer (Use as Basis) or the image/video editor (Save and Send to Creator), then prompt extract the text, transcribe, or extract the layout. After a layout extract, ask Studio to recreate the UI as HTML/CSS or an app (or another mockup if you ask for an image). For a song, Use as Basis reloads the prompt and lyrics as text — not the MP3.";
      }
    }
    renderStudioToolsList();
  }

  function renderStudioToolsList() {
    const listEl = $("#studio-tools-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    (state.studioTools || []).forEach((alias) => {
      const meta = toolMeta(alias);
      const li = document.createElement("li");
      li.className = "studio-tool-chip";
      const label = document.createElement("code");
      label.textContent = alias;
      label.title = meta.summary || meta.display_name || alias;
      li.appendChild(label);
      const insertBtn = document.createElement("button");
      insertBtn.type = "button";
      insertBtn.className = "studio-tool-insert";
      insertBtn.textContent = "Insert";
      insertBtn.title = "Insert alias into Tool Use";
      insertBtn.addEventListener("click", () => insertStudioToolAlias(alias));
      li.appendChild(insertBtn);
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "studio-tool-remove";
      removeBtn.textContent = "×";
      removeBtn.title = "Remove tool";
      removeBtn.addEventListener("click", () => {
        state.studioTools = (state.studioTools || []).filter((a) => a !== alias);
        renderStudioToolsList();
      });
      li.appendChild(removeBtn);
      listEl.appendChild(li);
    });
  }

  function insertStudioToolAlias(alias) {
    const ta = $("#studio-tool-use") || $("#studio-prompt");
    if (!ta) return;
    const text = String(alias || "");
    const start = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
    const end = ta.selectionEnd != null ? ta.selectionEnd : start;
    const before = ta.value.slice(0, start);
    const after = ta.value.slice(end);
    const padBefore = before && !/\s$/.test(before) ? " " : "";
    const padAfter = after && !/^\s/.test(after) ? " " : "";
    ta.value = before + padBefore + text + padAfter + after;
    const cursor = start + padBefore.length + text.length;
    try {
      ta.setSelectionRange(cursor, cursor);
    } catch (_) {
      /* ignore */
    }
    attachIme(ta);
  }

  function showAddToolDialog() {
    return new Promise((resolve) => {
      const overlay = $("#studio-add-tool-overlay");
      const listEl = $("#studio-add-tool-list");
      const cancelBtn = $("#studio-add-tool-cancel");
      const msgEl = $("#studio-add-tool-message");
      if (!overlay || !listEl || !cancelBtn) {
        resolve(null);
        return;
      }

      const attached = new Set(state.studioTools || []);
      const available = getGeminiToolsCatalog().filter((t) => !attached.has(t.alias));
      if (msgEl) {
        msgEl.textContent = available.length
          ? "Choose a built-in tool to attach for this generation."
          : "All built-in tools are already attached.";
      }

      const finish = (value) => {
        state.studioAddToolOpen = false;
        overlay.hidden = true;
        cancelBtn.removeEventListener("click", onCancel);
        overlay.removeEventListener("keydown", onKey);
        listEl.innerHTML = "";
        resolve(value);
      };
      const onCancel = () => finish(null);
      const onKey = (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          finish(null);
        }
      };

      listEl.innerHTML = "";
      available.forEach((t, idx) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        const btn = document.createElement("button");
        btn.type = "button";
        const titleSpan = document.createElement("span");
        titleSpan.className = "sr-title";
        titleSpan.textContent = (t.display_name || t.alias) + " (" + t.alias + ")";
        btn.appendChild(titleSpan);
        if (t.summary) {
          const metaSpan = document.createElement("span");
          metaSpan.className = "sr-meta";
          metaSpan.textContent = t.summary;
          btn.appendChild(metaSpan);
        }
        btn.addEventListener("click", () => finish(t.alias));
        if (idx === 0) btn.dataset.first = "1";
        li.appendChild(btn);
        listEl.appendChild(li);
      });

      state.studioAddToolOpen = true;
      overlay.hidden = false;
      detachIme();
      cancelBtn.addEventListener("click", onCancel);
      overlay.addEventListener("keydown", onKey);
      // Keep focus inside the dialog so Escape / Tab stay modal.
      overlay.setAttribute("tabindex", "-1");
      const firstBtn = listEl.querySelector("button[data-first]") || cancelBtn;
      firstBtn.focus();
    });
  }

  function setCreateBlocked(blocked) {
    const btn = $("#btn-generate");
    if (!btn) return;
    if (blocked || state.generating) {
      btn.disabled = true;
    } else {
      btn.disabled = false;
    }
  }

  let _settingsSaving = false;
  let _settingsSaveTimer = null;
  let _studioBasisWidthSaveTimer = null;

  async function saveControlPanelSettings(opts) {
    opts = opts || {};
    const a = api();
    if (!a) {
      if (!opts.silent) showToast("Python bridge not ready.");
      return;
    }
    if (_settingsSaving) return;
    if (!opts.silent && !ensureApiKeyBeforeSave()) return;
    _settingsSaving = true;
    try {

    if (opts.applyDisplay) applyDisplaySettingsFromControls();

    const res = await a.save_settings(collectSettings());

    if (res.config) {
      state.config = res.config;
      if (!opts.silent) {
        try {
          const boot = await a.get_bootstrap();
          state.config = boot.config || res.config;
          fillControlPanel(boot);
        } catch (_) {
          fillControlPanel({
            config: res.config,
            suggestedGeminiModels: [],
            modelStatus: res.modelStatus,
          });
        }
      }
      updateApiKeyIndicators();
      clearGeminiApiKeyInputsIfIdle();
      syncStudioToolsPanel();
    }

    if (opts.silent) {
      setProgress(res.message || "Settings saved");
    } else {
      showToast(res.message || "Saved");
    }

    const mediaMove = res.mediaMove;
    if (res.ok && mediaMove && mediaMove.offered && mediaMove.count > 0) {
      const go = await showConfirm(
        "Move existing media?",
        "Settings were saved.\n\n" +
          "Move " +
          mediaMove.count +
          " existing media file(s) into the new folder?\n\n" +
          "Yes — move the files and update Archives so Viewer still finds them.\n" +
          "No — leave them where they are. New creations will use the new folder."
      );
      if (go) {
        const moved = await a.relocate_media_files(mediaMove.source);
        if (!moved.ok) {
          showToast(moved.error || "Could not move media files");
        } else {
          if (Array.isArray(moved.creations)) {
            state.creations = moved.creations;
            if (state.active && state.active.id) {
              const next = state.creations.find((c) => c.id === state.active.id);
              if (next) renderDocument(next);
            }
            renderArchives();
          }
          showToast(
            moved.moved
              ? "Moved " + moved.moved + " media file(s)."
              : "No media files needed moving."
          );
        }
      }
    }

    if (opts.silent || !offerDownload) return;

    const go = await showConfirm(
      "Download local models?",
      "Settings were saved.\n\n" +
        "Download and cache the Hugging Face text, image, and video models now?\n\n" +
        "Yes — start the downloads (Create stays blocked until they finish).\n" +
        "No — skip download for now (models load on first use)."
    );
    if (!go) {
      showToast("Saved — local models not downloaded yet.");
      return;
    }

    await startLocalModelDownload();
    } finally {
      _settingsSaving = false;
    }
  }

  function persistSettingsSoon(opts) {
    clearTimeout(_settingsSaveTimer);
    _settingsSaveTimer = setTimeout(() => {
      void saveControlPanelSettings(Object.assign({ silent: true }, opts || {}));
    }, 250);
  }

  function persistSettingsNow(opts) {
    clearTimeout(_settingsSaveTimer);
    return saveControlPanelSettings(Object.assign({ silent: true }, opts || {}));
  }

  function formatElapsed(ms) {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m + ":" + String(r).padStart(2, "0");
  }

  function updateBusyElapsed() {
    const el = $("#busy-elapsed");
    if (!el || !busy.startedAt) return;
    el.textContent = formatElapsed(Date.now() - busy.startedAt);
  }

  function setBusyCancelVisible(show) {
    const actions = $("#busy-actions");
    const btn = $("#busy-cancel");
    if (actions) actions.hidden = !show;
    if (btn) {
      btn.disabled = !!busy.cancelling;
      btn.textContent = busy.cancelling ? "Cancelling…" : "Cancel";
    }
  }

  function _showBusyNow(title, message, percent, hint) {
    const overlay = $("#busy-overlay");
    if (!overlay) return;
    $("#busy-title").textContent = title || "Please wait…";
    $("#busy-message").textContent = message || "Working…";
    if (hint) setBusyHint(hint);
    overlay.hidden = false;
    busy.visible = true;
    detachIme();
    if (!busy.startedAt) busy.startedAt = Date.now();
    if (!busy.elapsedTimer) {
      updateBusyElapsed();
      busy.elapsedTimer = setInterval(updateBusyElapsed, 500);
    }
    setBusyPercent(percent);
    setBusyCancelVisible(!!busy.cancellable);
  }

  function setBusyPercent(percent) {
    const bar = $("#busy-bar");
    const indicator = $("#busy-indicator");
    const label = $("#busy-percent-label");
    if (!bar || !indicator) return;
    if (percent == null || Number.isNaN(Number(percent))) {
      indicator.classList.add("indeterminate");
      bar.style.width = "";
      bar.style.marginLeft = "";
      if (label) label.textContent = "";
    } else {
      const pct = Math.max(0, Math.min(100, Number(percent)));
      indicator.classList.remove("indeterminate");
      bar.style.marginLeft = "0";
      bar.style.width = pct + "%";
      if (label) label.textContent = Math.round(pct) + "%";
    }
  }

  /**
   * Show the busy dialog. Known long ops use delayMs=0.
   * Otherwise the dialog appears only if work is still going after delayMs
   * (default 1500ms) so short actions don't flash a modal.
   * opts.cancellable — show Cancel (generation jobs).
   * opts.activity — "generate" | "other" (drives title/hint framing).
   * opts.hint — footer description for this activity.
   */
  function beginBusy(title, message, opts) {
    opts = opts || {};
    const delayMs = opts.delayMs != null ? opts.delayMs : 1500;
    busy.title = title || "Please wait…";
    busy.activity = opts.activity || "other";
    if ("cancellable" in opts) busy.cancellable = !!opts.cancellable;
    if ("jobId" in opts) busy.jobId = opts.jobId || null;
    if (!opts.cancellable) busy.cancelling = false;
    const hint =
      opts.hint != null
        ? opts.hint
        : busy.activity === "generate"
          ? BUSY_HINTS.generate
          : null;
    clearTimeout(busy.showTimer);
    setProgress(message || title || "Working…");

    if (delayMs <= 0) {
      _showBusyNow(busy.title, message, opts.percent, hint);
      return;
    }

    // If already visible, just update
    if (busy.visible) {
      $("#busy-title").textContent = busy.title;
      $("#busy-message").textContent = message || "Working…";
      if (hint) setBusyHint(hint);
      if ("percent" in opts) setBusyPercent(opts.percent);
      setBusyCancelVisible(!!busy.cancellable);
      return;
    }

    busy.startedAt = Date.now();
    busy.showTimer = setTimeout(() => {
      _showBusyNow(busy.title, message, opts.percent, hint);
    }, delayMs);
  }

  function updateBusy(message, percent, title) {
    if (title) setBusyTitle(title);
    if (message) {
      setProgress(message);
      const msgEl = $("#busy-message");
      if (msgEl) msgEl.textContent = message;
    }
    if (percent !== undefined) setBusyPercent(percent);

    // If a deferred show is pending and we got real progress, show immediately
    if (!busy.visible && busy.showTimer && (message || percent != null || title)) {
      clearTimeout(busy.showTimer);
      busy.showTimer = null;
      _showBusyNow(busy.title, message || "Working…", percent);
    }
  }

  function endBusy(finalMessage) {
    clearTimeout(busy.showTimer);
    busy.showTimer = null;
    if (busy.elapsedTimer) {
      clearInterval(busy.elapsedTimer);
      busy.elapsedTimer = null;
    }
    busy.startedAt = 0;
    busy.visible = false;
    busy.activity = null;
    busy.cancellable = false;
    busy.cancelling = false;
    busy.jobId = null;
    setBusyCancelVisible(false);
    setBusyHint(BUSY_HINTS.default);
    const overlay = $("#busy-overlay");
    if (overlay) overlay.hidden = true;
    setProgress(finalMessage || "Ready");
  }

  function setStudioPlatform(platform) {
    // Platform select removed from Creation Studio; keep for API compatibility no-ops.
    void platform;
  }

  function getStudioPlatform() {
    return "";
  }

  function getStudioPrompt() {
    const field = $("#studio-prompt");
    return field ? field.value : "";
  }

  function setStudioPrompt(text) {
    const field = $("#studio-prompt");
    if (field) {
      field.value = text || "";
      refreshImeField(field);
    }
  }

  function getStudioSearch() {
    const field = $("#studio-search");
    return field ? field.value : "";
  }

  function setStudioSearch(text) {
    const field = $("#studio-search");
    if (field) {
      field.value = text || "";
      refreshImeField(field);
    }
  }

  function getStudioToolUse() {
    const field = $("#studio-tool-use");
    return field ? field.value : "";
  }

  function setStudioToolUse(text) {
    const field = $("#studio-tool-use");
    if (field) {
      field.value = text || "";
      refreshImeField(field);
    }
  }

  function savedPromptById(id) {
    return (state.savedPrompts || []).find((p) => p && p.id === id) || null;
  }

  function applySavedPrompts(list) {
    const items = Array.isArray(list) ? list.slice() : [];
    items.sort((a, b) =>
      String(a && a.name ? a.name : "").localeCompare(
        String(b && b.name ? b.name : ""),
        undefined,
        { sensitivity: "base" }
      )
    );
    state.savedPrompts = items;
    fillSavedPromptSelects();
  }

  function fillSelectOptions(selectEl, placeholder, selectedId) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = placeholder;
    selectEl.appendChild(blank);
    (state.savedPrompts || []).forEach((p) => {
      if (!p || !p.id) return;
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name || "Untitled";
      selectEl.appendChild(opt);
    });
    if (selectedId && (state.savedPrompts || []).some((p) => p.id === selectedId)) {
      selectEl.value = selectedId;
    } else {
      selectEl.value = "";
    }
  }

  function fillSavedPromptSelects() {
    fillSelectOptions(
      $("#studio-saved-prompt"),
      "Insert saved prompt…",
      ""
    );
    fillSelectOptions(
      $("#prompt-editor-list"),
      "Select a prompt…",
      state.promptEditor.selectedId
    );
  }

  async function refreshSavedPrompts() {
    const a = api();
    if (!a || typeof a.list_prompts !== "function") return;
    try {
      const res = await a.list_prompts();
      if (res && res.ok && Array.isArray(res.prompts)) {
        applySavedPrompts(res.prompts);
        syncPromptEditorUi();
      }
    } catch (err) {
      console.error(err);
    }
  }

  function promptEditorFieldValues() {
    const nameEl = $("#prompt-editor-name");
    const bodyEl = $("#prompt-editor-text");
    return {
      name: nameEl ? nameEl.value : "",
      body: bodyEl ? bodyEl.value : "",
    };
  }

  function promptEditorIsDirty() {
    const pe = state.promptEditor;
    if (!pe.editing) return false;
    const cur = promptEditorFieldValues();
    return (
      cur.name !== (pe.snapshotName || "") || cur.body !== (pe.snapshotBody || "")
    );
  }

  function setPromptEditorEditing(editing) {
    state.promptEditor.editing = !!editing;
    const nameEl = $("#prompt-editor-name");
    const bodyEl = $("#prompt-editor-text");
    if (nameEl) nameEl.disabled = !editing;
    if (bodyEl) bodyEl.disabled = !editing;
  }

  function loadPromptEditorFields(prompt) {
    const nameEl = $("#prompt-editor-name");
    const bodyEl = $("#prompt-editor-text");
    const name = prompt && prompt.name ? prompt.name : "";
    const body = prompt && prompt.body ? prompt.body : "";
    if (nameEl) nameEl.value = name;
    if (bodyEl) bodyEl.value = body;
    state.promptEditor.snapshotName = name;
    state.promptEditor.snapshotBody = body;
  }

  function resetPromptEditor() {
    state.promptEditor.selectedId = "";
    state.promptEditor.editing = false;
    state.promptEditor.snapshotName = "";
    state.promptEditor.snapshotBody = "";
    loadPromptEditorFields(null);
    setPromptEditorEditing(false);
    const list = $("#prompt-editor-list");
    if (list) list.value = "";
  }

  function syncPromptEditorUi() {
    const list = $("#prompt-editor-list");
    if (list) {
      fillSelectOptions(list, "Select a prompt…", state.promptEditor.selectedId);
    }
    const selected = savedPromptById(state.promptEditor.selectedId);
    if (state.promptEditor.editing) {
      setPromptEditorEditing(true);
      return;
    }
    if (selected) loadPromptEditorFields(selected);
    else if (!state.promptEditor.selectedId) loadPromptEditorFields(null);
    setPromptEditorEditing(false);
  }

  async function confirmDiscardPromptEdits() {
    if (!promptEditorIsDirty()) return true;
    return showConfirm(
      "Unsaved prompt",
      "Discard unsaved changes to this prompt?",
      { yesLabel: "Discard", noLabel: "Keep editing" }
    );
  }

  async function startNewPrompt() {
    if (!(await confirmDiscardPromptEdits())) return;
    state.promptEditor.selectedId = "";
    loadPromptEditorFields({ name: "", body: "" });
    setPromptEditorEditing(true);
    fillSelectOptions($("#prompt-editor-list"), "Select a prompt…", "");
    const nameEl = $("#prompt-editor-name");
    if (nameEl) nameEl.focus();
  }

  async function editSelectedPrompt() {
    const id = state.promptEditor.selectedId;
    const selected = savedPromptById(id);
    if (!selected) {
      await startNewPrompt();
      return;
    }
    if (promptEditorIsDirty() && state.promptEditor.editing) {
      const nameEl = $("#prompt-editor-name");
      if (nameEl) nameEl.focus();
      return;
    }
    loadPromptEditorFields(selected);
    setPromptEditorEditing(true);
    const nameEl = $("#prompt-editor-name");
    if (nameEl) nameEl.focus();
  }

  async function saveCurrentPrompt() {
    if (!state.promptEditor.editing) {
      showToast("Click Edit or Add before saving.");
      return;
    }
    const cur = promptEditorFieldValues();
    const name = (cur.name || "").trim();
    if (!name) {
      showToast("Name this prompt before saving.");
      const nameEl = $("#prompt-editor-name");
      if (nameEl) nameEl.focus();
      return;
    }
    const a = api();
    if (!a || typeof a.save_prompt !== "function") {
      showToast("Python bridge not ready.");
      return;
    }
    try {
      const res = await a.save_prompt({
        id: state.promptEditor.selectedId || "",
        name,
        body: cur.body || "",
      });
      if (!res || !res.ok) {
        showToast((res && res.error) || "Could not save prompt.");
        return;
      }
      applySavedPrompts(res.prompts || []);
      const saved = res.prompt || {};
      state.promptEditor.selectedId = saved.id || "";
      loadPromptEditorFields(saved);
      setPromptEditorEditing(false);
      fillSelectOptions(
        $("#prompt-editor-list"),
        "Select a prompt…",
        state.promptEditor.selectedId
      );
      showToast("Prompt saved.");
    } catch (err) {
      showToast("Could not save prompt: " + err);
    }
  }

  async function deleteCurrentPrompt() {
    const id = state.promptEditor.selectedId || "";
    const selected = savedPromptById(id);
    if (!id || !selected) {
      showToast("Select a saved prompt to delete.");
      return;
    }
    const name = selected.name || "this prompt";
    const go = await showConfirm(
      "Delete prompt",
      'Delete "' + name + '"? This cannot be undone.',
      { yesLabel: "Delete", noLabel: "Cancel" }
    );
    if (!go) return;
    const a = api();
    if (!a || typeof a.delete_prompt !== "function") {
      showToast("Python bridge not ready.");
      return;
    }
    try {
      const res = await a.delete_prompt(id);
      if (!res || !res.ok) {
        showToast((res && res.error) || "Could not delete prompt.");
        return;
      }
      applySavedPrompts(res.prompts || []);
      resetPromptEditor();
      showToast('Deleted "' + name + '".');
    } catch (err) {
      showToast("Could not delete prompt: " + err);
    }
  }

  async function onPromptEditorListChange() {
    const list = $("#prompt-editor-list");
    const nextId = list ? list.value : "";
    if (nextId === (state.promptEditor.selectedId || "")) return;
    if (!(await confirmDiscardPromptEdits())) {
      if (list) list.value = state.promptEditor.selectedId || "";
      return;
    }
    state.promptEditor.selectedId = nextId;
    const selected = savedPromptById(nextId);
    loadPromptEditorFields(selected);
    setPromptEditorEditing(false);
  }

  function studioInsertField() {
    const caret = state.studioCaret || {};
    const byId = caret.fieldId ? document.getElementById(caret.fieldId) : null;
    const candidates = ["studio-prompt", "studio-tool-use", "studio-search"];
    const visible = (el) => {
      if (!el) return false;
      if (el.disabled) return false;
      if (el.closest("[hidden]")) return false;
      const form = $("#create-form");
      if (form && form.classList.contains("studio-tools-mode") && el.id === "studio-prompt") {
        return false;
      }
      return true;
    };
    if (byId && candidates.includes(byId.id) && visible(byId)) return byId;
    if (studioToolsEnabled()) {
      const toolUse = $("#studio-tool-use");
      if (visible(toolUse)) return toolUse;
      const search = $("#studio-search");
      if (visible(search)) return search;
    }
    return $("#studio-prompt");
  }

  function rememberStudioCaret(el) {
    if (!el || typeof el.selectionStart !== "number") return;
    state.studioCaret = {
      fieldId: el.id,
      start: el.selectionStart,
      end: el.selectionEnd,
    };
  }

  function insertSavedPromptAtCursor(promptId) {
    const prompt = savedPromptById(promptId);
    if (!prompt) return;
    const text = String(prompt.body || "");
    const ta = studioInsertField();
    if (!ta) {
      showToast("Open the Prompt field in Creation Studio first.");
      return;
    }
    const caret = state.studioCaret || {};
    let start =
      caret.fieldId === ta.id && caret.start != null
        ? caret.start
        : ta.selectionStart != null
          ? ta.selectionStart
          : ta.value.length;
    let end =
      caret.fieldId === ta.id && caret.end != null
        ? caret.end
        : ta.selectionEnd != null
          ? ta.selectionEnd
          : start;
    if (start > ta.value.length) start = ta.value.length;
    if (end > ta.value.length) end = ta.value.length;
    if (end < start) end = start;
    const before = ta.value.slice(0, start);
    const after = ta.value.slice(end);
    ta.value = before + text + after;
    const cursor = start + text.length;
    try {
      ta.setSelectionRange(cursor, cursor);
    } catch (_) {
      /* ignore */
    }
    rememberStudioCaret(ta);
    attachIme(ta);
    const studioSel = $("#studio-saved-prompt");
    if (studioSel) studioSel.value = "";
    showToast('Inserted "' + (prompt.name || "prompt") + '".');
  }

  function onStudioSavedPromptChange() {
    const sel = $("#studio-saved-prompt");
    const id = sel ? sel.value : "";
    if (!id) return;
    insertSavedPromptAtCursor(id);
  }

  /** When Use Tools is on, Search + Tool Use replace the single Prompt field. */
  function getStudioCreateTexts() {
    if (studioToolsEnabled()) {
      return {
        toolsMode: true,
        search: getStudioSearch(),
        toolUse: getStudioToolUse(),
        prompt: getStudioToolUse(),
      };
    }
    return {
      toolsMode: false,
      search: "",
      toolUse: "",
      prompt: getStudioPrompt(),
    };
  }

  function toolAliasesReferencedInText(text, aliases) {
    const body = String(text || "");
    const list = Array.isArray(aliases) ? aliases : [];
    return list.filter((alias) => {
      const name = String(alias || "").trim();
      if (!name) return false;
      // Word-ish boundary so "read_json" matches but not as a substring of nonsense.
      const re = new RegExp(
        "(^|[^A-Za-z0-9_])" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "([^A-Za-z0-9_]|$)"
      );
      return re.test(body);
    });
  }

  function extractCreationTextBody(creation) {
    if (!creation) return "";
    const parts = [];
    const overview = (creation.overview || "").trim();
    if (overview) parts.push(overview);
    (creation.sections || []).forEach((sec) => {
      if (!sec || typeof sec !== "object") return;
      const st = (sec.title || "").trim();
      const sc = (sec.content || "").trim();
      if (st && sc) parts.push(st + "\n" + sc);
      else if (sc) parts.push(sc);
      else if (st) parts.push(st);
    });
    return parts.join("\n\n").trim();
  }

  function rememberImportedCreation(creation) {
    if (!creation || !creation.id) return;
    state.creations = [creation].concat(
      state.creations.filter((c) => c.id !== creation.id)
    );
    state.active = creation;
    renderArchives();
  }

  /**
   * Turn Clip timestamped lyrics ([0.0:4.7] LINE) into [Verse] lines.
   * Lyria accepts [Verse]/[Chorus] tags; re-sending timestamps as a
   * “new version” can look like recitation to Pro safety filters.
   */
  function formatSongBasisLyrics(lyrics) {
    const text = String(lyrics || "").trim();
    if (!text) return "";
    const timestampRe = /^\s*\[(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\]\s*(.*)$/;
    let hasTimestamps = false;
    const converted = text.split(/\r?\n/).map((line) => {
      const match = line.match(timestampRe);
      if (!match) return line;
      hasTimestamps = true;
      return String(match[3] || "").trim();
    });
    const body = converted.join("\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!body) return "";
    if (hasTimestamps && !/^\s*\[(verse|chorus|bridge|intro|outro|hook)\b/i.test(body)) {
      return "[Verse]\n" + body;
    }
    return body;
  }

  /**
   * Use an existing creation as the basis for new work of the same modality.
   * Text/audio → Studio prompt (songs: prompt + lyrics only, never the MP3).
   * Image/video → Studio media-basis panel (not the editors).
   */
  async function useCreationAsBasis(creation) {
    if (!creation) {
      showToast("Open or select a creation first.");
      return;
    }
    const mod = creationModality(creation);
    const a = api();
    if (!a) {
      showToast("Python bridge required.");
      return;
    }

    if (mod === "text" || mod === "audio") {
      const prompt = (creation.prompt || "").trim();
      const extra =
        mod === "audio"
          ? formatSongBasisLyrics(creationLyrics(creation))
          : extractCreationTextBody(creation);
      let seeded = "";
      if (prompt && extra && extra !== prompt) {
        seeded =
          prompt +
          (mod === "audio"
            ? "\n\nLyrics — use [Verse] / [Chorus] / [Bridge] tags for structure:\n\n"
            : "\n\nBased on this existing text, create an improved version:\n\n") +
          extra;
      } else {
        seeded = prompt || extra || creationTitle(creation);
      }
      clearStudioBasis();
      setStudioPrompt(seeded);
      if (studioToolsEnabled()) {
        setStudioSearch(seeded);
        setStudioToolUse("");
      }
      openWindow("form");
      showToast(
        mod === "audio"
          ? "Song prompt and lyrics loaded into Studio (text only — the MP3 is not attached). Edit, then CREATE."
          : "Text loaded into Studio as basis — edit the prompt, then CREATE."
      );
      return;
    }

    if (mod !== "image" && mod !== "video") {
      showToast("Unsupported creation type.");
      return;
    }

    const ok = await setStudioBasisFromCreation(creation);
    if (!ok) return;
    openWindow("form");
    const layout = getExtractedLayout(creation);
    showToast(
      layout
        ? "Screenshot plus extracted layout loaded into Studio. Describe the app or mockup to build, then CREATE."
        : (mod === "image" ? "Image" : "Video") +
            " loaded as Studio basis — describe the change, or prompt extract the text, transcribe, or extract the layout, then CREATE."
    );
  }

  async function sendCreationToCreator(creation) {
    if (!creation) {
      showToast("Open or select a creation first.");
      return false;
    }
    const mod = creationModality(creation);
    if (mod !== "image" && mod !== "video") {
      showToast("Save and Send to Creator is for images and videos.");
      return false;
    }
    const ok = await setStudioBasisFromCreation(creation, { anonymous: true });
    if (!ok) return false;
    openWindow("form");
    showToast(
      (mod === "image" ? "Image" : "Video") +
        " sent to Creation Studio — describe the change and CREATE for a new Archive item, or prompt extract the text, transcribe, or extract the layout."
    );
    return true;
  }

  function clearStudioBasis() {
    state.studioBasis = null;
    renderStudioBasisPanel();
  }

  function parseStudioBasisWidth(width) {
    const raw = Number(width);
    if (!Number.isFinite(raw)) return 280;
    return Math.round(Math.max(160, Math.min(raw, 1200)));
  }

  function clampStudioBasisWidth(width, layoutEl) {
    const layout = layoutEl || $("#studio-layout");
    const raw = parseStudioBasisWidth(width);
    const layoutW = layout ? layout.clientWidth : 0;
    const minW = 160;
    const reserved = 280;
    const maxW =
      layoutW > minW + reserved ? layoutW - reserved : Math.max(minW, layoutW - 80);
    return Math.round(Math.max(minW, Math.min(raw, maxW || raw)));
  }

  function applyStudioBasisWidth(width, opts) {
    const panel = $("#studio-basis-panel");
    const splitter = $("#studio-basis-splitter");
    const next = clampStudioBasisWidth(width);
    state.studioBasisWidth = next;
    if (panel) panel.style.width = next + "px";
    if (splitter) {
      splitter.setAttribute("aria-valuenow", String(next));
      splitter.setAttribute("aria-valuemin", "160");
      splitter.setAttribute("aria-valuemax", "1200");
    }
    if (opts && opts.persist) persistStudioBasisWidthSoon();
  }

  function persistStudioBasisWidthSoon() {
    clearTimeout(_studioBasisWidthSaveTimer);
    _studioBasisWidthSaveTimer = setTimeout(() => {
      void persistStudioBasisWidth();
    }, 250);
  }

  async function persistStudioBasisWidth() {
    const a = api();
    if (!a) return;
    try {
      const res = await a.save_settings({
        ui: { studio_basis_width: parseStudioBasisWidth(state.studioBasisWidth) },
      });
      if (res && res.config) state.config = res.config;
    } catch (_) {
      /* ignore */
    }
  }

  function renderStudioBasisPanel() {
    const win = $("#win-form");
    const panel = $("#studio-basis-panel");
    const splitter = $("#studio-basis-splitter");
    const preview = $("#studio-basis-preview");
    const label = $("#studio-basis-label");
    const layout = $("#studio-layout");
    const basis = state.studioBasis;
    if (!panel || !preview) return;

    if (!basis) {
      panel.hidden = true;
      if (splitter) splitter.hidden = true;
      if (win) win.classList.remove("has-studio-basis");
      if (layout) layout.classList.remove("has-basis");
      preview.innerHTML = '<p class="muted">No media loaded</p>';
      if (label) label.textContent = "";
      requestAnimationFrame(() => syncDesktopScrollExtent());
      return;
    }

    panel.hidden = false;
    if (splitter) splitter.hidden = false;
    if (layout) layout.classList.add("has-basis");
    if (win) win.classList.add("has-studio-basis");
    applyStudioBasisWidth(state.studioBasisWidth);

    preview.innerHTML = "";
    if (basis.modality === "video") {
      const vid = document.createElement("video");
      vid.src = basis.fileUrl;
      vid.controls = true;
      vid.playsInline = true;
      preview.appendChild(vid);
    } else {
      const img = document.createElement("img");
      img.src = basis.fileUrl;
      img.alt = basis.title || "Basis image";
      preview.appendChild(img);
    }
    if (label) {
      const hasLayout = !!(basis.layout && typeof basis.layout === "object");
      const kind = hasLayout
        ? basis.modality === "video"
          ? "Video + UI layout"
          : "Image + UI layout"
        : basis.modality === "video"
          ? "Video basis"
          : "Image basis";
      if (basis.title) {
        label.textContent = kind + ": " + basis.title;
      } else {
        label.textContent = kind;
      }
    }
    requestAnimationFrame(() => syncDesktopScrollExtent());
  }

  async function setStudioBasisFromCreation(creation, opts) {
    const a = api();
    if (!a || !creation) return false;
    const anonymous = !!(opts && opts.anonymous);
    const mod = creationModality(creation);
    if (mod !== "image" && mod !== "video") {
      showToast("Only image or video can be a media basis.");
      return false;
    }
    const payload = await a.get_media_payload(creation);
    const previewUrl =
      (payload && (payload.fileUrl || payload.dataUrl)) || "";
    if (!payload || !payload.ok || !previewUrl) {
      showToast((payload && payload.error) || "Could not load media for basis.");
      return false;
    }
    state.studioBasis = {
      creationId: creation.id,
      modality: mod,
      fileUrl: previewUrl,
      mimeType: payload.mimeType || creation.mimeType || "",
      title: anonymous ? "" : creationTitle(creation),
      mediaPath: creation.mediaPath || "",
      layout: getExtractedLayout(creation),
    };
    if (!anonymous) {
      const layout = getExtractedLayout(creation);
      if (layout) {
        setStudioPrompt(formatLayoutBasisPrompt(layout, getStudioPrompt()));
        if (studioToolsEnabled()) {
          setStudioSearch(formatLayoutBasisPrompt(layout, getStudioSearch()));
        }
      } else if (!(getStudioPrompt() || "").trim() && (creation.prompt || "").trim()) {
        setStudioPrompt(creation.prompt.trim());
        if (
          studioToolsEnabled() &&
          !(getStudioSearch() || "").trim() &&
          (creation.prompt || "").trim()
        ) {
          setStudioSearch(creation.prompt.trim());
        }
      }
    }
    renderStudioBasisPanel();
    return true;
  }

  async function studioLoadTextFile() {
    const a = api();
    if (!a) return;
    try {
      const res = await a.import_text_file(false);
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      clearStudioBasis();
      setStudioPrompt(res.text || "");
      if (studioToolsEnabled()) {
        setStudioSearch(res.text || "");
      }
      openWindow("form");
      showToast(
        studioToolsEnabled()
          ? "Text loaded into Search — edit Search / Tool Use and CREATE when ready."
          : "Text loaded into Studio prompt — edit and CREATE when ready."
      );
    } catch (err) {
      showToast("Load failed: " + err);
    }
  }

  async function studioLoadMediaFile(modality) {
    const a = api();
    if (!a) return;
    beginBusy("Loading " + modality, "Reading file for Studio basis…", {
      delayMs: 0,
    });
    try {
      const res = await a.import_media_file(modality);
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      rememberImportedCreation(res.creation);
      const ok = await setStudioBasisFromCreation(res.creation);
      if (!ok) return;
      openWindow("form");
      showToast(
        (modality === "image" ? "Image" : "Video") +
          " loaded as Studio basis — describe the change, or prompt extract the text, transcribe, or extract the layout, then CREATE."
      );
    } catch (err) {
      showToast("Load failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function archivesImportText() {
    const a = api();
    if (!a) return;
    try {
      const res = await a.import_text_file(true);
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      if (res.creation) {
        rememberImportedCreation(res.creation);
        renderDocument(res.creation);
        openWindow("viewer");
      }
      openWindow("library");
      showToast("Text imported into Archives");
    } catch (err) {
      showToast("Import failed: " + err);
    }
  }

  async function archivesImportMedia(modality) {
    const a = api();
    if (!a) return;
    const kind =
      modality === "video" ? "video" : modality === "audio" ? "audio" : "image";
    beginBusy("Importing " + kind, "Copying into Archives…", { delayMs: 0 });
    try {
      const res = await a.import_media_file(kind);
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      if (res.creation) {
        rememberImportedCreation(res.creation);
        renderDocument(res.creation);
        openWindow("viewer");
      }
      openWindow("library");
      showToast(
        (kind === "image" ? "Image" : kind === "audio" ? "Audio" : "Video") +
          " imported into Archives"
      );
    } catch (err) {
      showToast("Import failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  // ── Window manager ─────────────────────────────────────────────────
  let windowZTop = 20;

  function windowsLayer() {
    return document.getElementById("windows-layer") || document.getElementById("desktop");
  }

  function adoptWindowsIntoLayer() {
    const layer = document.getElementById("windows-layer");
    if (!layer) return;
    document.querySelectorAll(".app-window").forEach((el) => {
      if (el.parentElement !== layer) layer.appendChild(el);
    });
  }

  function bringWindowToFront(id) {
    if (!id) return;
    const order = (state.windowZOrder || []).filter((w) => w !== id);
    order.push(id);
    state.windowZOrder = order;
    const el = document.getElementById("win-" + id);
    if (!el) return;
    const layer = windowsLayer();
    // Reparenting/restacking during mousedown cancels the following click, so
    // leave a window that is already front-most alone.
    if (layer && layer.lastElementChild === el) return;
    windowZTop += 1;
    el.style.setProperty("z-index", String(windowZTop), "important");
    if (layer) layer.appendChild(el);
  }

  // Fields use the native caret, selection, and editing shortcuts. The old
  // custom IME existed to hide Windows' overlay caret above stacked Win98
  // windows; this app shows one screen at a time.
  const ime = {
    trap: null,
    caretEl: null,
    target: null,
    drag: null,
    resume: null,
    selStart: 0,
    selEnd: 0,
  };

  function isImeField(el) {
    if (!el) return false;
    if (!el.closest || !el.closest(".app-window")) return false;
    if (el.disabled || el.readOnly) return false;
    const tag = (el.tagName || "").toLowerCase();
    if (tag === "textarea") return true;
    if (tag !== "input") return false;
    const type = String(el.type || "text").toLowerCase();
    return type === "text" || type === "password" || type === "search" || type === "url" || type === "email";
  }

  function attachIme(field) {
    if (!isImeField(field)) return;
    ime.target = field;
    if (typeof field.selectionStart === "number") rememberStudioCaret(field);
    try {
      field.focus({ preventScroll: true });
    } catch (_err) {
      try { field.focus(); } catch (_err2) { /* ignore */ }
    }
  }

  function refreshImeField(_field) {}

  function syncImeCaret() {}

  function ensureImeBridge() {}

  function detachIme(opts) {
    const keepResume = !!(opts && opts.resume);
    if (keepResume && ime.target) ime.resume = ime.target;
    else if (!keepResume) ime.resume = null;
    ime.target = null;
  }

  function hideCaretOutsideWindow(id) {
    if (ime.target) {
      const host = ime.target.closest(".app-window");
      if (!host || host.dataset.window !== id) {
        detachIme();
      } else {
        syncImeCaret();
      }
    }
    const active = document.activeElement;
    if (!active || active === document.body || active === document.documentElement) {
      return;
    }
    const host = active.closest(".app-window");
    if (!host) return;
    if (host.dataset.window === id) return;
    const tag = (active.tagName || "").toLowerCase();
    const editable =
      tag === "textarea" ||
      tag === "input" ||
      tag === "select" ||
      active.isContentEditable;
    if (!editable) return;
    if (typeof active.selectionStart === "number") rememberStudioCaret(active);
    active.blur();
  }

  const SCREEN_IDS = [
    "form",
    "library",
    "viewer",
    "image-edit",
    "video-edit",
    "prompt-editor",
    "control",
  ];
  const SCREENS_WITH_MENU = {
    form: true,
    library: true,
    viewer: true,
    "image-edit": true,
    "video-edit": true,
  };

  function closeAppMenus() {
    const panel = $("#menu-app-panel");
    const btn = $("#menu-app-btn");
    if (panel) panel.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function toggleAppMenu(force) {
    const panel = $("#menu-app-panel");
    const btn = $("#menu-app-btn");
    if (!panel || !btn) return;
    const open = typeof force === "boolean" ? force : panel.hidden;
    if (open) {
      panel.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    } else {
      closeAppMenus();
    }
  }

  function syncAppMenus(id) {
    const panel = $("#menu-app-panel");
    if (panel) {
      panel.querySelectorAll(".menu-group").forEach((g) => {
        g.setAttribute(
          "data-active",
          g.getAttribute("data-screen") === id ? "1" : "0"
        );
      });
    }
    const wrap = $("#app-overflow-menu");
    if (wrap) wrap.hidden = !SCREENS_WITH_MENU[id];
    closeAppMenus();
  }

  function pauseViewerMedia() {
    const root = $("#win-viewer");
    if (!root) return;
    root.querySelectorAll("audio, video").forEach((el) => {
      try {
        el.pause();
      } catch (_) {
        /* ignore */
      }
    });
  }

  function showScreen(id) {
    if (!id || SCREEN_IDS.indexOf(id) === -1) return;
    const prev = state.focused;
    if (prev === "control" && id !== "control") {
      void persistSettingsNow({ applyDisplay: true });
    }
    if (prev === "viewer" && id !== "viewer") pauseViewerMedia();
    if (prev === "video-edit" && id !== "video-edit") {
      const player = $("#video-edit-player");
      if (player) {
        try {
          player.pause();
        } catch (_) {
          /* ignore */
        }
      }
    }
    state.focused = id;
    state.open[id] = true;
    state.minimized[id] = false;
    document.querySelectorAll(".app-window").forEach((w) => {
      const match = w.dataset.window === id;
      w.hidden = !match;
      w.classList.toggle("focused", match);
    });
    const sel = $("#screen-select");
    if (sel && sel.value !== id) sel.value = id;
    syncAppMenus(id);
    hideCaretOutsideWindow(id);
    if (id === "control") syncControlPanelWidth();
    if (id === "form") syncStudioToolsPanel();
    if (id === "prompt-editor") {
      syncPromptEditorUi();
      refreshSavedPrompts();
    }
    if (id === "viewer") {
      showViewerOpenButton();
      if (!state.active) prepareEmptyViewer();
      else syncViewerChrome(state.active);
    }
    if (id === "image-edit" && !imageEdit.creationId) {
      prepareEmptyImageEditor();
    }
    if (id === "video-edit" && !videoEdit.creationId) {
      prepareEmptyVideoEditor();
    }
  }

  function focusWindow(id) {
    showScreen(id);
  }

  function openWindow(id) {
    showScreen(id);
  }

  let _geminiModelsRefreshSeq = 0;

  async function refreshGeminiModelsForControlPanel() {
    const a = api();
    const textSel = $("#gemini-text-model");
    const imageSel = $("#gemini-image-model");
    const videoSel = $("#gemini-video-model");
    const audioSel = $("#gemini-audio-model");
    if (!a || !textSel || !imageSel || !videoSel || !audioSel) return;

    const seq = ++_geminiModelsRefreshSeq;
    const prev = {
      text: textSel.value,
      image: imageSel.value,
      video: videoSel.value,
      audio: audioSel.value,
    };
    beginBusy(
      "Refreshing Gemini models",
      "Checking Google for models available to your API key…",
      {
        delayMs: 0,
        percent: 15,
        hint:
          "Each modality picker is filled with compatible models only. Requires a saved Gemini API key.",
      }
    );

    try {
      const res = await a.list_gemini_models();
      if (seq !== _geminiModelsRefreshSeq) return;
      const models = (res && res.models) || [];
      fillGeminiModalitySelect(textSel, prev.text, models, "text");
      fillGeminiModalitySelect(imageSel, prev.image, models, "image");
      fillGeminiModalitySelect(videoSel, prev.video, models, "video");
      fillGeminiModalitySelect(audioSel, prev.audio, models, "audio");
      if (res && res.ok) {
        updateBusy(
          "Loaded " +
            models.length +
            " Gemini model" +
            (models.length === 1 ? "" : "s") +
            " from Google.",
          100
        );
      } else {
        updateBusy(
          (res && res.error) ||
            "Could not refresh live models — showing the built-in fallback list.",
          100
        );
        if (res && res.error) showToast(res.error);
      }
      updateStudioBackendLabel({
        config: {
          backend: { provider: "gemini" },
          gemini: {
            text_model: textSel.value,
            image_model: imageSel.value,
            video_model: videoSel.value,
            audio_model: audioSel.value,
          },
        },
      });
    } catch (err) {
      if (seq !== _geminiModelsRefreshSeq) return;
      showToast("Model list refresh failed: " + err);
    } finally {
      if (seq === _geminiModelsRefreshSeq) {
        endBusy("Ready");
        requestAnimationFrame(() => syncDesktopScrollExtent());
      }
    }
  }

  async function refreshHfModelsForControlPanel() {
    const a = api();
    const textSel = $("#hf-text-model");
    const imageSel = $("#hf-image-model");
    const videoSel = $("#hf-video-model");
    if (!a || !textSel || !imageSel || !videoSel) return;

    const go = await showConfirm(
      "Refresh Hub models?",
      "This contacts Hugging Face and loads up to 20 popular models for each of Text, Image, and Video (ranked by downloads).\n\n" +
        "This usually takes about 5–15 seconds, depending on your connection.\n\n" +
        "OK — fetch the model lists now.\n" +
        "Cancel — keep the current lists.",
      { yesLabel: "OK", noLabel: "Cancel" }
    );
    if (!go) return;

    const seq = ++_hfModelsRefreshSeq;
    const prev = {
      text: textSel.value,
      image: imageSel.value,
      video: videoSel.value,
    };
    beginBusy(
      "Refreshing Hub models",
      "Asking Hugging Face for top text, image, and video models…",
      {
        delayMs: 0,
        percent: 15,
        hint: "Up to 20 models per modality, ranked by downloads. Usually 5–15 seconds.",
      }
    );

    try {
      const res = await a.list_hf_models();
      if (seq !== _hfModelsRefreshSeq) return;
      const models = (res && res.models) || [];
      state.suggestedHfModels = models;
      fillHfModalitySelect(textSel, prev.text, models, "text");
      fillHfModalitySelect(imageSel, prev.image, models, "image");
      fillHfModalitySelect(videoSel, prev.video, models, "video");
      if (res && res.ok) {
        const live = res.liveCount != null ? res.liveCount : models.length;
        updateBusy(
          "Loaded " +
            live +
            " Hub model" +
            (live === 1 ? "" : "s") +
            " (up to 20 per modality).",
          100
        );
        showToast("Hub model lists refreshed");
      } else {
        updateBusy(
          (res && res.error) ||
            "Could not refresh Hub models — showing the curated fallback list.",
          100
        );
        if (res && res.error) showToast(res.error);
      }
      updateStudioBackendLabel({
        config: {
          backend: { provider: "huggingface" },
          gemini: currentGeminiUiConfig(),
          openrouter: currentOpenRouterUiConfig(),
          huggingface: currentHfUiConfig(),
        },
      });
    } catch (err) {
      if (seq !== _hfModelsRefreshSeq) return;
      showToast("Hub model list refresh failed: " + err);
    } finally {
      if (seq === _hfModelsRefreshSeq) {
        endBusy("Ready");
        requestAnimationFrame(() => syncDesktopScrollExtent());
      }
    }
  }

  async function refreshOpenRouterModelsForControlPanel() {
    const a = api();
    const textSel = $("#openrouter-text-model");
    const imageSel = $("#openrouter-image-model");
    const videoSel = $("#openrouter-video-model");
    if (!a || !textSel || !imageSel || !videoSel) return;

    const seq = ++_geminiModelsRefreshSeq;
    const prev = {
      text: textSel.value,
      image: imageSel.value,
      video: videoSel.value,
    };
    beginBusy(
      "Refreshing Gemini models",
      "Checking Google for models available to your API key…",
      {
        delayMs: 0,
        percent: 15,
        hint:
          "Each modality picker is filled with compatible models only. Requires a saved Gemini API key.",
      }
    );

    try {
      const res = await a.list_gemini_models();
      if (seq !== _geminiModelsRefreshSeq) return;
      const models = (res && res.models) || [];
      fillGeminiModalitySelect(textSel, prev.text, models, "text");
      fillGeminiModalitySelect(imageSel, prev.image, models, "image");
      fillGeminiModalitySelect(videoSel, prev.video, models, "video");
      if (res && res.ok) {
        updateBusy(
          "Loaded " +
            models.length +
            " Gemini model" +
            (models.length === 1 ? "" : "s") +
            " from Google.",
          100
        );
      } else {
        updateBusy(
          (res && res.error) ||
            "Could not refresh live models — showing the built-in fallback list.",
          100
        );
        if (res && res.error) showToast(res.error);
      }
      updateStudioBackendLabel({
        config: {
          backend: { provider: "gemini" },
          gemini: {
            text_model: textSel.value,
            image_model: imageSel.value,
            video_model: videoSel.value,
          },
        },
      });
    } catch (err) {
      if (seq !== _geminiModelsRefreshSeq) return;
      showToast("Model list refresh failed: " + err);
    } finally {
      if (seq === _geminiModelsRefreshSeq) {
        endBusy("Ready");
        requestAnimationFrame(() => syncDesktopScrollExtent());
      }
    }
  }

  function syncDesktopScrollExtent() {
    const desktop = $("#desktop");
    const layer = $("#windows-layer");
    if (!desktop || !layer) return;
    // Desktop is a fixed logical screen (DPI zoom). Do not grow a page scrollbar.
    desktop.style.minHeight = "";
    layer.style.minHeight = "";
    clampWindowsToDesktop();
  }

  function clampWindowsToDesktop() {
    const bounds = getDesktopBounds();
    document.querySelectorAll(".app-window").forEach((win) => {
      if (win.hidden || win.classList.contains("minimized")) return;
      if (win.classList.contains("maximized")) return;
      let left = parseFloat(win.style.left);
      let top = parseFloat(win.style.top);
      if (!Number.isFinite(left)) left = win.offsetLeft || 0;
      if (!Number.isFinite(top)) top = win.offsetTop || 0;
      const w = win.offsetWidth || 0;
      const h = win.offsetHeight || 0;
      if (w < bounds.width) left = Math.min(Math.max(left, 0), bounds.width - w);
      else left = 0;
      if (h < bounds.height) top = Math.min(Math.max(top, 0), bounds.height - h);
      else top = 0;
      win.style.left = left + "px";
      win.style.top = top + "px";
    });
  }

  async function cancelControlPanel() {
    // Discard unsaved Control Panel edits by restoring last saved config.
    const a = api();
    if (a) {
      try {
        const boot = await a.get_bootstrap();
        state.config = boot.config || state.config;
        fillControlPanel(boot);
      } catch (_) {
        if (state.config) {
          fillControlPanel({
            config: state.config,
            suggestedGeminiModels: [],
          });
        }
      }
    } else if (state.config) {
      fillControlPanel({
        config: state.config,
        suggestedGeminiModels: [],
      });
    }
    clearGeminiApiKeyInputs();
    closeWindow("control");
  }

  async function confirmDiscardEditorEdits(kind) {
    const dirty = kind === "image" ? imageEdit.dirty : videoEdit.dirty;
    if (!dirty) return true;
    const label = kind === "image" ? "image" : "video";
    const winId = kind === "image" ? "image-edit" : "video-edit";
    const discard = await showConfirm(
      "Unsaved edits",
      "You have unsaved " +
        label +
        " edits. Closing will discard them.\n\nDiscard and close, or keep editing so you can save?",
      {
        yesLabel: "Discard",
        noLabel: "Keep Editing",
        focusNo: true,
      }
    );
    if (!discard) {
      if (state.open[winId]) focusWindow(winId);
      else openWindow(winId);
      return false;
    }
    return true;
  }

  async function requestCloseWindow(id) {
    if (state.studioAddToolOpen) {
      showToast("Close the Add Tool dialog first.");
      return false;
    }
    if (id === "image-edit") {
      if (!(await confirmDiscardEditorEdits("image"))) return false;
    } else if (id === "video-edit") {
      if (!(await confirmDiscardEditorEdits("video"))) return false;
    }
    if (id === "prompt-editor") {
      if (!(await confirmDiscardPromptEdits())) return false;
    }
    closeWindow(id);
    return true;
  }

  function stopViewerMedia() {
    const root = $("#win-viewer");
    if (!root) return;
    root.querySelectorAll("audio, video").forEach((el) => {
      try {
        el.pause();
        el.currentTime = 0;
      } catch (_) {
        /* ignore unseekable / already torn-down elements */
      }
    });
  }

  function closeWindow(id) {
    if (id === "image-edit") {
      imageEdit.sourceImg = null;
      imageEdit.creationId = null;
      imageEdit.crop = null;
      imageEdit.cropDrag = null;
      imageEdit.filters = null;
      imageEdit.rotation = 0;
      imageEdit.dirty = false;
      if (window.R98ImageEdit) {
        writeImageEditFiltersToUi(window.R98ImageEdit.DEFAULT_FILTERS);
        if ($("#edit-rotation")) $("#edit-rotation").value = 0;
        syncImageEditValueLabels();
      }
    }
    if (id === "video-edit") {
      videoEdit.dirty = false;
      resetVideoEditRuntime();
    }
    if (id === "prompt-editor") {
      resetPromptEditor();
    }
    const next =
      (id === "image-edit" || id === "video-edit") && state.active
        ? "viewer"
        : "form";
    showScreen(next);
  }

  function minimizeWindow(id) {
    state.minimized[id] = true;
    const el = document.getElementById("win-" + id);
    if (el) el.classList.add("minimized");
    renderTaskbar();
    syncDesktopScrollExtent();
  }

  function updateMaximizeButton(id) {
    const el = document.getElementById("win-" + id);
    if (!el) return;
    const btn = el.querySelector(
      '.title-bar-controls button[data-action="maximize"]'
    );
    if (!btn) return;
    const isMax = !!state.maximized[id];
    btn.setAttribute("aria-label", isMax ? "Restore" : "Maximize");
    btn.title = isMax ? "Restore" : "Maximize";
  }

  // Snapshot the window's current on-screen geometry (relative to the
  // windows layer) so maximize can be undone later.
  function captureWindowGeometry(win, layerRect) {
    const left = parseFloat(win.style.left);
    const top = parseFloat(win.style.top);
    const scale = uiZoomFactor();
    return {
      left: Number.isFinite(left)
        ? left
        : (win.getBoundingClientRect().left - layerRect.left) / scale,
      top: Number.isFinite(top)
        ? top
        : (win.getBoundingClientRect().top - layerRect.top) / scale,
      width: win.style.width || win.offsetWidth + "px",
      height: win.style.height || win.offsetHeight + "px",
    };
  }

  function maximizeWindow(id) {
    const el = document.getElementById("win-" + id);
    if (!el || state.maximized[id]) return;
    if (state.minimized[id]) {
      state.minimized[id] = false;
      el.classList.remove("minimized");
    }
    const layer = $("#windows-layer") || $("#desktop");
    const layerRect = layer.getBoundingClientRect();
    state.preMaximizeRect[id] = captureWindowGeometry(el, layerRect);
    state.maximized[id] = true;
    el.classList.add("maximized");
    updateMaximizeButton(id);
    focusWindow(id);
    requestAnimationFrame(() => syncDesktopScrollExtent());
  }

  function restoreWindow(id) {
    const el = document.getElementById("win-" + id);
    if (!el || !state.maximized[id]) return;
    const prev = state.preMaximizeRect[id];
    state.maximized[id] = false;
    el.classList.remove("maximized");
    if (prev) {
      el.style.left = typeof prev.left === "number" ? prev.left + "px" : prev.left;
      el.style.top = typeof prev.top === "number" ? prev.top + "px" : prev.top;
      el.style.width = prev.width;
      el.style.height = prev.height;
    }
    updateMaximizeButton(id);
    focusWindow(id);
    requestAnimationFrame(() => syncDesktopScrollExtent());
  }

  function toggleMaximizeWindow(id) {
    if (state.maximized[id]) restoreWindow(id);
    else maximizeWindow(id);
  }

  function toggleStartMenu(force) {
    const menu = $("#start-menu");
    if (!menu) return;
    if (typeof force === "boolean") menu.hidden = !force;
    else menu.hidden = !menu.hidden;
  }

  // ── Drag windows by title bar ───────────────────────────────────────
  let dragState = null;

  function getDesktopBounds() {
    const layer = windowsLayer();
    return {
      width: layer ? layer.clientWidth : window.innerWidth,
      height: layer ? layer.clientHeight : window.innerHeight,
    };
  }

  function getDesktopWorkArea() {
    const bounds = getDesktopBounds();
    const icons = document.getElementById("desktop-icons");
    const pad = 12;
    let left = pad;
    if (icons) left = Math.round(icons.offsetLeft + icons.offsetWidth + pad);
    const top = pad;
    let width = bounds.width - left - pad;
    let height = bounds.height - top - pad;
    if (width < 320) {
      left = pad;
      width = Math.max(0, bounds.width - pad * 2);
    }
    height = Math.max(0, height);
    return { left, top, width, height };
  }

  function layoutWindowInWorkArea(el) {
    if (!el || el.classList.contains("maximized")) return;
    const area = getDesktopWorkArea();
    el.style.left = area.left + "px";
    el.style.top = area.top + "px";
    el.style.width = area.width + "px";
    el.style.height = area.height + "px";
    el.style.right = "auto";
    el.style.maxWidth = "none";
    el.style.maxHeight = "none";
    el.style.minWidth = "0";
    el.style.minHeight = "0";
  }

  function layoutOpenWindowsInWorkArea() {
    document.querySelectorAll(".app-window").forEach((el) => {
      const id = el.dataset.window;
      if (!id || !state.open[id] || state.minimized[id] || state.maximized[id]) {
        return;
      }
      if (el.hidden) return;
      layoutWindowInWorkArea(el);
    });
  }

  function clampWindowPosition(win, left, top) {
    const bounds = getDesktopBounds();
    const w = win.offsetWidth || 0;
    const h = win.offsetHeight || 0;
    const minVisible = 48;
    const maxLeft = bounds.width - minVisible;
    const maxTop = Math.max(0, bounds.height - minVisible);
    const minLeft = -(w - minVisible);
    left = Math.min(Math.max(left, minLeft), maxLeft);
    top = Math.min(Math.max(top, 0), maxTop);
    return { left, top };
  }

  function enableWindowDragging() {
    document.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".title-bar-controls")) return;
      const titleBar = e.target.closest(".app-window > .title-bar");
      if (!titleBar) return;
      const win = titleBar.parentElement;
      if (!win || !win.classList.contains("app-window")) return;

      const id = win.dataset.window;
      if (id && state.maximized[id]) restoreWindow(id);
      if (id) focusWindow(id);

      const startLeft = parseFloat(win.style.left);
      const startTop = parseFloat(win.style.top);

      dragState = {
        win,
        startX: e.clientX,
        startY: e.clientY,
        origLeft: Number.isFinite(startLeft) ? startLeft : win.offsetLeft || 0,
        origTop: Number.isFinite(startTop) ? startTop : win.offsetTop || 0,
        scale: uiZoomFactor(),
        dragging: false,
      };
    });

    document.addEventListener("mousemove", (e) => {
      if (!dragState) return;
      if (!dragState.dragging) {
        const adx = e.clientX - dragState.startX;
        const ady = e.clientY - dragState.startY;
        if (adx * adx + ady * ady < 16) return;
        dragState.dragging = true;
        dragState.win.classList.add("dragging");
      }
      const scale = dragState.scale || 1;
      const dx = (e.clientX - dragState.startX) / scale;
      const dy = (e.clientY - dragState.startY) / scale;
      const next = clampWindowPosition(
        dragState.win,
        dragState.origLeft + dx,
        dragState.origTop + dy
      );
      dragState.win.style.left = next.left + "px";
      dragState.win.style.top = next.top + "px";
      dragState.win.style.right = "auto";
      syncImeCaret();
    });

    document.addEventListener("mouseup", () => {
      if (!dragState) return;
      dragState.win.classList.remove("dragging");
      dragState = null;
    });

    // Cancel drag if pointer leaves the window unexpectedly
    window.addEventListener("blur", () => {
      if (!dragState) return;
      dragState.win.classList.remove("dragging");
      dragState = null;
    });
  }

  // ── Resize windows from bottom-right grip ───────────────────────────
  let resizeState = null;

  function uiZoomFactor() {
    const fromState = Number(state.uiScale);
    if (Number.isFinite(fromState) && fromState > 0) return fromState;
    const fromVar = Number(
      getComputedStyle(document.documentElement).getPropertyValue("--ui-scale")
    );
    if (Number.isFinite(fromVar) && fromVar > 0) return fromVar;
    return 1;
  }

  function enableWindowResizing() {
    document.querySelectorAll(".app-window").forEach((win) => {
      // Control Panel uses fixed tab widths + vertical scroll — no resize grip.
      if (win.id === "win-control") {
        win.querySelectorAll(".window-resize-handle").forEach((h) => h.remove());
        return;
      }
      if (win.querySelector(".window-resize-handle")) return;
      const handle = document.createElement("div");
      handle.className = "window-resize-handle";
      handle.title = "Resize";
      win.appendChild(handle);
    });

    document.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const handle = e.target.closest(".window-resize-handle");
      if (!handle) return;
      const win = handle.closest(".app-window");
      if (!win || win.id === "win-control" || win.classList.contains("maximized"))
        return;
      const id = win.dataset.window;
      if (id) focusWindow(id);

      // Inline max-* fight explicit sizing and make the grip feel like it slips.
      win.style.maxHeight = "none";
      win.style.maxWidth = "none";

      const scale = uiZoomFactor();
      resizeState = {
        win,
        handle,
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        // offset* matches style width/height (CSS px); client deltas are zoomed
        origW: win.offsetWidth,
        origH: win.offsetHeight,
        origLeft: parseFloat(win.style.left) || win.offsetLeft || 0,
        origTop: parseFloat(win.style.top) || win.offsetTop || 0,
        scale,
      };
      win.classList.add("resizing");
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      e.preventDefault();
      e.stopPropagation();
    });

    document.addEventListener("pointermove", (e) => {
      if (!resizeState || e.pointerId !== resizeState.pointerId) return;
      const layer = $("#windows-layer") || $("#desktop");
      const scale = resizeState.scale || 1;
      const deskW = layer ? layer.clientWidth : window.innerWidth;
      const deskH = layer ? layer.clientHeight : window.innerHeight;
      const roomW = Math.max(160, deskW - resizeState.origLeft - 8);
      const roomH = Math.max(120, deskH - resizeState.origTop - 8);
      const minW = Math.min(
        roomW,
        resizeState.win.id === "win-form"
          ? resizeState.win.classList.contains("has-studio-basis")
            ? 720
            : 400
          : 320
      );
      const minH = Math.min(
        roomH,
        resizeState.win.id === "win-form" ? 400 : 180
      );
      let nextW = resizeState.origW + (e.clientX - resizeState.startX) / scale;
      let nextH = resizeState.origH + (e.clientY - resizeState.startY) / scale;
      nextW = Math.max(minW, Math.min(nextW, roomW));
      nextH = Math.max(minH, Math.min(nextH, roomH));
      resizeState.win.style.width = Math.round(nextW) + "px";
      resizeState.win.style.height = Math.round(nextH) + "px";
      syncImeCaret();
    });

    const endResize = (e) => {
      if (!resizeState) return;
      if (e && e.pointerId != null && e.pointerId !== resizeState.pointerId) return;
      try {
        if (resizeState.handle && resizeState.pointerId != null) {
          resizeState.handle.releasePointerCapture(resizeState.pointerId);
        }
      } catch (_) {
        /* ignore */
      }
      resizeState.win.classList.remove("resizing");
      resizeState = null;
      syncDesktopScrollExtent();
    };

    document.addEventListener("pointerup", endResize);
    document.addEventListener("pointercancel", endResize);

    window.addEventListener("blur", () => {
      if (!resizeState) return;
      resizeState.win.classList.remove("resizing");
      resizeState = null;
    });
  }

  function renderTaskbar() {
    const host = $("#taskbar-windows");
    if (!host) return;
    const titles = {
      form: "Creation Studio",
      viewer: state.active ? "Viewer — " + creationTitle(state.active) : "Viewer",
      library: "Archives",
      control: "Control Panel",
      "image-edit": "Image Editor",
      "video-edit": "Video Editor",
      "prompt-editor": "Prompt Editor",
    };
    const ids = ["form", "viewer", "library", "control", "image-edit", "video-edit", "prompt-editor"].filter(
      (id) => state.open[id]
    );
    const existing = [...host.querySelectorAll(".task-btn")].map((b) =>
      b.getAttribute("data-window")
    );
    const sameSet =
      existing.length === ids.length && existing.every((id, i) => id === ids[i]);
    if (!sameSet) {
      host.innerHTML = "";
      ids.forEach((id) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "task-btn";
        btn.setAttribute("data-window", id);
        const activate = (e) => {
          e.stopPropagation();
          e.preventDefault();
          if (state.minimized[id]) {
            state.minimized[id] = false;
            const win = document.getElementById("win-" + id);
            if (win) win.classList.remove("minimized");
          }
          focusWindow(id);
          toggleStartMenu(false);
        };
        btn.addEventListener("mousedown", activate);
        btn.addEventListener("click", activate);
        host.appendChild(btn);
      });
    }
    ids.forEach((id) => {
      const btn = host.querySelector('.task-btn[data-window="' + id + '"]');
      if (!btn) return;
      btn.textContent = titles[id];
      btn.classList.toggle(
        "active",
        state.focused === id && !state.minimized[id]
      );
    });
  }

  function tickClock() {
    const el = $("#taskbar-clock");
    if (!el) return;
    const d = new Date();
    el.textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  // ── Document render ────────────────────────────────────────────────
  function resolveTheme(creation) {
    const t = (creation && creation.theme) || {};
    return {
      themeName: t.themeName || "Default",
      bgColor: t.bgColor || "#0055aa",
      cardBg: t.cardBg || "#ffffff",
      textColor: t.textColor || "#000000",
      accentColor: t.accentColor || "#ffaa00",
      headerBg: t.headerBg || "#0055aa",
      fontStyle: t.fontStyle || "retro-sans",
      boxArtStyle: t.boxArtStyle || "",
    };
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatCreatedAt(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch (_) {
      return String(iso).slice(0, 10);
    }
  }

  function stopSpeech() {
    if ("speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {
        /* ignore */
      }
    }
    state.speechPlaying = false;
    const btn = $("#btn-voice");
    if (btn) {
      btn.textContent = "Voice Reader";
      btn.classList.remove("speaking");
    }
  }

  function toggleVoiceReader() {
    if (!state.active) return;
    if (!("speechSynthesis" in window)) {
      showToast("Speech synthesis is not supported in this WebView");
      return;
    }
    if (state.speechPlaying) {
      stopSpeech();
      return;
    }
    const c = state.active;
    const parts = [
      c.game + " for " + c.platform + ".",
      c.creationType + ".",
      c.overview || "",
    ];
    (c.sections || []).forEach((s) => {
      parts.push((s.title || "") + ". " + (s.content || ""));
    });
    const utterance = new SpeechSynthesisUtterance(parts.join(" "));
    utterance.rate = 0.95;
    utterance.pitch = 0.9;
    utterance.onend = () => stopSpeech();
    utterance.onerror = () => stopSpeech();
    window.speechSynthesis.speak(utterance);
    state.speechPlaying = true;
    const btn = $("#btn-voice");
    if (btn) {
      btn.textContent = "Stop Reading";
      btn.classList.add("speaking");
    }
  }

  function setViewerTab(tab) {
    if (!state.active) return;
    state.viewerTab = tab || "doc";
    document.querySelectorAll(".viewer-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === state.viewerTab);
    });
    renderDocument(state.active);
  }

  function overviewIsTruncatedBody(creation) {
    const overview = String(creation.overview || "").trim();
    if (!overview) return true;
    const sections = creation.sections || [];
    if (!sections.length) return false;
    const body = String(sections[0].content || "").trim();
    if (!body) return false;
    const clipped = overview.replace(/…\s*$/u, "").replace(/\.\.\.\s*$/, "").trim();
    if (!clipped) return true;
    // Freeform Text creations used to store overview = body[:500] + "…"
    if (body.startsWith(clipped) || clipped === body.slice(0, clipped.length)) {
      return true;
    }
    if (
      (creation.creationType || "") === "Text" &&
      body.length > overview.length &&
      body.indexOf(clipped.slice(0, Math.min(60, clipped.length))) === 0
    ) {
      return true;
    }
    return false;
  }

  /** Hide empty or legacy "Response" section titles from display/export. */
  function shouldHideSectionHeading(secTitle) {
    const t = String(secTitle || "").trim();
    return !t || /^response$/i.test(t);
  }

  function renderDocTab(creation) {
    const meta = creation.meta || {};
    let html = "";

    if (creation.prompt) {
      html +=
        '<p class="doc-prompt"><strong>Prompt:</strong> ' +
        escapeHtml(creation.prompt) +
        "</p>";
    }

    const metaRows = [
      ["Year", meta.releaseYear],
      ["Developer", meta.developer],
      ["Publisher", meta.publisher],
      ["Designer", meta.designer],
      ["Genre", meta.genre],
      ["Media", meta.mediaFormat],
      ["Hardware", meta.systemRequirements],
    ].filter(([, val]) => val);
    if (metaRows.length) {
      html += '<div class="doc-meta">';
      metaRows.forEach(([label, val]) => {
        html +=
          "<div><strong>" +
          escapeHtml(label) +
          ":</strong> " +
          escapeHtml(val) +
          "</div>";
      });
      html += "</div>";
    }

    const overview = String(creation.overview || "").trim();
    if (overview && !overviewIsTruncatedBody(creation)) {
      html += '<p class="doc-overview">' + escapeHtml(overview) + "</p>";
    }

    (creation.sections || []).forEach((sec) => {
      const secTitle = String(sec.title || "").trim();
      html += '<div class="doc-section">';
      if (!shouldHideSectionHeading(secTitle)) {
        html += "<h3>" + escapeHtml(secTitle) + "</h3>";
      }
      html +=
        '<div class="doc-section-body">' +
        escapeHtml(sec.content || "") +
        "</div>";
      if (sec.keyValues && sec.keyValues.length) {
        html += '<table class="kv-table"><tbody>';
        sec.keyValues.forEach((kv) => {
          html +=
            "<tr><td>" +
            escapeHtml(kv.label) +
            "</td><td>" +
            escapeHtml(kv.value) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }
      html += "</div>";
    });

    if (creation.accuracyNote) {
      html +=
        '<p class="doc-export-hide" style="margin-top:16px;font-size:11px;opacity:0.85"><em>' +
        escapeHtml(creation.accuracyNote) +
        "</em></p>";
    }
    return html;
  }

  function renderMediaPlaceholder(creation, modality) {
    return (
      '<div class="media-pane media-pane-loading">' +
      "<p>Loading " +
      escapeHtml(modality) +
      "…</p>" +
      (creation.prompt
        ? '<p class="muted">' + escapeHtml(creation.prompt) + "</p>"
        : "") +
      "</div>"
    );
  }

  async function loadMediaIntoCanvas(creation) {
    const canvas = $("#doc-canvas");
    if (!canvas || !creation) return;
    const a = api();
    const modality = creationModality(creation);
    if (!a) {
      canvas.innerHTML =
        '<p class="muted">Python bridge required to display media.</p>';
      return;
    }
    try {
      const res = await a.get_media_payload(creation);
      if (!res || !res.ok) {
        canvas.innerHTML =
          '<p class="muted">' +
          escapeHtml((res && res.error) || "Media not found") +
          "</p>";
        return;
      }
      if (modality === "video" || res.modality === "video") {
        const src = res.fileUrl || res.dataUrl || "";
        if (!src) {
          canvas.innerHTML =
            '<p class="muted">Video URL missing — restart the app and try again.</p>';
          return;
        }
        canvas.innerHTML =
          '<div class="media-pane">' +
          '<video class="media-video" controls playsinline preload="metadata" src="' +
          escapeHtml(src) +
          '">' +
          "Your WebView could not play this video." +
          "</video>" +
          (creation.prompt
            ? '<p class="media-caption">' + escapeHtml(creation.prompt) + "</p>"
            : "") +
          "</div>";
        const vid = canvas.querySelector("video.media-video");
        if (vid) {
          vid.addEventListener("error", () => {
            const err = vid.error;
            const detail = err
              ? " (code " + err.code + ")"
              : "";
            showToast("Video failed to load" + detail + ". Try Save MP4… or restart the app.");
          });
        }
      } else if (modality === "audio" || res.modality === "audio") {
        const src = res.fileUrl || res.dataUrl || "";
        if (!src) {
          canvas.innerHTML =
            '<p class="muted">Audio URL missing — restart the app and try again.</p>';
          return;
        }
        const lyrics = creationLyrics(creation);
        canvas.innerHTML =
          '<div class="media-pane">' +
          '<audio class="media-audio" controls preload="metadata" src="' +
          escapeHtml(src) +
          '">' +
          "Your WebView could not play this audio." +
          "</audio>" +
          (creation.prompt
            ? '<p class="media-caption">' + escapeHtml(creation.prompt) + "</p>"
            : "") +
          (lyrics
            ? '<pre class="media-lyrics">' + escapeHtml(lyrics) + "</pre>"
            : "") +
          "</div>";
        const audioEl = canvas.querySelector("audio.media-audio");
        if (audioEl) {
          audioEl.addEventListener("error", () => {
            const err = audioEl.error;
            const detail = err ? " (code " + err.code + ")" : "";
            showToast(
              "Audio failed to load" + detail + ". Try Save MP3… or restart the app."
            );
          });
        }
      } else {
        const src = res.fileUrl || res.dataUrl || "";
        if (!src) {
          canvas.innerHTML =
            '<p class="muted">Image URL missing — restart the app and try again.</p>';
          return;
        }
        canvas.innerHTML =
          '<div class="media-pane">' +
          '<img class="media-image" alt="' +
          escapeHtml(creationTitle(creation)) +
          '" src="' +
          escapeHtml(src) +
          '" />' +
          (creation.prompt
            ? '<p class="media-caption">' + escapeHtml(creation.prompt) + "</p>"
            : "") +
          "</div>";
      }
    } catch (err) {
      canvas.innerHTML =
        '<p class="muted">Failed to load media: ' + escapeHtml(String(err)) + "</p>";
    }
  }

  function renderGroundingTab(creation) {
    const sources = creation.groundingSources || [];
    let html =
      '<div class="sources-intro"><strong>Search grounding &amp; cross-check</strong><br/>' +
      "Citations recorded when Google Search grounding was used during generation." +
      "</div>";
    if (!sources.length) {
      html +=
        '<p class="muted">No grounding sources on this document. Enable Google Search grounding in Settings and regenerate, or import a document that includes sources.</p>';
      return html;
    }
    html += '<p><strong>Verified archival web citations:</strong></p><ul class="sources-list">';
    sources.forEach((src, idx) => {
      const title = src.title || src.url || "Source " + (idx + 1);
      const url = src.url || "";
      html += "<li><span>[" + (idx + 1) + "]</span> ";
      if (url) {
        html +=
          '<a href="' +
          escapeHtml(url) +
          '" target="_blank" rel="noreferrer">' +
          escapeHtml(title) +
          "</a>";
        html += '<span class="sources-url">' + escapeHtml(url) + "</span>";
      } else {
        html += escapeHtml(title);
      }
      html += "</li>";
    });
    html += "</ul>";
    return html;
  }

  function getExtractedText(creation) {
    if (!creation || !creation.meta) return "";
    return String(creation.meta.extractedText || "").trim();
  }

  function getExtractedLayout(creation) {
    if (!creation || !creation.meta) return null;
    const layout = creation.meta.extractedLayout;
    return layout && typeof layout === "object" ? layout : null;
  }

  const LAYOUT_BASIS_MARKER = "Layout JSON:";
  const LAYOUT_BASIS_INTRO =
    "The screenshot is attached as a Studio media basis. Use this extracted UI layout " +
    "(element types, labels, pixel boxes, and flags) to recreate the interface — " +
    "for example as HTML/CSS, a desktop app, or another mockup. Address any flags " +
    "(overflow, uneven margins, unlabeled controls).\n\n" +
    LAYOUT_BASIS_MARKER +
    "\n";

  function formatLayoutBasisPrompt(layout, existing) {
    if (!layout || typeof layout !== "object") return String(existing || "").trim();
    const block = LAYOUT_BASIS_INTRO + JSON.stringify(layout, null, 2);
    const prior = String(existing || "").trim();
    if (!prior) return block;
    if (prior.indexOf(LAYOUT_BASIS_MARKER) !== -1) return prior;
    return prior + "\n\n" + block;
  }

  function viewerShouldExportLayout(creation) {
    return state.viewerTab === "layout" && !!getExtractedLayout(creation);
  }

  function renderLayoutTab(creation) {
    const layout = getExtractedLayout(creation);
    const meta = (creation && creation.meta) || {};
    const modality = creationModality(creation);
    let html = '<div class="layout-pane extracted-pane">';
    html += '<div class="extracted-intro"><strong>UI layout</strong>';
    if (meta.layoutExtractedAt || meta.layoutExtractionModel) {
      html +=
        '<span class="extracted-meta">' +
        escapeHtml(
          [
            meta.layoutExtractionProvider,
            meta.layoutExtractionModel,
            meta.layoutSource,
            meta.layoutExtractedAt,
          ]
            .filter(Boolean)
            .join(" · ")
        ) +
        "</span>";
    }
    html += "</div>";
    if (!layout) {
      html +=
        '<p class="muted">' +
        (modality === "video"
          ? "No layout yet. Send this clip to Creation Studio (Use as Basis or Save and Send to Creator), then prompt <strong>extract the layout</strong> to inspect a still frame for windows, buttons, and other chrome."
          : "No layout yet. Send this image to Creation Studio (Use as Basis or Save and Send to Creator), then prompt <strong>extract the layout</strong> to look for UI chrome (windows, buttons, fields) and build coordinate data.") +
        "</p>";
      html += "</div>";
      return html;
    }
    const isUi = layout.isUi !== false;
    const elements = Array.isArray(layout.elements) ? layout.elements : [];
    const flags = Array.isArray(layout.flags) ? layout.flags : [];
    if (!isUi) {
      html +=
        '<p class="muted">Gemini did not treat this as a user-interface screenshot. You can still inspect the JSON below, or try another image.</p>';
    } else {
      html +=
        "<p>" +
        escapeHtml(String(elements.length)) +
        " element" +
        (elements.length === 1 ? "" : "s") +
        (typeof layout.confidence === "number"
          ? " · confidence " + layout.confidence
          : "") +
        "</p>";
    }
    if (modality === "image") {
      html += '<div class="layout-preview-wrap" id="layout-preview-wrap"></div>';
    }
    if (flags.length) {
      html += '<ul class="layout-flags">';
      flags.forEach((flag) => {
        html +=
          "<li><strong>" +
          escapeHtml(flag.code || "flag") +
          "</strong>" +
          (flag.elementId ? " · " + escapeHtml(flag.elementId) : "") +
          (flag.message ? " — " + escapeHtml(flag.message) : "") +
          "</li>";
      });
      html += "</ul>";
    }
    html +=
      '<textarea class="extracted-text layout-json" readonly>' +
      escapeHtml(JSON.stringify(layout, null, 2)) +
      "</textarea>";
    html +=
      '<div class="extracted-actions">' +
      '<button type="button" id="btn-copy-layout">Copy JSON</button>' +
      "</div>";
    html += "</div>";
    return html;
  }

  async function loadLayoutPreview(creation) {
    const wrap = $("#layout-preview-wrap");
    if (!wrap || !creation) return;
    const layout = getExtractedLayout(creation);
    if (!layout || creationModality(creation) !== "image") return;
    const a = api();
    if (!a) return;
    try {
      const res = await a.get_media_payload(creation);
      const src = res && (res.fileUrl || res.dataUrl);
      if (!res || !res.ok || !src) {
        wrap.innerHTML = '<p class="muted">Could not load the image preview.</p>';
        return;
      }
      const width = Number(layout.width) || 0;
      const height = Number(layout.height) || 0;
      const elements = Array.isArray(layout.elements) ? layout.elements : [];
      let overlay = "";
      if (width > 0 && height > 0) {
        elements.forEach((el) => {
          const box = el && el.box;
          if (!box) return;
          const left = (100 * Number(box.x || 0)) / width;
          const top = (100 * Number(box.y || 0)) / height;
          const w = (100 * Number(box.w || 0)) / width;
          const h = (100 * Number(box.h || 0)) / height;
          overlay +=
            '<div class="layout-box" data-type="' +
            escapeHtml(el.type || "other") +
            '" title="' +
            escapeHtml((el.type || "element") + (el.label ? ": " + el.label : "")) +
            '" style="left:' +
            left.toFixed(2) +
            "%;top:" +
            top.toFixed(2) +
            "%;width:" +
            w.toFixed(2) +
            "%;height:" +
            h.toFixed(2) +
            '%"></div>';
        });
      }
      wrap.innerHTML =
        '<img class="layout-preview-img" alt="" src="' +
        escapeHtml(src) +
        '" />' +
        '<div class="layout-overlay">' +
        overlay +
        "</div>";
    } catch (err) {
      wrap.innerHTML =
        '<p class="muted">Preview failed: ' + escapeHtml(String(err)) + "</p>";
    }
  }

  function renderExtractedTab(creation) {
    const text = getExtractedText(creation);
    const meta = (creation && creation.meta) || {};
    const kind = String(meta.extractionKind || "").toLowerCase();
    const label = kind === "transcript" ? "Transcript" : "Extracted text";
    const modality = creationModality(creation);
    let html = '<div class="extracted-pane">';
    html += '<div class="extracted-intro"><strong>' + escapeHtml(label) + "</strong>";
    if (meta.extractedAt || meta.extractionModel) {
      html +=
        '<span class="extracted-meta">' +
        escapeHtml(
          [meta.extractionProvider, meta.extractionModel, meta.extractedAt]
            .filter(Boolean)
            .join(" · ")
        ) +
        "</span>";
    }
    html += "</div>";
    if (!text) {
      html +=
        '<p class="muted">' +
        (modality === "video"
          ? "No transcript yet. Send this clip to Creation Studio (Use as Basis or Save and Send to Creator), then prompt <strong>transcribe</strong> to pull speech (or on-screen text)."
          : "No text extracted yet. Send this image to Creation Studio (Use as Basis or Save and Send to Creator), then prompt <strong>extract the text</strong> to OCR it.") +
        "</p>";
    } else {
      html +=
        '<textarea class="extracted-text" readonly>' +
        escapeHtml(text) +
        "</textarea>";
      html +=
        '<div class="extracted-actions">' +
        '<button type="button" id="btn-copy-extracted">Copy</button>' +
        "</div>";
    }
    html += "</div>";
    return html;
  }

  function viewerEmptyHtml() {
    return (
      '<div class="viewer-empty">' +
      "<p>Open a <strong>text</strong> file, <strong>image</strong>, <strong>video</strong>, " +
      "or <strong>song</strong>. Tabs and tools change to match that type.</p>" +
      '<p class="muted">You can also generate in Creation Studio or pick an item in Archives.</p>' +
      "</div>"
    );
  }

  function showViewerOpenButton() {
    const btn = $("#btn-viewer-open");
    if (btn) btn.hidden = false;
  }

  function prepareEmptyViewer() {
    renderDocument(null);
  }

  async function viewerOpenFile() {
    const a = api();
    if (!a) {
      showToast("Python bridge required to open files.");
      return;
    }
    showViewerOpenButton();
    try {
      const res = await a.open_viewer_file();
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Open failed");
        return;
      }
      if (!res.creation) {
        showToast("Open failed");
        return;
      }
      rememberImportedCreation(res.creation);
      const mod = creationModality(res.creation);
      state.viewerTab = isMediaModality(mod) ? "media" : "doc";
      renderDocument(res.creation);
      const label =
        mod === "image"
          ? "Image"
          : mod === "video"
            ? "Video"
            : mod === "audio"
              ? "Song"
              : "Text";
      showToast(label + " opened in Viewer");
    } catch (err) {
      showToast("Open failed: " + err);
    } finally {
      showViewerOpenButton();
    }
  }

  function renderDocument(creation) {
    state.active = creation;
    const canvas = $("#doc-canvas");
    const groundingTab = $("#tab-grounding");

    if (!creation) {
      stopSpeech();
      stopViewerMedia();
      if (canvas) {
        canvas.classList.remove("doc-canvas-reading");
        canvas.style.background = "";
        canvas.style.color = "";
        canvas.style.fontFamily = "";
        canvas.innerHTML = viewerEmptyHtml();
      }
      if ($("#viewer-title")) $("#viewer-title").textContent = "Viewer";
      if ($("#viewer-status")) $("#viewer-status").textContent = "No file loaded";
      if (groundingTab) groundingTab.textContent = "Sources (0)";
      syncViewerChrome(null);
      renderTaskbar();
      return;
    }

    syncViewerChrome(creation);
    const modality = creationModality(creation);
    const sources = creation.groundingSources || [];
    if (groundingTab) groundingTab.textContent = "Sources (" + sources.length + ")";

    const title = creationTitle(creation);
    if ($("#viewer-title")) $("#viewer-title").textContent = "Viewer — " + title;
    const model = (creation._model && creation._model.repo_id) || "model";
    const created = formatCreatedAt(creation.createdAt);
    if ($("#app-status-text")) $("#app-status-text").textContent = title;
    if ($("#viewer-status")) $("#viewer-status").textContent =
      (creation.creationType || modality) +
      " · " +
      modality +
      " · " +
      model +
      (created ? " · " + created : "");

    const tab = state.viewerTab || (modality === "text" ? "doc" : "media");
    canvas.classList.remove("doc-canvas-reading");

    if (isMediaModality(modality)) {
      canvas.style.background = "#111";
      canvas.style.color = "#eee";
      canvas.style.fontFamily = "var(--ui-font)";
      if (tab === "extracted") {
        canvas.style.background = "#ffffff";
        canvas.style.color = "#000000";
        canvas.style.fontFamily = "var(--ui-font)";
        canvas.innerHTML = renderExtractedTab(creation);
      } else if (tab === "layout") {
        canvas.style.background = "#ffffff";
        canvas.style.color = "#000000";
        canvas.style.fontFamily = "var(--ui-font)";
        canvas.innerHTML = renderLayoutTab(creation);
        loadLayoutPreview(creation);
      } else if (tab === "grounding") {
        canvas.style.background = "#ffffff";
        canvas.style.color = "#000000";
        canvas.style.fontFamily = "var(--ui-font)";
        canvas.innerHTML = renderGroundingTab(creation);
      } else {
        canvas.innerHTML = renderMediaPlaceholder(creation, modality);
        loadMediaIntoCanvas(creation);
      }
    } else if (tab === "grounding") {
      canvas.style.background = "#ffffff";
      canvas.style.color = "#000000";
      canvas.style.fontFamily = "var(--ui-font)";
      canvas.innerHTML = renderGroundingTab(creation);
    } else {
      canvas.classList.add("doc-canvas-reading");
      canvas.style.background = "";
      canvas.style.color = "";
      canvas.style.fontFamily = "var(--ui-font)";
      canvas.innerHTML = renderDocTab(creation);
    }

    openWindow("viewer");
  }

  function exportCreationMetadata(creation) {
    if (!creation) return {};
    const model = Object.assign({}, creation._model || {});
    const meta = {
      id: creation.id || null,
      title: creationTitle(creation),
      creationType: creation.creationType || null,
      modality: creationModality(creation),
      platform: creation.platform || null,
      createdAt: creation.createdAt || null,
      prompt: creation.prompt || "",
      model: model,
      overview: creation.overview || "",
      sections: creation.sections || [],
      meta: creation.meta || {},
      groundingSources: creation.groundingSources || [],
      accuracyNote: creation.accuracyNote || "",
    };
    if (creation.mediaPath) meta.mediaPath = creation.mediaPath;
    if (creation.mimeType) meta.mimeType = creation.mimeType;
    if (creation.theme) meta.theme = creation.theme;
    return meta;
  }

  function exportBaseName(creation) {
    return creationTitle(creation)
      .replace(/[^\w\-]+/g, "_")
      .replace(/_+/g, "_")
      .slice(0, 60) || "creation";
  }

  function buildTextExportBodyHtml(creation, theme) {
    let html = "";
    const overview = String(creation.overview || "").trim();
    if (overview && !overviewIsTruncatedBody(creation)) {
      html +=
        '<p class="doc-overview" style="margin:0 0 12px;white-space:pre-wrap;">' +
        escapeHtml(overview) +
        "</p>";
    }
    (creation.sections || []).forEach((sec) => {
      const secTitle = String(sec.title || "").trim();
      html += '<div class="doc-section" style="margin:0 0 16px;">';
      if (!shouldHideSectionHeading(secTitle)) {
        html +=
          '<h3 style="margin:0 0 8px;color:' +
          escapeHtml(theme.accentColor || "#000080") +
          '">' +
          escapeHtml(secTitle) +
          "</h3>";
      }
      html +=
        '<div class="doc-section-body" style="white-space:pre-wrap;word-wrap:break-word;line-height:1.35;margin:0;">' +
        escapeHtml(sec.content || "") +
        "</div>";
      if (sec.keyValues && sec.keyValues.length) {
        html += '<table class="kv-table" style="margin-top:8px;"><tbody>';
        sec.keyValues.forEach((kv) => {
          html +=
            "<tr><td>" +
            escapeHtml(kv.label) +
            "</td><td>" +
            escapeHtml(kv.value) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }
      html += "</div>";
    });
    return html || '<p style="margin:0;">(empty)</p>';
  }

  async function withOffscreenTextExport(creation, fn) {
    if (!window.htmlToImage) {
      throw new Error("html-to-image is unavailable");
    }
    const theme = resolveTheme(creation);
    const host = document.createElement("div");
    host.setAttribute("data-export-host", "1");
    // Keep in the layout tree (not far off-screen) so WebView paints full height.
    host.style.cssText = [
      "position:fixed",
      "left:0",
      "top:0",
      "width:800px",
      "max-width:800px",
      "padding:24px",
      "box-sizing:border-box",
      "margin:0",
      "overflow:visible",
      "max-height:none",
      "height:auto",
      "opacity:0",
      "pointer-events:none",
      "z-index:2147483646",
      "background:" + (theme.cardBg || "#ffffff"),
      "color:" + (theme.textColor || "#000000"),
      "font-family:" + currentUiFontStack(),
      "font-size:14px",
      "line-height:1.35",
    ].join(";");
    host.innerHTML = buildTextExportBodyHtml(creation, theme);
    document.body.appendChild(host);

    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))
    );

    const fullWidth = Math.max(host.scrollWidth, host.offsetWidth, 800);
    const fullHeight = Math.max(host.scrollHeight, host.offsetHeight, 1);
    host.style.width = fullWidth + "px";
    host.style.height = fullHeight + "px";

    await new Promise((resolve) => requestAnimationFrame(resolve));

    // Stay under typical canvas dimension limits (~16384px) for long documents
    const maxDim = 16000;
    let pixelRatio = 2;
    if (fullWidth * pixelRatio > maxDim || fullHeight * pixelRatio > maxDim) {
      pixelRatio = Math.max(
        1,
        Math.min(maxDim / fullWidth, maxDim / fullHeight)
      );
    }

    const opts = {
      pixelRatio: pixelRatio,
      cacheBust: true,
      backgroundColor: theme.cardBg || "#ffffff",
      width: fullWidth,
      height: fullHeight,
      style: {
        opacity: "1",
        position: "static",
        left: "auto",
        top: "auto",
        transform: "none",
        maxHeight: "none",
        overflow: "visible",
        height: fullHeight + "px",
        width: fullWidth + "px",
      },
    };

    try {
      return await fn(host, opts);
    } finally {
      if (host.parentNode) host.parentNode.removeChild(host);
    }
  }

  function drawLayoutAnnotationCanvas(img, layout) {
    const canvas = document.createElement("canvas");
    const width = Math.max(1, img.naturalWidth || img.width || 1);
    const height = Math.max(1, img.naturalHeight || img.height || 1);
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    const lw = Number(layout && layout.width) || width;
    const lh = Number(layout && layout.height) || height;
    const sx = lw > 0 ? width / lw : 1;
    const sy = lh > 0 ? height / lh : 1;
    const elements = layout && Array.isArray(layout.elements) ? layout.elements : [];
    ctx.lineWidth = Math.max(2, Math.round(Math.min(width, height) / 400));
    elements.forEach((el) => {
      const box = el && el.box;
      if (!box) return;
      const x = Number(box.x || 0) * sx;
      const y = Number(box.y || 0) * sy;
      const w = Number(box.w || 0) * sx;
      const h = Number(box.h || 0) * sy;
      if (w <= 0 || h <= 0) return;
      ctx.fillStyle = "rgba(255, 64, 64, 0.12)";
      ctx.strokeStyle = "#cc2020";
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
    });
    return canvas;
  }

  function layoutExportMetaLines(creation, layout) {
    const meta = (creation && creation.meta) || {};
    const elements = layout && Array.isArray(layout.elements) ? layout.elements : [];
    const flags = layout && Array.isArray(layout.flags) ? layout.flags : [];
    const lines = [];
    lines.push(
      "UI layout" +
        (meta.layoutExtractionModel ? " · " + meta.layoutExtractionModel : "") +
        (meta.layoutSource ? " · " + meta.layoutSource : "")
    );
    lines.push(
      elements.length +
        " element" +
        (elements.length === 1 ? "" : "s") +
        (typeof (layout && layout.confidence) === "number"
          ? " · confidence " + layout.confidence
          : "")
    );
    flags.forEach((flag) => {
      lines.push(
        (flag.code || "flag") +
          (flag.elementId ? " · " + flag.elementId : "") +
          (flag.message ? " — " + flag.message : "")
      );
    });
    return lines;
  }

  async function loadLayoutExportImage(creation) {
    if (creationModality(creation) !== "image") return null;
    const a = api();
    if (!a) return null;
    const payload = await a.get_media_payload(creation);
    const src = payload && payload.ok && (payload.dataUrl || payload.fileUrl);
    if (!src) return null;
    const img = new Image();
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Image load timed out")), 20000);
      img.onload = () => {
        clearTimeout(timer);
        resolve();
      };
      img.onerror = () => {
        clearTimeout(timer);
        reject(new Error("Could not load screenshot for export"));
      };
      img.src = src;
    });
    return img;
  }

  function wrapCanvasLines(ctx, text, maxWidth) {
    const out = [];
    String(text || "")
      .split(/\r?\n/)
      .forEach((line) => {
        if (!line) {
          out.push("");
          return;
        }
        if (ctx.measureText(line).width <= maxWidth) {
          out.push(line);
          return;
        }
        let buf = "";
        for (let i = 0; i < line.length; i++) {
          const next = buf + line[i];
          if (buf && ctx.measureText(next).width > maxWidth) {
            out.push(buf);
            buf = line[i];
          } else {
            buf = next;
          }
        }
        if (buf) out.push(buf);
      });
    return out;
  }

  function composeLayoutDocumentCanvas(annoCanvas, creation, layout) {
    const pad = 24;
    const maxDim = 16000;
    const width = Math.max(960, annoCanvas ? annoCanvas.width : 0);
    const header = layoutExportMetaLines(creation, layout).join("\n");
    const json = JSON.stringify(layout, null, 2);
    const body = header + "\n\n" + json;
    const imgW = annoCanvas ? annoCanvas.width : 0;
    const imgH = annoCanvas ? annoCanvas.height : 0;
    const textWidth = width - pad * 2;
    const titleH = 36;
    const sectionH = 28;
    const gap = 16;
    let fontPx = 13;
    let lineH = 18;
    const measure = document.createElement("canvas").getContext("2d");
    function layoutText(size) {
      measure.font = size + 'px ui-monospace, Consolas, "Courier New", monospace';
      return wrapCanvasLines(measure, body, textWidth);
    }
    let bodyLines = layoutText(fontPx);
    let height =
      pad +
      titleH +
      (annoCanvas ? imgH + gap : 0) +
      sectionH +
      bodyLines.length * lineH +
      pad;
    while (height > maxDim && fontPx > 9) {
      fontPx -= 1;
      lineH = Math.max(11, fontPx + 3);
      bodyLines = layoutText(fontPx);
      height =
        pad +
        titleH +
        (annoCanvas ? imgH + gap : 0) +
        sectionH +
        bodyLines.length * lineH +
        pad;
    }
    if (height > maxDim) {
      const fixed =
        pad + titleH + (annoCanvas ? imgH + gap : 0) + sectionH + pad + lineH;
      const maxLines = Math.max(12, Math.floor((maxDim - fixed) / lineH));
      if (bodyLines.length > maxLines) {
        bodyLines = bodyLines.slice(0, maxLines);
        bodyLines[maxLines - 1] =
          "… truncated — use Save Layout PDF for the rest of the JSON.";
      }
      height =
        pad +
        titleH +
        (annoCanvas ? imgH + gap : 0) +
        sectionH +
        bodyLines.length * lineH +
        pad;
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = Math.max(1, Math.min(maxDim, height));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000000";
    ctx.textBaseline = "top";
    ctx.font = "bold 20px Helvetica, Arial, sans-serif";
    ctx.fillText("UI layout", pad, pad);
    let y = pad + titleH;
    if (annoCanvas) {
      const x = Math.round((width - imgW) / 2);
      ctx.drawImage(annoCanvas, x, y, imgW, imgH);
      y += imgH + gap;
    }
    ctx.font = "bold 16px Helvetica, Arial, sans-serif";
    ctx.fillText("Layout flags and JSON", pad, y);
    y += sectionH;
    ctx.font = fontPx + 'px ui-monospace, Consolas, "Courier New", monospace';
    bodyLines.forEach((line) => {
      ctx.fillText(line, pad, y);
      y += lineH;
    });
    return canvas;
  }

  function getJsPdfCtor() {
    const ns = window.jspdf || window.jsPDF;
    return ns && (ns.jsPDF || ns);
  }

  function addPdfImagePage(pdf, dataUrl, pixelW, pixelH) {
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const margin = 12;
    const maxW = pageW - margin * 2;
    const maxH = pageH - margin * 2;
    const scale = Math.min(maxW / pixelW, maxH / pixelH);
    const w = pixelW * scale;
    const h = pixelH * scale;
    const x = (pageW - w) / 2;
    const y = margin;
    pdf.setFillColor(255, 255, 255);
    pdf.rect(0, 0, pageW, pageH, "F");
    pdf.addImage(dataUrl, "PNG", x, y, w, h);
  }

  function addPdfTextPages(pdf, title, body) {
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const margin = 12;
    const lineH = 4.2;
    pdf.addPage();
    pdf.setFillColor(255, 255, 255);
    pdf.rect(0, 0, pageW, pageH, "F");
    pdf.setTextColor(0, 0, 0);
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(14);
    let y = margin + 4;
    pdf.text(title, margin, y);
    y += 8;
    pdf.setFont("courier", "normal");
    pdf.setFontSize(8);
    const lines = pdf.splitTextToSize(String(body || ""), pageW - margin * 2);
    lines.forEach((line) => {
      if (y + lineH > pageH - margin) {
        pdf.addPage();
        pdf.setFillColor(255, 255, 255);
        pdf.rect(0, 0, pageW, pageH, "F");
        pdf.setTextColor(0, 0, 0);
        pdf.setFont("courier", "normal");
        pdf.setFontSize(8);
        y = margin;
      }
      pdf.text(line, margin, y);
      y += lineH;
    });
  }

  async function exportLayoutDocument(format) {
    const creation = state.active;
    const layout = getExtractedLayout(creation);
    const a = api();
    if (!a || !creation || !layout) return;
    const JsPDF = getJsPdfCtor();
    if (format === "pdf" && !JsPDF) {
      showToast("jsPDF is unavailable");
      return;
    }
    showToast(format === "pdf" ? "Building layout PDF…" : "Capturing layout PNG…");
    try {
      const img = await loadLayoutExportImage(creation);
      const anno = img ? drawLayoutAnnotationCanvas(img, layout) : null;
      const base = exportBaseName(creation) + "_layout";
      if (format === "png") {
        const doc = composeLayoutDocumentCanvas(anno, creation, layout);
        const pngDataUrl = doc.toDataURL("image/png");
        const res = await a.save_binary_file_dialog(base + ".png", pngDataUrl);
        if (res.ok) {
          showToast("Saved layout PNG");
        } else if (!res.cancelled) {
          showToast(res.error || "PNG export failed");
        }
        return;
      }
      const landscape = !!(anno && anno.width > anno.height);
      const pdf = new JsPDF({
        orientation: landscape ? "landscape" : "portrait",
        unit: "mm",
        format: "a4",
      });
      if (anno) {
        addPdfImagePage(pdf, anno.toDataURL("image/png"), anno.width, anno.height);
      } else {
        pdf.setFillColor(255, 255, 255);
        pdf.rect(0, 0, pdf.internal.pageSize.getWidth(), pdf.internal.pageSize.getHeight(), "F");
        pdf.setTextColor(0, 0, 0);
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(14);
        pdf.text("UI layout", 12, 16);
      }
      const header = layoutExportMetaLines(creation, layout).join("\n");
      const json = JSON.stringify(layout, null, 2);
      addPdfTextPages(pdf, "Layout flags and JSON", header + "\n\n" + json);
      const dataUri = pdf.output("datauristring");
      const res = await a.save_binary_file_dialog(base + ".pdf", dataUri);
      if (res.ok) {
        showToast("Saved layout PDF");
      } else if (!res.cancelled) {
        showToast(res.error || "PDF export failed");
      }
    } catch (err) {
      console.error(err);
      showToast("Export failed: " + (err && err.message ? err.message : err));
    }
  }

  function buildLayoutOverlayHtml(layout) {
    const width = Number(layout && layout.width) || 0;
    const height = Number(layout && layout.height) || 0;
    const elements = layout && Array.isArray(layout.elements) ? layout.elements : [];
    if (width <= 0 || height <= 0) return "";
    let overlay = "";
    elements.forEach((el) => {
      const box = el && el.box;
      if (!box) return;
      const left = (100 * Number(box.x || 0)) / width;
      const top = (100 * Number(box.y || 0)) / height;
      const w = (100 * Number(box.w || 0)) / width;
      const h = (100 * Number(box.h || 0)) / height;
      overlay +=
        '<div class="layout-box" data-type="' +
        escapeHtml(el.type || "other") +
        '" style="left:' +
        left.toFixed(2) +
        "%;top:" +
        top.toFixed(2) +
        "%;width:" +
        w.toFixed(2) +
        "%;height:" +
        h.toFixed(2) +
        '%"></div>';
    });
    return overlay;
  }

  async function exportDocumentImage(format) {
    if (!state.active) return;
    const a = api();
    if (!a) return;
    const modality = creationModality(state.active);

    if (viewerShouldExportLayout(state.active)) {
      await exportLayoutDocument(format);
      return;
    }

    // Native image → PNG: copy original bytes; PDF: embed image full-bleed
    if (modality === "image") {
      try {
        const payload = await a.get_media_payload(state.active);
        if (!payload || !payload.ok || !payload.dataUrl) {
          showToast((payload && payload.error) || "Image not found");
          return;
        }
        const base = exportBaseName(state.active);
        if (format === "png") {
          const res = await a.save_binary_file_dialog(base + ".png", payload.dataUrl);
          if (res.ok) {
            showToast("Saved PNG");
          } else if (!res.cancelled) {
            showToast(res.error || "PNG export failed");
          }
          return;
        }
        showToast("Building PDF…");
        const jspdfNS = window.jspdf || window.jsPDF;
        const JsPDF = jspdfNS && (jspdfNS.jsPDF || jspdfNS);
        if (!JsPDF) throw new Error("jsPDF is unavailable");
        const img = new Image();
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
          img.src = payload.dataUrl;
        });
        const pdf = new JsPDF({
          orientation: img.width > img.height ? "landscape" : "portrait",
          unit: "px",
          format: [img.width, img.height],
        });
        const fmt = (payload.mimeType || "").includes("jpeg") ? "JPEG" : "PNG";
        pdf.addImage(payload.dataUrl, fmt, 0, 0, img.width, img.height);
        const dataUri = pdf.output("datauristring");
        const res = await a.save_binary_file_dialog(base + ".pdf", dataUri);
        if (res.ok) {
          showToast("Saved PDF");
        } else if (!res.cancelled) {
          showToast(res.error || "PDF export failed");
        }
      } catch (err) {
        console.error(err);
        showToast("Export failed: " + (err && err.message ? err.message : err));
      }
      return;
    }

    // Text: render full body offscreen so parent window overflow cannot clip it
    showToast(format === "pdf" ? "Building PDF…" : "Capturing PNG…");
    try {
      const base = exportBaseName(state.active);
      if (format === "png") {
        const pngDataUrl = await withOffscreenTextExport(state.active, (el, opts) =>
          window.htmlToImage.toPng(el, opts)
        );
        const res = await a.save_binary_file_dialog(base + ".png", pngDataUrl);
        if (res.ok) {
          showToast("Saved PNG");
        } else if (!res.cancelled) {
          showToast(res.error || "PNG export failed");
        }
        return;
      }

      const jspdfNS = window.jspdf || window.jsPDF;
      const JsPDF = jspdfNS && (jspdfNS.jsPDF || jspdfNS);
      if (!JsPDF) throw new Error("jsPDF is unavailable");

      const canvas = await withOffscreenTextExport(state.active, (el, opts) =>
        window.htmlToImage.toCanvas(el, opts)
      );
      const imgData = canvas.toDataURL("image/png");
      const pdf = new JsPDF({
        orientation: canvas.width > canvas.height ? "landscape" : "portrait",
        unit: "px",
        format: [canvas.width / 2, canvas.height / 2],
      });
      pdf.addImage(imgData, "PNG", 0, 0, canvas.width / 2, canvas.height / 2);
      const dataUri = pdf.output("datauristring");
      const res = await a.save_binary_file_dialog(base + ".pdf", dataUri);
      if (res.ok) {
        showToast("Saved PDF");
      } else if (!res.cancelled) {
        showToast(res.error || "PDF export failed");
      }
    } catch (err) {
      console.error(err);
      showToast("Export failed: " + (err && err.message ? err.message : err));
    }
  }

  function creationModalityLabel(creation) {
    const m = creationModality(creation);
    if (m === "image") return "Image";
    if (m === "video") return "Video";
    if (m === "audio") return "Audio";
    return "Text";
  }

  function archiveSortValue(creation, key) {
    if (key === "name") return creationTitle(creation).toLowerCase();
    if (key === "type") return creationModalityLabel(creation).toLowerCase();
    if (key === "created") {
      const t = Date.parse(creation && creation.createdAt);
      return Number.isFinite(t) ? t : 0;
    }
    return "";
  }

  function compareArchiveRows(a, b, key, dir) {
    const av = archiveSortValue(a, key);
    const bv = archiveSortValue(b, key);
    let cmp = 0;
    if (typeof av === "number" && typeof bv === "number") {
      cmp = av - bv;
    } else {
      cmp = String(av).localeCompare(String(bv), undefined, {
        sensitivity: "base",
        numeric: true,
      });
    }
    if (cmp === 0) {
      // Stable-ish secondary: newest id / created
      const at = archiveSortValue(a, "created");
      const bt = archiveSortValue(b, "created");
      cmp = bt - at;
    }
    return dir === "desc" ? -cmp : cmp;
  }

  function syncArchiveSortHeaders() {
    const sort = state.archiveSort || { key: "created", dir: "desc" };
    document.querySelectorAll(".archive-table thead th[aria-sort]").forEach((th) => {
      const btn = th.querySelector(".arch-sort-btn");
      const key = btn && btn.getAttribute("data-sort");
      if (!key) return;
      const label =
        key === "name" ? "Name" : key === "type" ? "Type" : "Created";
      if (sort.key === key) {
        th.setAttribute("aria-sort", sort.dir === "asc" ? "ascending" : "descending");
        btn.textContent = label + (sort.dir === "asc" ? " ▲" : " ▼");
        btn.setAttribute("aria-pressed", "true");
      } else {
        th.setAttribute("aria-sort", "none");
        btn.textContent = label;
        btn.setAttribute("aria-pressed", "false");
      }
    });
  }

  function setArchiveSort(key) {
    if (!key) return;
    const cur = state.archiveSort || { key: "created", dir: "desc" };
    if (cur.key === key) {
      state.archiveSort = { key: key, dir: cur.dir === "asc" ? "desc" : "asc" };
    } else {
      // Dates default newest-first; text columns start A→Z
      state.archiveSort = {
        key: key,
        dir: key === "created" ? "desc" : "asc",
      };
    }
    renderArchives();
  }

  function renderArchives() {
    const q = ($("#archive-search").value || "").toLowerCase();
    const list = $("#archive-list");
    if (!list) return;
    list.innerHTML = "";
    const sort = state.archiveSort || { key: "created", dir: "desc" };
    syncArchiveSortHeaders();
    state.creations
      .filter((c) => {
        if (!q) return true;
        const typeLabel = creationModalityLabel(c).toLowerCase();
        return (
          (c.game || "").toLowerCase().includes(q) ||
          (c.title || "").toLowerCase().includes(q) ||
          (c.prompt || "").toLowerCase().includes(q) ||
          (c.creationType || "").toLowerCase().includes(q) ||
          (c.platform || "").toLowerCase().includes(q) ||
          typeLabel.includes(q) ||
          creationModality(c).includes(q)
        );
      })
      .slice()
      .sort((a, b) => compareArchiveRows(a, b, sort.key, sort.dir))
      .forEach((c) => {
        const tr = document.createElement("tr");
        const mod = creationModality(c);
        const isMedia = mod === "image" || mod === "video";

        const tdName = document.createElement("td");
        tdName.className = "arch-col-name";
        const openBtn = document.createElement("button");
        openBtn.type = "button";
        openBtn.className = "arch-open";
        openBtn.textContent = creationTitle(c);
        openBtn.title = "Open in Viewer";
        openBtn.addEventListener("click", () => {
          renderDocument(c);
        });
        tdName.appendChild(openBtn);

        const tdType = document.createElement("td");
        tdType.className = "arch-col-type";
        tdType.textContent = creationModalityLabel(c);

        const tdDate = document.createElement("td");
        tdDate.className = "arch-col-date";
        tdDate.textContent = c.createdAt ? formatCreatedAt(c.createdAt) : "—";

        const tdActions = document.createElement("td");
        tdActions.className = "arch-col-actions";
        const basis = document.createElement("button");
        basis.type = "button";
        basis.textContent = isMedia ? "Edit…" : "Basis";
        basis.title = isMedia
          ? "Open a copy in the " + mod + " editor"
          : mod === "audio"
            ? "Use as basis for a new song"
            : "Use as basis for a new text creation";
        basis.addEventListener("click", () => {
          useCreationAsBasis(c);
        });
        const del = document.createElement("button");
        del.type = "button";
        del.textContent = "Del";
        del.addEventListener("click", async () => {
          const a = api();
          if (!a) return;
          state.creations = await a.delete_creation(c.id);
          if (state.active && state.active.id === c.id) {
            renderDocument(null);
          }
          renderArchives();
        });
        tdActions.appendChild(basis);
        tdActions.appendChild(del);

        tr.appendChild(tdName);
        tr.appendChild(tdType);
        tr.appendChild(tdDate);
        tr.appendChild(tdActions);
        tr.addEventListener("dblclick", (e) => {
          if (e.target.closest(".arch-col-actions")) return;
          e.preventDefault();
          renderDocument(c);
        });
        list.appendChild(tr);
      });
  }

  function syncGeminiTwoPassAvailability() {
    const search = $("#gemini-search");
    const twoPass = $("#gemini-two-pass");
    const hint = $("#gemini-two-pass-hint");
    if (!twoPass) return;
    const searchOn = !search || search.checked;
    twoPass.disabled = !searchOn;
    if (!searchOn) {
      twoPass.checked = false;
    }
    if (hint) {
      hint.classList.toggle("muted", !searchOn);
    }
  }

  function syncGeminiToolsAvailability() {
    // Tools may be combined with Search; only refresh Studio strip + two-pass (search-gated).
    syncGeminiTwoPassAvailability();
    syncGeminiSearchEnrichmentAvailability();
    syncStudioToolsPanel();
  }

  function syncGeminiSearchEnrichmentAvailability() {
    const search = $("#gemini-search");
    const ocr = $("#gemini-ocr-search-images");
    const ocrHint = $("#gemini-ocr-search-images-hint");
    const yt = $("#gemini-youtube-search-captions");
    const ytHint = $("#gemini-youtube-search-captions-hint");
    const searchOn = !search || search.checked;
    [ocr, yt].forEach((el) => {
      if (el) el.disabled = !searchOn;
    });
    [ocrHint, ytHint].forEach((hint) => {
      if (hint) hint.classList.toggle("muted", !searchOn);
    });
  }

  function modelOptionLabel(m, maxLen) {
    // Always show the model id in the picker so labels match config / save /
    // restart (friendly display names are only in the option title tooltip).
    maxLen = maxLen == null ? 44 : maxLen;
    let text = String((m && m.repo_id) || (m && m.label) || "").trim() || "model";
    if (text.length > maxLen) text = text.slice(0, maxLen - 1) + "…";
    return text;
  }

  function modelOptionTitle(m) {
    const parts = [
      (m && m.label) || "",
      (m && m.notes) || "",
      (m && m.repo_id) || "",
    ]
      .map((s) => String(s || "").trim())
      .filter(Boolean);
    return parts.filter((p, i) => p !== parts[i - 1]).join("\n");
  }

  function appendModelOption(sel, m, modality) {
    const opt = document.createElement("option");
    opt.value = m.repo_id;
    opt.textContent = modelOptionLabel(m);
    opt.title = modelOptionTitle(m);
    if (modality) opt.dataset.modality = modality;
    sel.appendChild(opt);
    return opt;
  }

  /** Fill a Gemini modality picker with only compatible models. */
  function fillGeminiModalitySelect(sel, selected, suggestions, modality) {
    if (!sel) return;
    const want = (modality || "text").toLowerCase();
    const defaults = {
      text: "gemini-2.5-flash",
      image: "gemini-2.5-flash-image",
      video: "veo-2.0-generate-001",
      audio: "lyria-3-clip-preview",
    };
    const retired = new Set(
      (state.retiredGeminiModels || []).map((id) => String(id || "").toLowerCase())
    );
    const filtered = (suggestions || []).filter(
      (m) => (m.modality || "text").toLowerCase() === want
    );
    sel.innerHTML = "";
    filtered.forEach((m) => appendModelOption(sel, m, want));
    let pick = selected || defaults[want] || "";
    const pickKey = String(pick || "").toLowerCase();
    if (pick && retired.has(pickKey)) {
      // Learned/built-in retired ids must not stick in the picker
      pick = defaults[want] || (sel.options[0] && sel.options[0].value) || "";
    } else if (pick && ![...sel.options].some((o) => o.value === pick)) {
      // Keep a valid saved config choice even when the short suggested list
      // doesn't include it yet (e.g. veo-3.1-fast before live Refresh).
      appendModelOption(
        sel,
        { repo_id: pick, label: pick, notes: "saved" },
        want
      );
    }
    if (!pick && sel.options.length) pick = sel.options[0].value;
    if (pick) sel.value = pick;
  }

  function creationModality(creation) {
    if (!creation) return "text";
    const m = String(creation.modality || "").toLowerCase();
    if (m === "image" || m === "video" || m === "text" || m === "audio") return m;
    if (creation.mediaPath) {
      const mime = String(creation.mimeType || "").toLowerCase();
      if (mime.startsWith("video/")) return "video";
      if (mime.startsWith("audio/")) return "audio";
      return "image";
    }
    return "text";
  }

  function creationLyrics(creation) {
    const sections = (creation && creation.sections) || [];
    const parts = [];
    sections.forEach((sec) => {
      const content = String((sec && sec.content) || "").trim();
      if (content) parts.push(content);
    });
    return parts.join("\n\n").trim();
  }

  function isMediaModality(modality) {
    return modality === "image" || modality === "video" || modality === "audio";
  }

  function creationTitle(creation) {
    if (!creation) return "Untitled";
    return (
      creation.title ||
      creation.game ||
      (creation.prompt && String(creation.prompt).split("\n")[0].trim()) ||
      "Untitled"
    );
  }

  function syncViewerChrome(creation) {
    showViewerOpenButton();
    const modality = creation ? creationModality(creation) : "";
    const isMedia = isMediaModality(modality);
    const extracted = getExtractedText(creation);
    const lyrics = modality === "audio" ? creationLyrics(creation) : "";

    const tabs = $("#viewer-tabs");
    const tabDoc = $("#tab-doc");
    const tabMedia = $("#tab-media");
    const tabExtracted = $("#tab-extracted");
    const tabLayout = $("#tab-layout");
    const tabGrounding = $("#tab-grounding");
    if (tabs) tabs.hidden = !creation;
    if (tabDoc) {
      tabDoc.hidden = !creation || isMedia;
      tabDoc.textContent = "Document";
    }
    if (tabMedia) {
      tabMedia.hidden = !isMedia;
      tabMedia.textContent =
        modality === "video" ? "Video" : modality === "audio" ? "Audio" : "Image";
    }
    if (tabExtracted) {
      tabExtracted.hidden = !isMedia || modality === "audio";
      const kind =
        creation &&
        creation.meta &&
        String(creation.meta.extractionKind || "").toLowerCase();
      tabExtracted.textContent =
        kind === "transcript" ? "Transcript" : "Extracted";
    }
    if (tabLayout) tabLayout.hidden = !isMedia || modality === "audio";
    if (tabGrounding) {
      const sources = (creation && creation.groundingSources) || [];
      tabGrounding.hidden = !creation || (isMedia && !sources.length);
    }

    const showTxt = modality === "text" || (isMedia && !!extracted) || !!lyrics;
    const hasLayout = !!getExtractedLayout(creation);
    const exportLayout = state.viewerTab === "layout" && hasLayout;
    const showPng = modality === "text" || modality === "image" || exportLayout;
    const showPdf = modality === "text" || modality === "image" || exportLayout;
    const showMp4 = modality === "video" || modality === "audio";
    const showVoice = modality === "text";
    const showEditImage = modality === "image";
    const showEditVideo = modality === "video";
    const showMetadata = !!creation;
    const showBasis = !!creation;

    if ($("#btn-export-txt")) {
      $("#btn-export-txt").hidden = !showTxt;
      $("#btn-export-txt").textContent =
        modality === "audio" && lyrics
          ? "Export Lyrics"
          : isMedia && extracted
            ? "Export Extracted TXT"
            : "Export TXT";
    }
    if ($("#btn-export-png")) {
      $("#btn-export-png").hidden = !showPng;
      $("#btn-export-png").textContent = exportLayout
        ? "Save Layout PNG"
        : modality === "image"
          ? "Save PNG"
          : "Export PNG";
    }
    if ($("#btn-export-pdf")) {
      $("#btn-export-pdf").hidden = !showPdf;
      $("#btn-export-pdf").textContent = exportLayout
        ? "Save Layout PDF"
        : modality === "image"
          ? "Save PDF"
          : "Export PDF";
    }
    if ($("#btn-export-media")) {
      // Native media file — images use Save PNG / Save PDF
      $("#btn-export-media").hidden = !showMp4;
      $("#btn-export-media").textContent =
        modality === "audio" ? "Save MP3…" : "Save MP4…";
    }
    if ($("#btn-edit-image")) $("#btn-edit-image").hidden = !showEditImage;
    if ($("#btn-edit-video")) $("#btn-edit-video").hidden = !showEditVideo;
    if ($("#btn-viewer-send-creator")) {
      $("#btn-viewer-send-creator").hidden = !(showEditImage || showEditVideo);
    }
    if ($("#btn-voice")) $("#btn-voice").hidden = !showVoice;
    if ($("#btn-use-basis")) $("#btn-use-basis").hidden = !showBasis;
    if ($("#btn-export-json")) {
      $("#btn-export-json").hidden = !showMetadata;
      $("#btn-export-json").textContent = "Export Metadata";
    }

    if (isMedia && (state.viewerTab === "doc" || state.viewerTab === "print" || state.viewerTab === "ascii")) {
      state.viewerTab = "media";
    }
    if (
      isMedia &&
      modality === "audio" &&
      (state.viewerTab === "extracted" || state.viewerTab === "layout")
    ) {
      state.viewerTab = "media";
    }
    if (
      !isMedia &&
      creation &&
      (state.viewerTab === "media" ||
        state.viewerTab === "extracted" ||
        state.viewerTab === "layout" ||
        state.viewerTab === "print" ||
        state.viewerTab === "ascii")
    ) {
      state.viewerTab = "doc";
    }
    if (!creation) {
      state.viewerTab = "";
    } else if (!state.viewerTab) {
      state.viewerTab = isMedia ? "media" : "doc";
    }
    document.querySelectorAll(".viewer-tab").forEach((btn) => {
      btn.classList.toggle(
        "active",
        !!creation && btn.getAttribute("data-tab") === state.viewerTab
      );
    });
  }

  function fillMediaFolderControls(paths) {
    const input = $("#media-folder-path");
    const hint = $("#media-folder-hint");
    const cfg = paths || {};
    const stored = (cfg.media || "media").trim() || "media";
    if (input) input.value = stored;
    if (!hint) return;
    const resolved = (cfg.media_resolved || "").trim();
    hint.textContent =
      "Only image, video, and song files go here (PNG, MP4, MP3). " +
      "Text, lyrics, prompts, and metadata stay in archives.json — you do not need to Export to keep them. " +
      "Default is the media folder next to the app. After Save you can move existing media files into the new folder; " +
      "declining leaves them where they are. Archives still opens items left in the old project media folder." +
      (resolved ? " Currently: " + resolved + "." : "");
  }

  function fillControlPanel(boot) {
    if (boot && boot.config) state.config = boot.config;
    if (boot && Array.isArray(boot.geminiTools)) {
      state.geminiToolsCatalog = boot.geminiTools.slice();
    }
    if (boot && Array.isArray(boot.retiredGeminiModels)) {
      state.retiredGeminiModels = boot.retiredGeminiModels.slice();
    }
    const gemini = (boot.config && boot.config.gemini) || {};
    const ui = (boot.config && boot.config.ui) || {};
    const promptCfg = (boot.config && boot.config.prompt) || {};

    if ($("#gemini-temp")) {
      $("#gemini-temp").value = gemini.temperature ?? 0;
    }
    if ($("#gemini-search")) {
      $("#gemini-search").checked = gemini.google_search !== false;
    }
    if ($("#gemini-two-pass")) {
      $("#gemini-two-pass").checked = gemini.two_pass_verify !== false;
    }
    if ($("#gemini-use-tools")) {
      $("#gemini-use-tools").checked = !!gemini.use_tools;
    }
    applyStudioEnableToolsFromConfig();
    if ($("#gemini-ocr-search-images")) {
      $("#gemini-ocr-search-images").checked = gemini.ocr_search_images !== false;
    }
    if ($("#gemini-youtube-search-captions")) {
      $("#gemini-youtube-search-captions").checked =
        gemini.youtube_search_captions !== false;
    }
    syncGeminiToolsAvailability();

    const workspaceCfg =
      (boot.config && (boot.config.google_workspace || boot.config.gmail)) || {};
    if ($("#google-workspace-credentials-path")) {
      $("#google-workspace-credentials-path").value =
        workspaceCfg.credentials_path || "";
    }
    void refreshGoogleWorkspaceAuthStatus();

    fillMediaFolderControls(boot.config && boot.config.paths);

    const suggested = boot.suggestedGeminiModels || [];
    fillGeminiModalitySelect(
      $("#gemini-text-model"),
      gemini.text_model || "gemini-2.5-flash",
      suggested,
      "text"
    );
    fillGeminiModalitySelect(
      $("#gemini-image-model"),
      gemini.image_model || "gemini-2.5-flash-image",
      suggested,
      "image"
    );
    fillGeminiModalitySelect(
      $("#gemini-video-model"),
      gemini.video_model || "veo-2.0-generate-001",
      suggested,
      "video"
    );
    fillGeminiModalitySelect(
      $("#gemini-audio-model"),
      gemini.audio_model || "lyria-3-clip-preview",
      suggested,
      "audio"
    );

    updateApiKeyIndicators();

    if ($("#system-extra")) $("#system-extra").value = promptCfg.extra_instructions || "";
    $("#opt-sound").checked = ui.sound_enabled !== false;
    state.soundEnabled = $("#opt-sound").checked;
    applySoundVolume(ui.sound_volume != null ? ui.sound_volume : 100);
    if ($("#opt-sound-volume")) {
      $("#opt-sound-volume").disabled = !state.soundEnabled;
    }
    state.crtEnabled = false;
    applyUiScale(1);

    fillAppThemeSelect();
    fillUiFontSelect();
    fillUiFontSizeSelect();
    const custom = ui.custom_theme || {};
    state.customTheme = {
      desktopColor: normalizeHexColor(custom.desktop_color, "#ffffff"),
      windowColor: normalizeHexColor(custom.window_color, "#ffffff"),
      titleColor: normalizeHexColor(custom.title_color, "#000000"),
      textColor: normalizeHexColor(custom.text_color, "#000000"),
      font: resolveCustomFontKey(custom.font || "sans"),
    };
    state.uiFont = resolveUiFontKey(
      ui.ui_font || (custom.font === "serif" || custom.font === "mono" ? custom.font : null) || "inter"
    );
    applyUiFont(state.uiFont);
    applyUiFontSize(ui.ui_font_size != null ? ui.ui_font_size : UI_FONT_SIZE_DEFAULT);
    state.appTheme = resolveAppThemeKey(ui.app_theme || "light");
    if ($("#app-theme")) {
      $("#app-theme").value = state.appTheme;
    }
    applyAppTheme(state.appTheme);

    state.studioBasisWidth = parseStudioBasisWidth(ui.studio_basis_width);
    const basisPanel = $("#studio-basis-panel");
    if (basisPanel && !basisPanel.hidden) {
      applyStudioBasisWidth(state.studioBasisWidth);
    }

    updateStudioBackendLabel(boot);
    syncStudioToolsPanel();
  }

  function updateStudioBackendLabel(boot) {
    const modelField = $("#studio-model-field");
    if (!modelField) return;
    const provider =
      (boot && boot.config && boot.config.backend && boot.config.backend.provider) ||
      ($("#backend-provider") && $("#backend-provider").value) ||
      "gemini";
    if (provider === "huggingface") {
      const h =
        (boot && boot.config && boot.config.huggingface) ||
        (state.config && state.config.huggingface) ||
        {};
      const textM =
        h.text_model ||
        h.repo_id ||
        ($("#hf-text-model") && $("#hf-text-model").value) ||
        "local HF";
      const imageM =
        h.image_model ||
        ($("#hf-image-model") && $("#hf-image-model").value) ||
        "";
      const videoM =
        h.video_model ||
        ($("#hf-video-model") && $("#hf-video-model").value) ||
        "";
      modelField.textContent =
        "Backend: Hugging Face · text " +
        textM +
        " · image " +
        imageM +
        " · video " +
        videoM;
    } else if (provider === "openrouter") {
      const o =
        (boot && boot.config && boot.config.openrouter) ||
        (state.config && state.config.openrouter) ||
        {};
      const textM =
        o.text_model ||
        ($("#openrouter-text-model") && $("#openrouter-text-model").value) ||
        "google/gemini-2.5-flash";
      const imageM =
        o.image_model ||
        ($("#openrouter-image-model") && $("#openrouter-image-model").value) ||
        "google/gemini-2.5-flash-image";
      const videoM =
        o.video_model ||
        ($("#openrouter-video-model") && $("#openrouter-video-model").value) ||
        "google/veo-2.0";
      modelField.textContent =
        "Backend: OpenRouter · text " +
        textM +
        " · image " +
        imageM +
        " · video " +
        videoM;
    } else {
      const g =
        (boot && boot.config && boot.config.gemini) ||
        (state.config && state.config.gemini) ||
        {};
      const textM =
        g.text_model ||
        ($("#gemini-text-model") && $("#gemini-text-model").value) ||
        "gemini-2.5-flash";
      const imageM =
        g.image_model ||
        ($("#gemini-image-model") && $("#gemini-image-model").value) ||
        "gemini-2.5-flash-image";
      const videoM =
        g.video_model ||
        ($("#gemini-video-model") && $("#gemini-video-model").value) ||
        "veo-2.0-generate-001";
      const audioM =
        g.audio_model ||
        ($("#gemini-audio-model") && $("#gemini-audio-model").value) ||
        "lyria-3-clip-preview";
      modelField.textContent =
        "Backend: Gemini · text " +
        textM +
        " · image " +
        imageM +
        " · video " +
        videoM +
        " · audio " +
        audioM;
    }
  }

  function savedBackendProvider() {
    return (
      (state.config &&
        state.config.backend &&
        state.config.backend.provider) ||
      "gemini"
    );
  }

  function providerLabel(provider) {
    if (provider === "openrouter") return "OpenRouter";
    if (provider === "huggingface") return "Hugging Face";
    return "Gemini";
  }

  function geminiApiKeyInputs() {
    return [$("#gemini-key"), $("#gemini-key-google")].filter(Boolean);
  }

  function typedGeminiApiKey() {
    for (const el of geminiApiKeyInputs()) {
      const value = el.value.trim();
      if (value) return value;
    }
    return "";
  }

  function setGeminiApiKeyInputs(value) {
    geminiApiKeyInputs().forEach((el) => {
      el.value = value;
    });
  }

  function syncGeminiApiKeyInputs(source) {
    const value = source ? source.value : typedGeminiApiKey();
    geminiApiKeyInputs().forEach((el) => {
      if (el !== source) el.value = value;
    });
  }

  function clearGeminiApiKeyInputs() {
    setGeminiApiKeyInputs("");
  }

  function clearGeminiApiKeyInputsIfIdle() {
    const active = document.activeElement;
    geminiApiKeyInputs().forEach((el) => {
      if (el !== active) el.value = "";
    });
  }

  function updateApiKeyIndicators() {
    const geminiSet = !!(
      state.config &&
      state.config.gemini &&
      state.config.gemini.api_key_set
    );

    const badges = [$("#gemini-key-badge"), $("#gemini-key-google-badge")];
    const statuses = [$("#gemini-key-status"), $("#gemini-key-google-status")];
    badges.forEach((badge) => {
      if (!badge) return;
      badge.textContent = geminiSet ? "Saved" : "Not set";
      badge.classList.toggle("key-badge-set", geminiSet);
      badge.classList.toggle("key-badge-missing", !geminiSet);
    });
    geminiApiKeyInputs().forEach((input) => {
      input.placeholder = geminiSet
        ? "Leave blank to keep saved key"
        : "Paste Gemini API key";
    });
    statuses.forEach((statusEl) => {
      if (!statusEl) return;
      statusEl.textContent = geminiSet
        ? "A Gemini API key is already saved in config.yaml. Leave the field blank to keep it."
        : "No Gemini API key saved yet. Paste a key and click Save API key.";
    });
  }

  function updateGoogleWorkspaceAuthIndicators(status) {
    const pathInput = $("#google-workspace-credentials-path");
    const configured = !!(pathInput && pathInput.value.trim());
    const badge = $("#google-workspace-auth-badge");
    const statusEl = $("#google-workspace-auth-status");
    const authorized = !!(status && status.authorized);

    if (badge) {
      if (authorized) {
        badge.textContent = "Connected";
        badge.classList.add("key-badge-set");
        badge.classList.remove("key-badge-missing");
      } else if (configured) {
        badge.textContent = "Not connected";
        badge.classList.remove("key-badge-set");
        badge.classList.add("key-badge-missing");
      } else {
        badge.textContent = "Not configured";
        badge.classList.remove("key-badge-set");
        badge.classList.add("key-badge-missing");
      }
    }
    if (statusEl) {
      if (authorized) {
        if (status && status.has_refresh_token === false) {
          statusEl.textContent =
            "Google Workspace is connected, but Google did not issue a refresh token. Click Connect Google Workspace again so the session can renew after the hourly access token expires.";
        } else {
          const products = (status && status.granted_products) || [];
          const missing = (status && status.missing_scopes) || [];
          let text = products.length
            ? "Google Workspace is connected (" + products.join(", ") + "). Attach Gmail, Drive, Docs, Calendar, or Tasks tools in Studio."
            : "Google Workspace is connected. Attach Gmail, Drive, Docs, Calendar, or Tasks tools in Studio.";
          if (missing.length) {
            text += " Some requested scopes were not granted — Connect Google Workspace again if a product is missing.";
          }
          statusEl.textContent = text;
        }
      } else if (configured) {
        statusEl.textContent =
          "OAuth client JSON selected. Save settings, then click Connect Google Workspace.";
      } else {
        statusEl.textContent =
          "Pick an OAuth client JSON, Save, then Connect Google Workspace.";
      }
    }
  }

  async function refreshGoogleWorkspaceAuthStatus() {
    try {
      const a = api();
      if (!a) {
        updateGoogleWorkspaceAuthIndicators();
        return;
      }
      const res = a.get_google_workspace_auth_status
        ? await a.get_google_workspace_auth_status()
        : await a.get_gmail_auth_status();
      updateGoogleWorkspaceAuthIndicators(res);
    } catch (_err) {
      updateGoogleWorkspaceAuthIndicators();
    }
  }

  function providerApiKeyReady() {
    if (typedGeminiApiKey()) return true;
    return !!(
      state.config &&
      state.config.gemini &&
      state.config.gemini.api_key_set
    );
  }

  function ensureApiKeyBeforeSave() {
    if (providerApiKeyReady()) return true;
    showToast("Paste a Gemini API key before saving.");
    const first = geminiApiKeyInputs()[0];
    if (first) first.focus();
    return false;
  }

  async function saveGeminiApiKeyFromControls() {
    const typed = typedGeminiApiKey();
    const alreadySet = !!(
      state.config &&
      state.config.gemini &&
      state.config.gemini.api_key_set
    );
    if (!typed && !alreadySet) {
      showToast("Paste a Gemini API key first.");
      const first = geminiApiKeyInputs()[0];
      if (first) first.focus();
      return;
    }
    if (!api()) {
      showToast("Python bridge not ready.");
      return;
    }
    await persistSettingsNow({ applyDisplay: false });
    clearGeminiApiKeyInputs();
    updateApiKeyIndicators();
    showToast(typed ? "Gemini API key saved to config.yaml." : "Settings saved.");
  }

  function currentGeminiUiConfig() {
    const text =
      ($("#gemini-text-model") && $("#gemini-text-model").value) ||
      "gemini-2.5-flash";
    return {
      text_model: text,
      image_model:
        ($("#gemini-image-model") && $("#gemini-image-model").value) ||
        "gemini-2.5-flash-image",
      video_model:
        ($("#gemini-video-model") && $("#gemini-video-model").value) ||
        "veo-2.0-generate-001",
      audio_model:
        ($("#gemini-audio-model") && $("#gemini-audio-model").value) ||
        "lyria-3-clip-preview",
    };
  }

  function collectSettings() {
    return {
      backend: { provider: "gemini" },
      gemini: {
        text_model:
          ($("#gemini-text-model") && $("#gemini-text-model").value.trim()) ||
          "gemini-2.5-flash",
        image_model:
          ($("#gemini-image-model") && $("#gemini-image-model").value.trim()) ||
          "gemini-2.5-flash-image",
        video_model:
          ($("#gemini-video-model") && $("#gemini-video-model").value.trim()) ||
          "veo-2.0-generate-001",
        audio_model:
          ($("#gemini-audio-model") && $("#gemini-audio-model").value.trim()) ||
          "lyria-3-clip-preview",
        api_key: typedGeminiApiKey(),
        google_search: $("#gemini-search") ? $("#gemini-search").checked : true,
        two_pass_verify: $("#gemini-two-pass") ? $("#gemini-two-pass").checked : true,
        use_tools: $("#gemini-use-tools") ? $("#gemini-use-tools").checked : false,
        ocr_search_images: $("#gemini-ocr-search-images")
          ? $("#gemini-ocr-search-images").checked
          : true,
        youtube_search_captions: $("#gemini-youtube-search-captions")
          ? $("#gemini-youtube-search-captions").checked
          : true,
        temperature: $("#gemini-temp") ? Number($("#gemini-temp").value) || 0 : 0,
      },
      prompt: {
        extra_instructions: ($("#system-extra") && $("#system-extra").value) || "",
      },
      google_workspace: {
        credentials_path:
          ($("#google-workspace-credentials-path") &&
            $("#google-workspace-credentials-path").value.trim()) ||
          null,
        token_path: ".synthetic-text-extruder/google_workspace_token.json",
      },
      paths: {
        media:
          ($("#media-folder-path") && $("#media-folder-path").value.trim()) ||
          "media",
      },
      ui: {
        sound_enabled: $("#opt-sound").checked,
        sound_volume: clampSoundVolume(
          $("#opt-sound-volume") ? $("#opt-sound-volume").value : state.soundVolume
        ),
        crt_enabled: false,
        ui_scale: 1,
        ui_font:
          ($("#ui-font") && $("#ui-font").value) || state.uiFont || "inter",
        ui_font_size: parseUiFontSize(
          ($("#ui-font-size") && $("#ui-font-size").value) || state.uiFontSize
        ),
        app_theme: resolveAppThemeKey(
          ($("#app-theme") && $("#app-theme").value) || state.appTheme || "light"
        ),
        custom_theme: {
          desktop_color: state.customTheme.desktopColor,
          window_color: state.customTheme.windowColor,
          title_color: state.customTheme.titleColor,
          text_color: state.customTheme.textColor,
          font: state.customTheme.font || "sans",
        },
        studio_basis_width: parseStudioBasisWidth(state.studioBasisWidth),
      },
    };
  }

  function readUiScaleFromControl() {
    const raw = $("#ui-scale") ? Number($("#ui-scale").value) : state.uiScale || 1;
    if (!Number.isFinite(raw)) return 1;
    return Math.min(2, Math.max(0.75, raw));
  }

  function applyUiScale(scale) {
    const s = Number(scale);
    const clamped = Number.isFinite(s) ? Math.min(2, Math.max(0.75, s)) : 1;
    state.uiScale = clamped;
    // DPI-style scale: logical desktop is viewport/scale, then zoomed to fill the screen.
    document.documentElement.style.setProperty("--ui-scale", String(clamped));
    document.documentElement.style.zoom = "";
    const label = $("#ui-scale-label");
    if (label) label.textContent = Math.round(clamped * 100) + "%";
    requestAnimationFrame(() => {
      layoutOpenWindowsInWorkArea();
      syncDesktopScrollExtent();
    });
  }

  function setSettingsPage(page, opts) {
    opts = opts || {};
    const allowed = {
      models: true,
      generation: true,
      google: true,
      storage: true,
      appearance: true,
      ai: true,
      display: true,
    };
    let next = allowed[page] ? page : "models";
    if (next === "ai") next = "models";
    if (next === "display") next = "appearance";
    if (!opts.skipSave && state.settingsPage && state.settingsPage !== next) {
      void persistSettingsNow({ applyDisplay: true });
    }
    state.settingsPage = next;
    document.querySelectorAll(".settings-nav-item").forEach((btn) => {
      const selected = btn.getAttribute("data-settings-page") === next;
      if (selected) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    document.querySelectorAll(".control-pane").forEach((pane) => {
      const id = pane.getAttribute("data-control-pane");
      pane.hidden = id !== next;
    });
  }

  function setControlTab(tab) {
    setSettingsPage(tab);
  }

  function syncControlPanelWidth() {
    const win = $("#win-control");
    if (!win) return;
    const ai = state.controlTab !== "display";
    win.classList.toggle("control-tab-ai", ai);
    win.classList.toggle("control-tab-display", !ai);
  }

  function applyDisplaySettingsFromControls() {
    state.soundEnabled = $("#opt-sound").checked;
    applySoundVolume(
      $("#opt-sound-volume") ? $("#opt-sound-volume").value : state.soundVolume
    );
    if ($("#opt-sound-volume")) {
      $("#opt-sound-volume").disabled = !state.soundEnabled;
    }
    state.crtEnabled = false;
    applyUiScale(1);
    applyUiFont(
      ($("#ui-font") && $("#ui-font").value) || state.uiFont || "inter"
    );
    applyUiFontSize(
      ($("#ui-font-size") && $("#ui-font-size").value) || state.uiFontSize
    );
    const themeKey =
      ($("#app-theme") && $("#app-theme").value) || state.appTheme || "light";
    applyAppTheme(themeKey);
  }

  function fillAppThemeSelect() {
    const dst = $("#app-theme");
    if (!dst) return;
    const prev = resolveAppThemeKey(dst.value || state.appTheme || "light");
    dst.innerHTML = "";
    [
      ["light", "Light Mode (Day)"],
      ["dark", "Dark Mode (Night)"],
    ].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      dst.appendChild(opt);
    });
    dst.value = prev;
  }

  function applyCreationPlaceholders(template, game, platform) {
    let text = String(template || "").replace(/\r\n/g, "\n");
    const g = String(game || "").trim();
    const p = String(platform || "").trim();
    if (g) text = text.replace(/\[GAME\]/gi, g);
    if (p) text = text.replace(/\[PLATFORM\]/gi, p);
    return text;
  }

  function syncCreationDescription() {
    // Prompt is user-authored; no auto-fill from catalogs.
  }

  function getCreationDescription() {
    return getStudioPrompt();
  }

  function fillCatalogs(boot) {
    const creationTypes =
      (boot && boot.creationTypes) ||
      (window.RGC_CATALOG && window.RGC_CATALOG.creationTypes) ||
      [];
    const presets =
      (boot && boot.presets) ||
      (window.RGC_CATALOG && window.RGC_CATALOG.presets) ||
      [];
    state.presets = presets;
    state.creationTypes = creationTypes;
  }

  window.__onProgress = function (payload) {
    let message = "";
    let percent = undefined;
    let title = null;
    let phase = "";
    if (payload && typeof payload === "object") {
      message = payload.message || payload.detail || "";
      if (payload.percent != null) percent = payload.percent;
      if (payload.title) title = payload.title;
      phase = String(payload.phase || "");
    } else {
      message = String(payload || "");
    }

    // Keep create vs model-download framing distinct even when generation
    // briefly downloads/loads a local model first.
    if (busy.activity === "generate") {
      if (phase === "download") {
        title = "Creating…";
        if (message && !/^preparing model/i.test(message)) {
          message = "Preparing model — " + message;
        }
      } else if (phase === "load") {
        title = "Creating…";
        if (message && !/^loading model/i.test(message)) {
          message = "Loading model — " + message;
        }
      } else if (title) {
        // Keep provider titles like "Generating image"
      } else if (phase === "generate") {
        title = "Creating…";
      } else {
        title = title || busy.title || "Creating…";
      }
    } else {
      if (phase === "download") title = title || "Downloading model";
      if (phase === "load") title = title || "Loading model";
      if (phase === "generate") title = title || "Creating…";
    }

    updateBusy(message, percent, title);
  };

  function applyGenerationResult(creation) {
    if (!creation) return;
    // Idempotent — poll and evaluate_js may both fire (require a real id)
    if (creation.id && state._lastHandledId === creation.id) return;
    if (creation.id) state._lastHandledId = creation.id;

    state.generating = false;
    setCreateBlocked(false);
    endBusy("Ready");
    const layout = getExtractedLayout(creation);
    const extractedText = getExtractedText(creation);
    const sameBasis =
      !!state.studioBasis &&
      !!creation.id &&
      creation.id === state.studioBasis.creationId;
    const studioJob = String(
      (creation.meta && creation.meta.studioJob) || ""
    ).toLowerCase();
    const extractedThisJob = sameBasis && studioJob === "layout" && !!layout;
    const extractedTextThisJob =
      sameBasis && studioJob === "extract" && !!extractedText;
    if (extractedThisJob) {
      state.studioBasis.layout = layout;
      renderStudioBasisPanel();
      setStudioPrompt(formatLayoutBasisPrompt(layout, ""));
      if (studioToolsEnabled()) {
        setStudioSearch(formatLayoutBasisPrompt(layout, ""));
      }
      state.viewerTab = "layout";
    } else if (extractedTextThisJob) {
      renderStudioBasisPanel();
      state.viewerTab = "extracted";
    } else if (state.studioBasis) {
      clearStudioBasis();
    }
    state.creations = [creation].concat(
      state.creations.filter((c) => c.id !== creation.id)
    );
    renderArchives();
    renderDocument(creation);
    openWindow("viewer");
    focusWindow("viewer");
    playUiSound("success");
    if (extractedThisJob) {
      const count =
        layout && Array.isArray(layout.elements) ? layout.elements.length : 0;
      showToast(
        layout && layout.isUi === false
          ? "No UI chrome found. The screenshot is still the Studio basis."
          : "Layout ready (" +
              count +
              " element" +
              (count === 1 ? "" : "s") +
              "). Prompt Studio to recreate it as HTML/CSS or an app."
      );
    } else if (extractedTextThisJob) {
      const kind = String(
        (creation.meta && creation.meta.extractionKind) || ""
      ).toLowerCase();
      showToast(
        kind === "transcript"
          ? "Transcript ready. It is on the Extracted tab."
          : "Extracted text ready. It is on the Extracted tab."
      );
    }
  }

  function applyGenerationError(err) {
    state.generating = false;
    setCreateBlocked(false);
    endBusy("Ready");
    showToast(String(err));
    playUiSound("error");
  }

  async function applyRetiredGeminiModel(info) {
    if (!info) return;
    state.generating = false;
    setCreateBlocked(false);
    endBusy("Ready");
    const retiredId = String((info && info.retired) || "").toLowerCase();
    if (retiredId) {
      const set = new Set(state.retiredGeminiModels || []);
      set.add(retiredId);
      state.retiredGeminiModels = [...set];
    }
    const msg =
      (info && info.message) ||
      "A Gemini model was retired. Open Settings → AI Model to pick another.";
    showToast(msg, 16000);
    playUiSound("error");
    openWindow("control");
    focusWindow("control");
    setControlTab("ai");
    const gemini = (info && info.gemini) || {};
    // Prefill slots with replacements before refresh so pickers land on them.
    if ($("#gemini-text-model") && gemini.text_model) {
      $("#gemini-text-model").value = gemini.text_model;
    }
    if ($("#gemini-image-model") && gemini.image_model) {
      $("#gemini-image-model").value = gemini.image_model;
    }
    if ($("#gemini-video-model") && gemini.video_model) {
      $("#gemini-video-model").value = gemini.video_model;
    }
    if ($("#gemini-audio-model") && gemini.audio_model) {
      $("#gemini-audio-model").value = gemini.audio_model;
    }
    try {
      await refreshGeminiModelsForControlPanel();
    } catch (_) {
      /* refresh shows its own toast */
    }
    updateStudioBackendLabel({
      config: {
        backend: { provider: "gemini" },
        gemini: gemini,
      },
    });
  }

  function applyGenerationCancelled() {
    if (!state.generating && !busy.visible) return;
    state.generating = false;
    setCreateBlocked(false);
    endBusy("Ready");
    showToast("Generation cancelled");
    playUiSound("cancel");
  }

  function applyExtractResult(creation) {
    if (!creation) {
      endBusy();
      return;
    }
    endBusy("Ready");
    state.creations = [creation].concat(
      state.creations.filter((c) => c.id !== creation.id)
    );
    renderArchives();
    state.viewerTab = "extracted";
    renderDocument(creation);
    openWindow("viewer");
    focusWindow("viewer");
    const kind =
      creation.meta && String(creation.meta.extractionKind || "").toLowerCase();
    showToast(
      kind === "transcript" ? "Transcript ready." : "Extracted text ready."
    );
    playUiSound("success");
  }

  function applyLayoutResult(creation) {
    if (!creation) {
      endBusy();
      return;
    }
    endBusy("Ready");
    state.creations = [creation].concat(
      state.creations.filter((c) => c.id !== creation.id)
    );
    renderArchives();
    state.viewerTab = "layout";
    renderDocument(creation);
    openWindow("viewer");
    focusWindow("viewer");
    const layout = getExtractedLayout(creation);
    const count =
      layout && Array.isArray(layout.elements) ? layout.elements.length : 0;
    showToast(
      layout && layout.isUi === false
        ? "No UI chrome found."
        : "Layout ready (" + count + " element" + (count === 1 ? "" : "s") + ")."
    );
    playUiSound("success");
  }

  async function requestCancelBusyJob() {
    if (!busy.cancellable || busy.cancelling) return;
    const jobId = busy.jobId;
    if (!jobId) {
      showToast("Nothing to cancel yet.");
      return;
    }
    const a = api();
    if (!a || typeof a.cancel_job !== "function") {
      showToast("Cancel is not available.");
      return;
    }
    busy.cancelling = true;
    setBusyCancelVisible(true);
    updateBusy("Cancelling…");
    try {
      const res = await a.cancel_job(jobId);
      if (!res || !res.ok) {
        busy.cancelling = false;
        setBusyCancelVisible(true);
        showToast((res && res.error) || "Could not cancel");
        return;
      }
      // Dismiss overlay immediately; pollJob still waits for cancelled status.
      const kind = busy.activity;
      endBusy("Cancelling…");
      setProgress("Cancelling…");
      if (kind === "generate") {
        // Keep CREATE blocked until pollJob sees cancelled/error/done.
        setCreateBlocked(true);
        state.generating = true;
      }
      showToast("Cancelling…");
    } catch (err) {
      busy.cancelling = false;
      setBusyCancelVisible(true);
      showToast("Cancel failed: " + err);
    }
  }

  let _choiceHandledKey = "";

  async function applyNeedsChoice(payload) {
    if (!payload || payload.kind !== "ambiguous") return;
    const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    const key =
      String(payload.query || "") +
      "|" +
      candidates.map((c) => (c && c.game) || "").join("|");
    if (_choiceHandledKey === key) return;
    _choiceHandledKey = key;

    state.generating = false;
    setCreateBlocked(false);
    endBusy("Ready");

    if (candidates.length < 2) {
      showToast('Game Not Found — could not disambiguate "' + (payload.query || "") + '".');
      return;
    }

    const picked = await showSearchResults(payload.query, candidates);
    if (!picked || !picked.game) {
      showToast("Cancelled — pick a game from Search Results when ready.");
      return;
    }

    const gameInput = studioToolsEnabled()
      ? $("#studio-search") || $("#studio-prompt")
      : $("#studio-prompt");
    if (gameInput && picked.game && !gameInput.value.trim()) {
      gameInput.value = picked.game;
    }

    await startGeneration({
      exactTitle: true,
      game: picked.game,
      platform: picked.platform || "General",
    });
  }

  /**
   * Poll Python get_job until done/error/needs_choice. This is the reliable completion path
   * on Windows WebView2 where evaluate_js from worker threads often fails.
   */
  async function pollJob(jobId, kind) {
    const a = api();
    if (!a || !jobId) return;
    const started = Date.now();
    const maxMs = 60 * 60 * 1000;

    while (Date.now() - started < maxMs) {
      let job;
      try {
        job = await a.get_job(jobId);
      } catch (err) {
        if (kind === "generate") {
          applyGenerationError("Lost connection to Python bridge: " + err);
        } else {
          endBusy();
          showToast("Lost connection to Python bridge: " + err);
        }
        return;
      }

      if (!job) {
        await sleep(500);
        continue;
      }

      if (job.progress) {
        window.__onProgress(job.progress);
      }

      if (job.status === "done") {
        if (kind === "generate") {
          applyGenerationResult(job.result);
        } else if (kind === "extract") {
          applyExtractResult(job.result);
        } else if (kind === "layout") {
          applyLayoutResult(job.result);
        } else {
          endBusy();
          showToast(job.error || "Unexpected job completed.");
        }
        return;
      }

      if (job.status === "needs_choice") {
        if (kind === "generate") {
          await applyNeedsChoice(job.result);
        }
        return;
      }

      if (job.status === "cancelled") {
        if (kind === "generate") {
          applyGenerationCancelled();
        } else if (kind === "extract") {
          endBusy();
          showToast("Extract Text cancelled.");
          playUiSound("cancel");
        } else if (kind === "layout") {
          endBusy();
          showToast("Extract Layout cancelled.");
          playUiSound("cancel");
        } else {
          endBusy();
          showToast("Cancelled");
        }
        return;
      }

      if (job.status === "cancelling") {
        // Overlay already dismissed after cancel_job; keep status line only.
        setProgress("Cancelling…");
      }

      if (job.status === "error" || job.status === "missing") {
        if (job.retired_model) {
          await applyRetiredGeminiModel(job.retired_model);
          return;
        }
        if (kind === "generate") {
          applyGenerationError(job.error || "Generation failed");
        } else if (kind === "extract") {
          endBusy();
          showToast(job.error || "Extract Text failed");
          playUiSound("error");
        } else if (kind === "layout") {
          endBusy();
          showToast(job.error || "Extract Layout failed");
          playUiSound("error");
        } else {
          endBusy();
          showToast(job.error || "Job failed");
        }
        return;
      }

      await sleep(500);
    }

    if (kind === "generate") {
      applyGenerationError("Timed out waiting for generation.");
    } else if (kind === "extract") {
      endBusy();
      showToast("Timed out waiting for Extract Text.");
      playUiSound("error");
    } else if (kind === "layout") {
      endBusy();
      showToast("Timed out waiting for Extract Layout.");
      playUiSound("error");
    } else {
      endBusy();
      showToast("Timed out waiting for job.");
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  let startGenerationLock = false;

  function applyModalityMismatch(res) {
    const msg =
      (res && res.error) ||
      "This prompt needs a Gemini image or video model. Pick one in Settings.";
    showToast(msg, 14000);
    setProgress("Stopped");
    playUiSound("error");
    openWindow("control");
  }

  async function startGeneration(opts) {
    const exactTitle = !!(opts && opts.exactTitle);
    if (startGenerationLock || state.generating) {
      showToast("A generation is already running…");
      return;
    }
    // Fresh user-initiated search may need a new Search Results dialog
    if (!exactTitle) _choiceHandledKey = "";
    // Layout extract updates the basis in place (same Archive id).
    state._lastHandledId = "";
    startGenerationLock = true;

    try {
      const a = api();
      if (!a) {
        showToast("Python bridge not ready. Launch via: python -m synthetic_text_extruder");
        return;
      }

      const texts = getStudioCreateTexts();
      const toolsOn = texts.toolsMode;
      let toolAliases = toolsOn ? (state.studioTools || []).slice() : [];
      let searchQuery = "";
      let prompt = (texts.prompt || "").trim();

      if (toolsOn) {
        const search = (texts.search || "").trim();
        const toolUse = (texts.toolUse || "").trim();
        if (!toolUse) {
          showToast(
            "Cannot create — fill in Tool Use (describe the tool steps and reference attached aliases)."
          );
          return;
        }
        if (!toolAliases.length) {
          showToast(
            "Cannot create — Use Tools is on, so attach at least one tool with Add Tool…"
          );
          return;
        }
        const referenced = toolAliasesReferencedInText(toolUse, toolAliases);
        if (!referenced.length) {
          showToast(
            "Cannot create — Tool Use must reference attached tools (e.g. " +
              toolAliases.slice(0, 3).join(", ") +
              ")."
          );
          return;
        }
        searchQuery = search;
        prompt = toolUse;
      } else if (!prompt) {
        showToast("Enter a prompt to create.");
        return;
      }

      const basisId =
        (state.studioBasis && state.studioBasis.creationId) || "";
      // Prefer prompt intent (video/image keywords); else keep basis modality.
      // "Generate a video…" + image basis → image-to-video, not img2img.
      // "Extract the layout" / "extract the text" / "transcribe" are analysis, not img2img.
      let compatPrompt = prompt;
      let wantsMedia = false;
      if (basisId && state.studioBasis) {
        const lower = prompt.toLowerCase();
        const wantsLayoutExtract =
          /\b(extract|find|detect|analyze|map|inspect|pull|grab|get)\b[\s\S]{0,40}\b(the\s+)?(ui\s+)?layout\b/.test(
            lower
          ) ||
          /\bextract\b[\s\S]{0,40}\b(ui(\s+chrome)?|coordinates?|regions?)\b/.test(
            lower
          ) ||
          /\b(ui\s+)?layout\s+json\b/.test(lower) ||
          /\bfind\b[\s\S]{0,32}\b(ui\s+)?chrome\b/.test(lower);
        const wantsTextExtract =
          !wantsLayoutExtract &&
          (/\b(extract|ocr|read|pull|grab|get)\b[\s\S]{0,40}\b(the\s+)?(text|words|captions?|subtitles?)\b/.test(
            lower
          ) ||
            /\bocr\b/.test(lower) ||
            /\btranscri(be|ption|pt)\b/.test(lower) ||
            /\bspeech[\s-]?to[\s-]?text\b/.test(lower));
        const wantsAudio =
          /\b(create|generate|make|compose|produce|write|score)\b[\s\S]{0,48}\b(music|song|soundtrack|jingle|melody|tune|instrumental|chiptune)\b/.test(
            lower
          ) ||
          /\b(music|song|soundtrack|jingle|melody|chiptune)\s+(of|about|for|in)\b/.test(
            lower
          ) ||
          /\blyria\b/.test(lower) ||
          /\binstrumental\s+only\b/.test(lower) ||
          /\b(background|game)\s+(music|soundtrack)\b/.test(lower);
        const wantsVideo =
          /\b(create|generate|make|render|produce|shoot|film)\b[\s\S]{0,48}\b(video|clip|animation|footage|movie|cinematic)\b/.test(
            lower
          ) ||
          /\b(turn|convert|transform|morph|change)\b[\s\S]{0,48}\b(into|to)\b[\s\S]{0,24}\b(video|clip|animation|footage|movie)\b/.test(
            lower
          ) ||
          /\b(video|clip|animation|footage)\s+of\b/.test(lower) ||
          /\banimate\b/.test(lower);
        const wantsImage =
          /\b(create|generate|make|render|draw|paint|illustrate)\b[\s\S]{0,40}\b(image|picture|photo|illustration|drawing)\b/.test(
            lower
          ) || /\b(image|picture|photo)\s+of\b/.test(lower);
        if (wantsLayoutExtract || wantsTextExtract) {
          wantsMedia = false;
        } else if (wantsAudio) {
          compatPrompt = "Generate music: " + prompt;
          wantsMedia = true;
        } else if (wantsVideo) {
          compatPrompt = "Generate a video: " + prompt;
          wantsMedia = true;
        } else if (wantsImage) {
          compatPrompt = "Create an image: " + prompt;
          wantsMedia = true;
        } else if (state.studioBasis.layout) {
          wantsMedia = false;
        } else if (state.studioBasis.modality === "video") {
          compatPrompt = "Generate a video: " + prompt;
          wantsMedia = true;
        } else {
          compatPrompt = "Create an image: " + prompt;
          wantsMedia = true;
        }
      }

      // Preflight: image/video prompts on text models (and reverse) stop here
      try {
        if (typeof a.check_modality_match === "function") {
          const compat = await a.check_modality_match(compatPrompt);
          if (compat && compat.ok === false) {
            applyModalityMismatch(compat);
            return;
          }
          if (
            compat &&
            (compat.promptModality === "image" ||
              compat.promptModality === "video" ||
              compat.promptModality === "audio")
          ) {
            wantsMedia = true;
          }
        }
      } catch (_) {
        /* fall through — server create_creation still guards */
      }

      if (toolsOn && wantsMedia) {
        if (toolAliases.length) {
          showToast("Tools apply to text only — generating without tools.");
        }
        toolAliases = [];
        searchQuery = "";
        // Media path uses Search + Tool Use as the combined prompt.
        const search = (texts.search || "").trim();
        const toolUse = (texts.toolUse || "").trim();
        prompt = [search, toolUse].filter(Boolean).join("\n\n") || prompt;
      }

      const game = ((opts && opts.game) || "Prompt").trim() || "Prompt";
      const platform =
        ((opts && opts.platform) || "General").trim() || "General";
      const creationType = "Custom";
      const creationDescription = prompt;

      state.generating = true;
      $("#btn-generate").disabled = true;
      beginBusy("Creating…", "Starting generation…", {
        delayMs: 0,
        cancellable: true,
        activity: "generate",
        hint: BUSY_HINTS.generate,
      });
      try {
        await a.ping();
      } catch (err) {
        applyGenerationError("Python bridge not responding: " + err);
        return;
      }

      let res;
      try {
        res = await a.create_creation(
          game,
          platform,
          creationType,
          true,
          creationDescription,
          basisId,
          toolAliases,
          searchQuery
        );
      } catch (err) {
        applyGenerationError(err);
        return;
      }

      if (!res || !res.ok) {
        if (res && res.modalityMismatch) {
          state.generating = false;
          setCreateBlocked(false);
          endBusy("Ready");
          applyModalityMismatch(res);
          return;
        }
        applyGenerationError((res && res.error) || "Generation failed to start");
        return;
      }
      if (!res.job_id) {
        applyGenerationError("Backend did not return a job id.");
        return;
      }
      busy.jobId = res.job_id;
      busy.cancellable = true;
      setBusyCancelVisible(true);
      updateBusy(
        exactTitle
          ? "Creating for selected title…"
          : "Generation started…",
        undefined,
        "Creating…"
      );
      pollJob(res.job_id, "generate");
    } finally {
      startGenerationLock = false;
    }
  }

  window.__onGenerationComplete = function (creation) {
    // evaluate_js best-effort path
    if (!creation) return;
    if (!state.generating && !busy.visible) {
      // Already handled via poll
      return;
    }
    applyGenerationResult(creation);
  };

  window.__onGenerateError = function (err) {
    if (!state.generating && !busy.visible) return;
    applyGenerationError(err);
  };

  window.__onRetiredGeminiModel = function (info) {
    if (!info) return;
    applyRetiredGeminiModel(info);
  };

  window.__onGenerateCancelled = function () {
    if (!state.generating && !busy.visible) return;
    applyGenerationCancelled();
  };

  window.__onNeedsChoice = function (payload) {
    if (!state.generating && !busy.visible) return;
    applyNeedsChoice(payload);
  };

  window.__onModelStatus = function () {
    if (state.generating) return;
    endBusy("Ready");
  };

  // ── Image Edit (ReFrame-style filters + crop + rotate) ─────────────
  const imageEdit = {
    sourceImg: null,
    creationId: null,
    standalone: true, // desktop app vs Viewer Edit (Apply)
    filters: null,
    rotation: 0,
    crop: null, // {x,y,w,h} in source pixels
    cropDrag: null,
    dirty: false,
    raf: 0,
  };

  function markImageEditDirty() {
    imageEdit.dirty = true;
  }

  function setImageEditLoadedLabel(creation) {
    const el = $("#iedit-loaded-label");
    if (!el) return;
    el.textContent = creation
      ? "Loaded: " + creationTitle(creation)
      : "No image loaded";
  }

  function syncImageEditChrome() {
    const toolbar = $("#win-image-edit .editor-app-toolbar");
    if (toolbar) toolbar.hidden = !imageEdit.standalone;
    if ($("#btn-edit-apply")) $("#btn-edit-apply").hidden = !!imageEdit.standalone;
    if ($("#btn-edit-save")) $("#btn-edit-save").hidden = !imageEdit.standalone;
    // Save As is always available once an image is loaded (Archives Apply or desktop editor)
    if ($("#btn-edit-save-as")) $("#btn-edit-save-as").hidden = false;
    if ($("#btn-edit-send-creator")) $("#btn-edit-send-creator").hidden = false;
    const hint = $("#image-edit-hint");
    if (hint) {
      hint.textContent = imageEdit.standalone
        ? "Load an image to begin. At 0° rotation, drag to set a crop, then drag the box or handles to adjust. Save writes Archives; Save As… exports a file. Save and Send to Creator hands the current image to Creation Studio without the original filename."
        : "At 0° rotation, drag on the image to set a crop. Drag the yellow box to move, or use the handles to resize. Clear Crop to reset. Apply saves to Archives; Save As… exports a file. Save and Send to Creator hands the current image to Creation Studio without the original filename.";
    }
  }

  function prepareEmptyImageEditor() {
    imageEdit.sourceImg = null;
    imageEdit.creationId = null;
    imageEdit.standalone = true;
    imageEdit.crop = null;
    imageEdit.cropDrag = null;
    imageEdit.dirty = false;
    imageEdit.rotation = 0;
    if (window.R98ImageEdit) {
      imageEdit.filters = Object.assign({}, window.R98ImageEdit.DEFAULT_FILTERS);
      writeImageEditFiltersToUi(imageEdit.filters);
    }
    if ($("#edit-rotation")) $("#edit-rotation").value = 0;
    syncImageEditValueLabels();
    const canvas = $("#image-edit-canvas");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
      canvas.width = 320;
      canvas.height = 200;
      if (ctx) {
        ctx.fillStyle = "#808080";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#000";
        ctx.font = "12px sans-serif";
        ctx.fillText("Load an image to begin", 16, 28);
      }
    }
    const box = $("#image-edit-crop-box");
    if (box) box.hidden = true;
    setImageEditLoadedLabel(null);
    syncImageEditChrome();
  }

  async function loadImageIntoEditorFromFile() {
    const a = api();
    if (!a) return;
    beginBusy("Loading image", "Importing into Archives…", { delayMs: 0 });
    try {
      const res = await a.import_media_file("image");
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      rememberImportedCreation(res.creation);
      await openImageEditor(res.creation, { standalone: true });
      showToast("Image loaded into Image Editor");
    } catch (err) {
      showToast("Load failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  function readImageEditFiltersFromUi() {
    const num = (id, fallback) => {
      const el = $("#" + id);
      if (!el) return fallback;
      const n = Number(el.value);
      return Number.isFinite(n) ? n : fallback;
    };
    return {
      brightness: num("edit-brightness", 0),
      contrast: num("edit-contrast", 0),
      grayscale: !!($("#edit-grayscale") && $("#edit-grayscale").checked),
      threshold: !!($("#edit-threshold") && $("#edit-threshold").checked),
      sharpen: !!($("#edit-sharpen") && $("#edit-sharpen").checked),
      saturation: num("edit-saturation", 100),
      hueRotate: num("edit-hue", 0),
      invert: num("edit-invert", 0),
      sepia: num("edit-sepia", 0),
      blur: num("edit-blur", 0),
      exposure: num("edit-exposure", 0),
      gamma: num("edit-gamma", 1),
      vignette: num("edit-vignette", 0),
      tintRed: num("edit-tint-r", 0),
      tintGreen: num("edit-tint-g", 0),
      tintBlue: num("edit-tint-b", 0),
      bgRemove: !!($("#edit-bg-remove") && $("#edit-bg-remove").checked),
      bgRemoveTolerance: num("edit-bg-tolerance", 35),
      bgRemoveFromEdges: !!($("#edit-bg-edges") && $("#edit-bg-edges").checked),
    };
  }

  function writeImageEditFiltersToUi(filters) {
    const f = (window.R98ImageEdit && window.R98ImageEdit.normalizeFilters(filters)) || filters;
    const map = {
      "edit-brightness": f.brightness,
      "edit-contrast": f.contrast,
      "edit-saturation": f.saturation,
      "edit-hue": f.hueRotate,
      "edit-invert": f.invert,
      "edit-sepia": f.sepia,
      "edit-blur": f.blur,
      "edit-exposure": f.exposure,
      "edit-gamma": f.gamma,
      "edit-vignette": f.vignette,
      "edit-tint-r": f.tintRed,
      "edit-tint-g": f.tintGreen,
      "edit-tint-b": f.tintBlue,
      "edit-bg-tolerance": f.bgRemoveTolerance,
    };
    Object.keys(map).forEach((id) => {
      const el = $("#" + id);
      if (el) el.value = map[id];
    });
    if ($("#edit-grayscale")) $("#edit-grayscale").checked = !!f.grayscale;
    if ($("#edit-threshold")) $("#edit-threshold").checked = !!f.threshold;
    if ($("#edit-sharpen")) $("#edit-sharpen").checked = !!f.sharpen;
    if ($("#edit-bg-remove")) $("#edit-bg-remove").checked = !!f.bgRemove;
    if ($("#edit-bg-edges")) $("#edit-bg-edges").checked = !!f.bgRemoveFromEdges;
    syncImageEditValueLabels();
    syncBgRemoveRows();
  }

  function syncImageEditValueLabels() {
    document.querySelectorAll("#win-image-edit .edit-val[data-for]").forEach((el) => {
      const id = el.getAttribute("data-for");
      const input = id && $("#" + id);
      if (input) el.textContent = input.value;
    });
    if ($("#edit-rotation-label") && $("#edit-rotation")) {
      $("#edit-rotation-label").textContent = $("#edit-rotation").value + "°";
    }
  }

  function syncBgRemoveRows() {
    const on = !!($("#edit-bg-remove") && $("#edit-bg-remove").checked);
    if ($("#edit-bg-tol-row")) $("#edit-bg-tol-row").hidden = !on;
    if ($("#edit-bg-edges-row")) $("#edit-bg-edges-row").hidden = !on;
  }

  function scheduleImageEditPreview() {
    if (imageEdit.raf) cancelAnimationFrame(imageEdit.raf);
    imageEdit.raf = requestAnimationFrame(() => {
      imageEdit.raf = 0;
      renderImageEditPreview();
    });
  }

  function renderImageEditPreview() {
    const apiEdit = window.R98ImageEdit;
    const canvas = $("#image-edit-canvas");
    if (!apiEdit || !canvas || !imageEdit.sourceImg) return;
    imageEdit.filters = readImageEditFiltersFromUi();
    imageEdit.rotation = Number($("#edit-rotation") && $("#edit-rotation").value) || 0;
    // At 0° show the full filtered image so crop is drawn as an overlay.
    // When rotated, bake crop into the preview (overlay mapping is unreliable).
    const previewCrop = imageEdit.rotation ? imageEdit.crop : null;
    const out = apiEdit.renderEditedCanvas(
      imageEdit.sourceImg,
      imageEdit.filters,
      previewCrop,
      imageEdit.rotation
    );
    canvas.width = out.width;
    canvas.height = out.height;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(out, 0, 0);
    updateCropBoxOverlay();
  }

  /** Map pointer → source image pixels using the visible canvas box. */
  function imageEditClientToSourcePixels(clientX, clientY, opts) {
    opts = opts || {};
    const canvas = $("#image-edit-canvas");
    const img = imageEdit.sourceImg;
    if (!canvas || !img) return null;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return null;
    const sw = img.naturalWidth || img.width || canvas.width;
    const sh = img.naturalHeight || img.height || canvas.height;
    let nx = (clientX - rect.left) / rect.width;
    let ny = (clientY - rect.top) / rect.height;
    if (!opts.clamp) {
      if (nx < 0 || ny < 0 || nx > 1 || ny > 1) return null;
    } else {
      nx = Math.min(1, Math.max(0, nx));
      ny = Math.min(1, Math.max(0, ny));
    }
    return {
      x: Math.min(sw, Math.max(0, nx * sw)),
      y: Math.min(sh, Math.max(0, ny * sh)),
      sw: sw,
      sh: sh,
    };
  }

  function clampImageEditCrop(crop, sw, sh) {
    if (!crop) return null;
    let w = Math.max(1, Math.min(Number(crop.w) || 1, sw));
    let h = Math.max(1, Math.min(Number(crop.h) || 1, sh));
    let x = Number(crop.x) || 0;
    let y = Number(crop.y) || 0;
    x = Math.min(Math.max(0, x), Math.max(0, sw - w));
    y = Math.min(Math.max(0, y), Math.max(0, sh - h));
    return { x: x, y: y, w: w, h: h };
  }

  function ensureImageEditCropHandles(box) {
    if (!box || box.querySelector(".crop-handle")) return;
    ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach((dir) => {
      const handle = document.createElement("div");
      handle.className = "crop-handle crop-handle-" + dir;
      handle.dataset.handle = dir;
      box.appendChild(handle);
    });
  }

  function updateCropBoxOverlay() {
    const box = $("#image-edit-crop-box");
    const canvas = $("#image-edit-canvas");
    if (!box || !canvas || !imageEdit.sourceImg) return;
    const crop = imageEdit.crop;
    if (!crop || imageEdit.rotation) {
      box.hidden = true;
      return;
    }
    ensureImageEditCropHandles(box);
    // Crop box is positioned inside .image-edit-canvas-wrap (same box as the canvas),
    // so percentages track CSS scaling / centering without stage scroll math.
    const sw = imageEdit.sourceImg.naturalWidth || imageEdit.sourceImg.width || canvas.width;
    const sh = imageEdit.sourceImg.naturalHeight || imageEdit.sourceImg.height || canvas.height;
    box.hidden = false;
    box.style.left = (crop.x / sw) * 100 + "%";
    box.style.top = (crop.y / sh) * 100 + "%";
    box.style.width = (crop.w / sw) * 100 + "%";
    box.style.height = (crop.h / sh) * 100 + "%";
  }

  function resizeImageEditCropFromHandle(startCrop, handle, x1, y1, sw, sh) {
    const left0 = startCrop.x;
    const top0 = startCrop.y;
    const right0 = startCrop.x + startCrop.w;
    const bottom0 = startCrop.y + startCrop.h;
    let left = left0;
    let top = top0;
    let right = right0;
    let bottom = bottom0;
    if (handle.indexOf("w") !== -1) left = x1;
    if (handle.indexOf("e") !== -1) right = x1;
    if (handle.indexOf("n") !== -1) top = y1;
    if (handle.indexOf("s") !== -1) bottom = y1;
    left = Math.min(Math.max(0, left), sw);
    right = Math.min(Math.max(0, right), sw);
    top = Math.min(Math.max(0, top), sh);
    bottom = Math.min(Math.max(0, bottom), sh);
    return clampImageEditCrop(
      {
        x: Math.min(left, right),
        y: Math.min(top, bottom),
        w: Math.max(1, Math.abs(right - left)),
        h: Math.max(1, Math.abs(bottom - top)),
      },
      sw,
      sh
    );
  }

  async function openImageEditor(creation, opts) {
    opts = opts || {};
    if (!creation || creationModality(creation) !== "image") {
      showToast("Edit is available for image creations.");
      return false;
    }
    if (!window.R98ImageEdit) {
      showToast("Image edit module failed to load.");
      return false;
    }
    const a = api();
    if (!a) {
      showToast("Python bridge required to edit images.");
      return false;
    }
    const payload = await a.get_media_payload(creation);
    if (!payload || !payload.ok || !payload.dataUrl) {
      showToast((payload && payload.error) || "Could not load image.");
      return false;
    }

    const img = new Image();
    try {
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = payload.dataUrl;
      });
    } catch (_) {
      showToast("Could not decode image for editing.");
      return false;
    }

    imageEdit.sourceImg = img;
    imageEdit.creationId = creation.id;
    imageEdit.standalone = typeof opts.standalone === "boolean" ? opts.standalone : true;
    imageEdit.crop = null;
    imageEdit.cropDrag = null;
    imageEdit.dirty = false;
    imageEdit.rotation = 0;
    imageEdit.filters = Object.assign({}, window.R98ImageEdit.DEFAULT_FILTERS);
    if ($("#edit-rotation")) $("#edit-rotation").value = 0;
    writeImageEditFiltersToUi(imageEdit.filters);
    setImageEditLoadedLabel(creation);
    syncImageEditChrome();
    openWindow("image-edit");
    // Preview after the window is shown/laid out
    requestAnimationFrame(() => scheduleImageEditPreview());
    return true;
  }

  function resetImageEditor() {
    if (!window.R98ImageEdit) return;
    imageEdit.filters = Object.assign({}, window.R98ImageEdit.DEFAULT_FILTERS);
    imageEdit.crop = null;
    imageEdit.rotation = 0;
    imageEdit.dirty = false;
    if ($("#edit-rotation")) $("#edit-rotation").value = 0;
    writeImageEditFiltersToUi(imageEdit.filters);
    scheduleImageEditPreview();
  }

  function encodeEditedImageDataUrl() {
    if (!imageEdit.sourceImg || !window.R98ImageEdit) return null;
    const filters = readImageEditFiltersFromUi();
    const rotation = Number($("#edit-rotation") && $("#edit-rotation").value) || 0;
    const out = window.R98ImageEdit.renderEditedCanvas(
      imageEdit.sourceImg,
      filters,
      imageEdit.crop,
      rotation
    );
    const needsAlpha = !!(filters && filters.bgRemove);
    const mime = needsAlpha ? "image/png" : "image/jpeg";
    const dataUrl = window.R98ImageEdit.canvasToDataUrl(out, mime);
    if (!dataUrl || dataUrl.length < 32) return null;
    return { dataUrl, mime, filters };
  }

  async function persistEditedImageToArchives() {
    if (!imageEdit.creationId) {
      showToast("No Archive item — use Load Image… first.");
      return null;
    }
    const encoded = encodeEditedImageDataUrl();
    if (!encoded) {
      showToast("Could not encode edited image.");
      return null;
    }
    const httpRes = await fetch("/api/replace-creation-media", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        creationId: imageEdit.creationId,
        dataUrl: encoded.dataUrl,
        mimeType: encoded.mime,
      }),
    });
    let res = null;
    try {
      res = await httpRes.json();
    } catch (_) {
      res = null;
    }
    if (!httpRes.ok || !res || !res.ok) {
      showToast(
        (res && res.error) ||
          "Failed to save edited image (HTTP " + httpRes.status + ")"
      );
      return null;
    }
    const saved = res.creation;
    state.creations = [saved].concat(
      state.creations.filter((c) => c.id !== saved.id)
    );
    state.active = saved;
    renderArchives();
    return saved;
  }

  async function reloadImageEditorFromCreation(creation) {
    const a = api();
    if (!a || !creation) return;
    const payload = await a.get_media_payload(creation);
    if (!payload || !payload.ok || !payload.dataUrl) {
      showToast((payload && payload.error) || "Could not reload image.");
      return;
    }
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = payload.dataUrl;
    });
    imageEdit.sourceImg = img;
    imageEdit.creationId = creation.id;
    imageEdit.crop = null;
    imageEdit.cropDrag = null;
    imageEdit.rotation = 0;
    imageEdit.dirty = false;
    if (window.R98ImageEdit) {
      imageEdit.filters = Object.assign({}, window.R98ImageEdit.DEFAULT_FILTERS);
      writeImageEditFiltersToUi(imageEdit.filters);
    }
    if ($("#edit-rotation")) $("#edit-rotation").value = 0;
    setImageEditLoadedLabel(creation);
    syncImageEditValueLabels();
    scheduleImageEditPreview();
  }

  async function applyImageEditor() {
    if (!imageEdit.sourceImg || !window.R98ImageEdit) {
      showToast("Load an image first.");
      return;
    }
    beginBusy("Saving edit", "Applying filters and writing media…", { delayMs: 0 });
    try {
      const saved = await persistEditedImageToArchives();
      if (!saved) return;
      renderDocument(saved);
      closeImageEditor();
      showToast("Image edit applied");
    } catch (err) {
      showToast("Edit failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveImageEditor() {
    if (!imageEdit.sourceImg || !window.R98ImageEdit) {
      showToast("Load an image first.");
      return;
    }
    beginBusy("Saving image", "Writing edited image to Archives…", { delayMs: 0 });
    try {
      const saved = await persistEditedImageToArchives();
      if (!saved) return;
      await reloadImageEditorFromCreation(saved);
      showToast("Image saved");
    } catch (err) {
      showToast("Save failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveImageEditorAs() {
    if (!imageEdit.sourceImg || !window.R98ImageEdit) {
      showToast("Load an image first.");
      return;
    }
    beginBusy("Save As", "Encoding image…", { delayMs: 0 });
    try {
      const encoded = encodeEditedImageDataUrl();
      if (!encoded) {
        showToast("Could not encode edited image.");
        return;
      }
      const ext = encoded.mime === "image/png" ? ".png" : ".jpg";
      const creation =
        state.creations.find((c) => c.id === imageEdit.creationId) || state.active;
      const base = exportBaseName(creation || { title: "image" }) + ext;
      const httpRes = await fetch("/api/save-media-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          defaultName: base,
          dataUrl: encoded.dataUrl,
        }),
      });
      let res = null;
      try {
        res = await httpRes.json();
      } catch (_) {
        res = null;
      }
      if (res && res.cancelled) return;
      if (!httpRes.ok || !res || !res.ok) {
        showToast(
          (res && res.error) ||
            "Save As failed (HTTP " + httpRes.status + ")"
        );
        return;
      }
      showToast("Saved to " + (res.path || "file"));
    } catch (err) {
      showToast("Save As failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveImageEditorAndSendToCreator() {
    if (!imageEdit.sourceImg || !window.R98ImageEdit) {
      showToast("Load an image first.");
      return;
    }
    beginBusy("Sending to Creator", "Saving the edited image…", { delayMs: 0 });
    try {
      const saved = await persistEditedImageToArchives();
      if (!saved) return;
      await reloadImageEditorFromCreation(saved);
      await sendCreationToCreator(saved);
    } catch (err) {
      showToast("Send to Creator failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  function closeImageEditor() {
    closeWindow("image-edit");
  }

  async function requestCloseImageEditor() {
    await requestCloseWindow("image-edit");
  }

  function setupImageEditCropInteraction() {
    const stage = $("#image-edit-stage");
    const canvas = $("#image-edit-canvas");
    if (!stage || !canvas) return;

    stage.addEventListener("pointerdown", (e) => {
      if (!imageEdit.sourceImg) return;
      if (imageEdit.rotation) {
        showToast("Set rotation to 0° before drawing a crop (or crop first, then rotate).");
        return;
      }
      const handleEl =
        e.target && e.target.closest
          ? e.target.closest(".crop-handle")
          : null;
      const onCropBox =
        e.target && e.target.closest
          ? e.target.closest("#image-edit-crop-box")
          : null;
      const clamp = !!(handleEl || onCropBox || imageEdit.crop);
      const pt = imageEditClientToSourcePixels(e.clientX, e.clientY, {
        clamp: clamp,
      });
      if (!pt) return;

      if (handleEl && imageEdit.crop) {
        imageEdit.cropDrag = {
          mode: "resize",
          handle: handleEl.getAttribute("data-handle") || "se",
          x0: pt.x,
          y0: pt.y,
          startCrop: Object.assign({}, imageEdit.crop),
          pointerId: e.pointerId,
        };
      } else if (onCropBox && imageEdit.crop) {
        imageEdit.cropDrag = {
          mode: "move",
          handle: null,
          x0: pt.x,
          y0: pt.y,
          startCrop: Object.assign({}, imageEdit.crop),
          pointerId: e.pointerId,
        };
      } else {
        imageEdit.cropDrag = {
          mode: "draw",
          handle: null,
          x0: pt.x,
          y0: pt.y,
          startCrop: null,
          pointerId: e.pointerId,
        };
        // Tiny seed rect so overlay appears immediately
        imageEdit.crop = { x: pt.x, y: pt.y, w: 1, h: 1 };
      }
      updateCropBoxOverlay();
      stage.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    stage.addEventListener("pointermove", (e) => {
      if (!imageEdit.cropDrag || e.pointerId !== imageEdit.cropDrag.pointerId) return;
      const drag = imageEdit.cropDrag;
      const pt = imageEditClientToSourcePixels(e.clientX, e.clientY, {
        clamp: true,
      });
      if (!pt) return;
      const sw = pt.sw;
      const sh = pt.sh;

      if (drag.mode === "move" && drag.startCrop) {
        const dx = pt.x - drag.x0;
        const dy = pt.y - drag.y0;
        imageEdit.crop = clampImageEditCrop(
          {
            x: drag.startCrop.x + dx,
            y: drag.startCrop.y + dy,
            w: drag.startCrop.w,
            h: drag.startCrop.h,
          },
          sw,
          sh
        );
      } else if (drag.mode === "resize" && drag.startCrop && drag.handle) {
        imageEdit.crop = resizeImageEditCropFromHandle(
          drag.startCrop,
          drag.handle,
          pt.x,
          pt.y,
          sw,
          sh
        );
      } else {
        const x0 = drag.x0;
        const y0 = drag.y0;
        imageEdit.crop = clampImageEditCrop(
          {
            x: Math.min(x0, pt.x),
            y: Math.min(y0, pt.y),
            w: Math.max(1, Math.abs(pt.x - x0)),
            h: Math.max(1, Math.abs(pt.y - y0)),
          },
          sw,
          sh
        );
      }
      updateCropBoxOverlay();
    });

    const endDrag = (e) => {
      if (!imageEdit.cropDrag || e.pointerId !== imageEdit.cropDrag.pointerId) return;
      const mode = imageEdit.cropDrag.mode;
      imageEdit.cropDrag = null;
      try {
        stage.releasePointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      // Drop accidental clicks when drawing a new crop (no real drag)
      if (
        mode === "draw" &&
        imageEdit.crop &&
        (imageEdit.crop.w < 2 || imageEdit.crop.h < 2)
      ) {
        imageEdit.crop = null;
      } else if (imageEdit.crop || mode === "move" || mode === "resize") {
        markImageEditDirty();
      }
      updateCropBoxOverlay();
    };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
    stage.addEventListener("scroll", () => updateCropBoxOverlay());
    window.addEventListener("resize", () => updateCropBoxOverlay());
  }

  function wireImageEditEvents() {
    if ($("#btn-edit-image")) {
      $("#btn-edit-image").addEventListener("click", () => {
        void openImageEditor(state.active, { standalone: false });
      });
    }
    const controlIds = [
      "edit-brightness",
      "edit-contrast",
      "edit-saturation",
      "edit-hue",
      "edit-invert",
      "edit-sepia",
      "edit-blur",
      "edit-exposure",
      "edit-gamma",
      "edit-vignette",
      "edit-tint-r",
      "edit-tint-g",
      "edit-tint-b",
      "edit-bg-tolerance",
      "edit-rotation",
    ];
    controlIds.forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", () => {
        markImageEditDirty();
        syncImageEditValueLabels();
        scheduleImageEditPreview();
      });
      // Some WebView hosts fire change more reliably than input on ranges
      el.addEventListener("change", () => {
        markImageEditDirty();
        syncImageEditValueLabels();
        scheduleImageEditPreview();
      });
    });
    ["edit-grayscale", "edit-threshold", "edit-sharpen", "edit-bg-remove", "edit-bg-edges"].forEach(
      (id) => {
        const el = $("#" + id);
        if (!el) return;
        el.addEventListener("change", () => {
          markImageEditDirty();
          syncBgRemoveRows();
          scheduleImageEditPreview();
        });
      }
    );
    if ($("#btn-edit-rot-cw")) {
      $("#btn-edit-rot-cw").addEventListener("click", () => {
        const cur = Number($("#edit-rotation").value) || 0;
        $("#edit-rotation").value = String((cur + 90) % 360);
        markImageEditDirty();
        syncImageEditValueLabels();
        scheduleImageEditPreview();
      });
    }
    if ($("#btn-edit-rot-ccw")) {
      $("#btn-edit-rot-ccw").addEventListener("click", () => {
        const cur = Number($("#edit-rotation").value) || 0;
        $("#edit-rotation").value = String((cur + 270) % 360);
        markImageEditDirty();
        syncImageEditValueLabels();
        scheduleImageEditPreview();
      });
    }
    if ($("#btn-edit-crop-clear")) {
      $("#btn-edit-crop-clear").addEventListener("click", () => {
        if (imageEdit.crop) markImageEditDirty();
        imageEdit.crop = null;
        scheduleImageEditPreview();
      });
    }
    if ($("#btn-edit-reset")) {
      $("#btn-edit-reset").addEventListener("click", () => {
        resetImageEditor();
      });
    }
    if ($("#btn-edit-cancel")) {
      $("#btn-edit-cancel").addEventListener("click", () => {
        requestCloseImageEditor();
      });
    }
    if ($("#btn-edit-apply")) {
      $("#btn-edit-apply").addEventListener("click", () => {
        applyImageEditor();
      });
    }
    if ($("#btn-edit-save")) {
      $("#btn-edit-save").addEventListener("click", () => {
        saveImageEditor();
      });
    }
    if ($("#btn-edit-save-as")) {
      $("#btn-edit-save-as").addEventListener("click", () => {
        saveImageEditorAs();
      });
    }
    if ($("#btn-edit-send-creator")) {
      $("#btn-edit-send-creator").addEventListener("click", () => {
        saveImageEditorAndSendToCreator();
      });
    }
    setupImageEditCropInteraction();
  }

  // ── Video Edit (segment timeline + filters) ────────────────────────
  const videoEdit = {
    creationId: null,
    standalone: true, // desktop app vs Viewer Edit (Apply)
    fileUrl: null,
    duration: 0,
    crop: null, // normalized {x,y,w,h, normalized:true}
    cropDrag: null,
    rotation: 0,
    segments: [], // [{id, start, end}] source times, edit order
    selectedSegId: null,
    segSeq: 0,
    playSegIdx: 0, // which segment is playing in edit order
    boundarySeeking: false, // ignore timeupdates while jumping between segments
    raf: 0,
    showFilterPreview: false,
    dirty: false,
  };

  function markVideoEditDirty() {
    videoEdit.dirty = true;
  }

  function setVideoEditLoadedLabel(creation) {
    const el = $("#vedit-loaded-label");
    if (!el) return;
    el.textContent = creation
      ? "Loaded: " + creationTitle(creation)
      : "No video loaded";
  }

  function syncVideoEditChrome() {
    const toolbar = $("#win-video-edit .editor-app-toolbar");
    if (toolbar) toolbar.hidden = !videoEdit.standalone;
    if ($("#btn-vedit-apply")) $("#btn-vedit-apply").hidden = !!videoEdit.standalone;
    if ($("#btn-vedit-save")) $("#btn-vedit-save").hidden = !videoEdit.standalone;
    // Save As is always available once a video is loaded
    if ($("#btn-vedit-save-as")) $("#btn-vedit-save-as").hidden = false;
    if ($("#btn-vedit-send-creator")) $("#btn-vedit-send-creator").hidden = false;
    const hint = $("#video-edit-hint");
    if (hint) {
      hint.textContent = videoEdit.standalone
        ? "Load a video to begin. Sliders preview live on the player (play, scrub, and timeline keep working). Save writes Archives; Save As… exports MP4 (ffmpeg required). Save and Send to Creator hands the current video to Creation Studio without the original filename."
        : "Sliders preview live on the player while you play and edit the timeline. Apply rebuilds the video in Archives; Save As… exports MP4 (requires ffmpeg on PATH). Drag a paused frame (0°) to crop. Timeline starts at 0.00s. Save and Send to Creator hands the current video to Creation Studio without the original filename.";
    }
  }

  function prepareEmptyVideoEditor() {
    resetVideoEditRuntime();
    videoEdit.standalone = true;
    videoEdit.dirty = false;
    setVideoEditLoadedLabel(null);
    syncVideoEditChrome();
  }

  async function loadVideoIntoEditorFromFile() {
    const a = api();
    if (!a) return;
    beginBusy("Loading video", "Importing into Archives…", { delayMs: 0 });
    try {
      const res = await a.import_media_file("video");
      if (!res || res.cancelled) return;
      if (!res.ok) {
        showToast(res.error || "Import failed");
        return;
      }
      rememberImportedCreation(res.creation);
      await openVideoEditor(res.creation, { standalone: true });
      showToast("Video loaded into Video Editor");
    } catch (err) {
      showToast("Load failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  function nextSegId() {
    videoEdit.segSeq += 1;
    return "seg_" + videoEdit.segSeq;
  }

  function initVideoSegments(duration) {
    const dur = Math.max(0.1, Number(duration) || 0.1);
    videoEdit.segments = [{ id: nextSegId(), start: 0, end: dur }];
    videoEdit.selectedSegId = videoEdit.segments[0].id;
  }

  function segmentTotalDuration() {
    return videoEdit.segments.reduce(
      (sum, s) => sum + Math.max(0, s.end - s.start),
      0
    );
  }

  /** Edited-timeline offset (0 = left edge) for the start of segment idx. */
  function editedOffsetForSegment(idx) {
    let off = 0;
    for (let i = 0; i < idx && i < videoEdit.segments.length; i++) {
      const s = videoEdit.segments[i];
      off += Math.max(0, s.end - s.start);
    }
    return off;
  }

  /** Map source player time → position on the edited timeline (0 … total). */
  function editedTimeFromSource(sourceT) {
    const t = Number(sourceT) || 0;
    let elapsed = 0;
    for (let i = 0; i < videoEdit.segments.length; i++) {
      const seg = videoEdit.segments[i];
      const len = Math.max(0, seg.end - seg.start);
      if (t >= seg.start - 0.001 && t <= seg.end + 0.001) {
        return elapsed + Math.min(len, Math.max(0, t - seg.start));
      }
      elapsed += len;
    }
    return null;
  }

  /** Map edited timeline time → source seek time + segment index. */
  function sourceFromEditedTime(editedT) {
    let remaining = Math.max(0, Number(editedT) || 0);
    const segs = videoEdit.segments;
    if (!segs.length) return { sourceTime: 0, segIdx: 0 };
    for (let i = 0; i < segs.length; i++) {
      const seg = segs[i];
      const len = Math.max(0.05, seg.end - seg.start);
      if (remaining <= len + 0.0001 || i === segs.length - 1) {
        const into = Math.min(len, remaining);
        return { sourceTime: seg.start + into, segIdx: i };
      }
      remaining -= len;
    }
    const last = segs[segs.length - 1];
    return { sourceTime: last.end, segIdx: segs.length - 1 };
  }

  /** After cut/reorder, keep the player on a valid segment; left edge = edited 0.00. */
  function snapPlayerToEditedTimeline(preferEditedTime) {
    const player = $("#video-edit-player");
    if (!player || !videoEdit.segments.length) return;
    let edited =
      preferEditedTime != null
        ? preferEditedTime
        : editedTimeFromSource(player.currentTime);
    if (edited == null || edited < 0) edited = 0;
    const mapped = sourceFromEditedTime(edited);
    videoEdit.playSegIdx = mapped.segIdx;
    if (videoEdit.segments[mapped.segIdx]) {
      videoEdit.selectedSegId = videoEdit.segments[mapped.segIdx].id;
    }
    player.currentTime = mapped.sourceTime;
  }

  function renderVideoSegments() {
    const track = $("#vedit-timeline-track");
    const summary = $("#vedit-segments-summary");
    if (!track) return;
    track.innerHTML = "";
    videoEdit.segments.forEach((seg, idx) => {
      const len = Math.max(0.05, seg.end - seg.start);
      const editStart = editedOffsetForSegment(idx);
      const editEnd = editStart + len;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "vedit-seg" + (seg.id === videoEdit.selectedSegId ? " selected" : "");
      btn.style.flexGrow = String(len);
      btn.dataset.segId = seg.id;
      btn.title =
        "Clip " +
        (idx + 1) +
        ": " +
        editStart.toFixed(2) +
        "s → " +
        editEnd.toFixed(2) +
        "s on timeline (source " +
        seg.start.toFixed(2) +
        "–" +
        seg.end.toFixed(2) +
        ")";
      btn.textContent = idx + 1 + " · " + len.toFixed(1) + "s";
      btn.addEventListener("click", () => {
        videoEdit.selectedSegId = seg.id;
        videoEdit.playSegIdx = idx;
        const player = $("#video-edit-player");
        if (player) {
          // Seek to this clip's start on the edited timeline (leftmost = 0.00)
          player.currentTime = seg.start;
          updateVideoEditTimeLabel();
        }
        renderVideoSegments();
      });
      track.appendChild(btn);
    });
    if (summary) {
      const n = videoEdit.segments.length;
      summary.textContent =
        n +
        " segment" +
        (n === 1 ? "" : "s") +
        " · " +
        segmentTotalDuration().toFixed(1) +
        "s total (timeline starts at 0.00)";
    }
    updateVideoTimelinePlayhead();
  }

  function updateVideoTimelinePlayhead() {
    const head = $("#vedit-playhead");
    const track = $("#vedit-timeline-track");
    const player = $("#video-edit-player");
    if (!head || !track || !player || !videoEdit.segments.length) {
      if (head) head.hidden = true;
      return;
    }
    const edited = editedTimeFromSource(player.currentTime || 0);
    const total = segmentTotalDuration() || 1;
    if (edited == null) {
      head.hidden = true;
      return;
    }
    head.hidden = false;
    head.style.left =
      Math.min(100, Math.max(0, (edited / total) * 100)) + "%";
  }

  function splitVideoSegmentAtPlayhead() {
    const player = $("#video-edit-player");
    const t = player ? player.currentTime : 0;
    const minLen = 0.15;
    const idx = videoEdit.segments.findIndex(
      (s) => t > s.start + minLen && t < s.end - minLen
    );
    if (idx < 0) {
      showToast("Move the playhead inside a segment (not near an edge) to split.");
      return;
    }
    const seg = videoEdit.segments[idx];
    const left = { id: seg.id, start: seg.start, end: t };
    const right = { id: nextSegId(), start: t, end: seg.end };
    videoEdit.segments.splice(idx, 1, left, right);
    videoEdit.selectedSegId = right.id;
    videoEdit.playSegIdx = idx + 1;
    markVideoEditDirty();
    renderVideoSegments();
    updateVideoEditTimeLabel();
  }

  function deleteSelectedVideoSegment() {
    if (videoEdit.segments.length <= 1) {
      showToast("Keep at least one segment.");
      return;
    }
    const id = videoEdit.selectedSegId;
    if (!id) {
      showToast("Select a segment to delete.");
      return;
    }
    const idx = videoEdit.segments.findIndex((s) => s.id === id);
    if (idx < 0) return;
    // Keep playhead near the same edited time after the cut
    const keepEdited = editedOffsetForSegment(idx);
    videoEdit.segments.splice(idx, 1);
    const nextIdx = Math.min(idx, videoEdit.segments.length - 1);
    videoEdit.selectedSegId = videoEdit.segments[nextIdx].id;
    videoEdit.playSegIdx = nextIdx;
    markVideoEditDirty();
    snapPlayerToEditedTimeline(keepEdited);
    renderVideoSegments();
    updateVideoEditTimeLabel();
  }

  function moveSelectedVideoSegment(dir) {
    const id = videoEdit.selectedSegId;
    const idx = videoEdit.segments.findIndex((s) => s.id === id);
    if (idx < 0) return;
    const j = idx + dir;
    if (j < 0 || j >= videoEdit.segments.length) return;
    // Preserve position within the moved clip on the edited timeline
    const player = $("#video-edit-player");
    const within = player
      ? Math.max(0, (player.currentTime || 0) - videoEdit.segments[idx].start)
      : 0;
    const tmp = videoEdit.segments[idx];
    videoEdit.segments[idx] = videoEdit.segments[j];
    videoEdit.segments[j] = tmp;
    videoEdit.playSegIdx = j;
    markVideoEditDirty();
    const newEditStart = editedOffsetForSegment(j);
    snapPlayerToEditedTimeline(newEditStart + within);
    renderVideoSegments();
    updateVideoEditTimeLabel();
  }

  function clearVideoFilterPreview() {
    if (videoEdit.raf) {
      cancelAnimationFrame(videoEdit.raf);
      videoEdit.raf = 0;
    }
    videoEdit.showFilterPreview = false;
    const stage = $("#video-edit-stage");
    if (stage) stage.classList.remove("previewing-filters");
    const player = $("#video-edit-player");
    if (player) {
      player.style.filter = "";
      player.style.transform = "";
    }
    const canvas = $("#video-edit-preview-canvas");
    if (canvas) {
      canvas.hidden = true;
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
      canvas.width = 0;
      canvas.height = 0;
    }
    const box = $("#video-edit-crop-box");
    if (box) box.hidden = true;
    syncVideoEditPlayButton();
  }

  function cssFilterFromVideoEdit(filters) {
    const apiEdit = window.R98ImageEdit;
    const f =
      (apiEdit && apiEdit.normalizeFilters(filters)) ||
      filters ||
      {};
    const parts = [];
    // Match image_edit / ffmpeg approximate mapping for live preview
    const brightness = 1 + (Number(f.brightness) || 0) / 100 + ((Number(f.exposure) || 0) / 100) * 0.5;
    const contrast = 1 + (Number(f.contrast) || 0) / 100;
    parts.push("brightness(" + Math.max(0, brightness) + ")");
    parts.push("contrast(" + Math.max(0, contrast) + ")");
    if (f.grayscale) parts.push("grayscale(1)");
    const sat = Number(f.saturation);
    parts.push(
      "saturate(" +
        (Number.isFinite(sat) ? Math.max(0, sat) / 100 : 1) +
        ")"
    );
    const hue = Number(f.hueRotate) || 0;
    if (hue) parts.push("hue-rotate(" + hue + "deg)");
    const inv = Number(f.invert) || 0;
    if (inv) parts.push("invert(" + Math.max(0, Math.min(100, inv)) / 100 + ")");
    const sepia = Number(f.sepia) || 0;
    if (sepia) parts.push("sepia(" + Math.max(0, Math.min(100, sepia)) / 100 + ")");
    const blur = Number(f.blur) || 0;
    if (blur) parts.push("blur(" + Math.max(0, blur) + "px)");
    // gamma / vignette / tint / sharpen still apply on Save via ffmpeg; no clean CSS equivalent
    return parts.join(" ");
  }

  function syncVideoEditPlayButton() {
    const btn = $("#btn-vedit-play");
    const player = $("#video-edit-player");
    if (!btn) return;
    const playing = !!(player && !player.paused && !player.ended && player.readyState > 0);
    btn.textContent = playing ? "Pause" : "Play";
  }

  function toggleVideoEditPlayback() {
    const player = $("#video-edit-player");
    if (!player || !videoEdit.creationId) {
      showToast("Load a video first.");
      return;
    }
    if (player.paused || player.ended) {
      if (!videoEdit.segments.length) {
        showToast("Keep at least one segment.");
        return;
      }
      // If outside kept ranges, snap to timeline start before playing
      if (editedTimeFromSource(player.currentTime || 0) == null) {
        snapPlayerToEditedTimeline(0);
      }
      videoEdit.playSegIdx = sourceFromEditedTime(
        editedTimeFromSource(player.currentTime || 0) || 0
      ).segIdx;
      player.play().catch(() => {
        /* autoplay / decode errors surface via UI */
      });
    } else {
      player.pause();
    }
    syncVideoEditPlayButton();
  }

  function resetVideoEditRuntime() {
    clearVideoFilterPreview();
    const player = $("#video-edit-player");
    if (player) {
      player.pause();
      player.onloadedmetadata = null;
      player.ontimeupdate = null;
      player.onplay = null;
      player.onpause = null;
      player.onseeked = null;
      player.onended = null;
      player.removeAttribute("src");
      player.load();
    }
    videoEdit.creationId = null;
    videoEdit.fileUrl = null;
    videoEdit.duration = 0;
    videoEdit.crop = null;
    videoEdit.cropDrag = null;
    videoEdit.rotation = 0;
    videoEdit.segments = [];
    videoEdit.selectedSegId = null;
    videoEdit.boundarySeeking = false;
    if (window.R98ImageEdit) {
      writeVideoEditFiltersToUi(window.R98ImageEdit.DEFAULT_FILTERS);
    }
    if ($("#vedit-rotation")) $("#vedit-rotation").value = 0;
    syncVideoEditValueLabels();
    const track = $("#vedit-timeline-track");
    if (track) track.innerHTML = "";
    const summary = $("#vedit-segments-summary");
    if (summary) summary.textContent = "No segments";
    syncVideoEditPlayButton();
  }

  function closeVideoEditor() {
    closeWindow("video-edit");
  }

  async function requestCloseVideoEditor() {
    await requestCloseWindow("video-edit");
  }

  function readVideoEditFiltersFromUi() {
    return {
      brightness: Number($("#vedit-brightness") && $("#vedit-brightness").value) || 0,
      contrast: Number($("#vedit-contrast") && $("#vedit-contrast").value) || 0,
      grayscale: !!($("#vedit-grayscale") && $("#vedit-grayscale").checked),
      sharpen: !!($("#vedit-sharpen") && $("#vedit-sharpen").checked),
      saturation: Number($("#vedit-saturation") && $("#vedit-saturation").value) || 100,
      hueRotate: Number($("#vedit-hue") && $("#vedit-hue").value) || 0,
      invert: Number($("#vedit-invert") && $("#vedit-invert").value) || 0,
      sepia: Number($("#vedit-sepia") && $("#vedit-sepia").value) || 0,
      blur: Number($("#vedit-blur") && $("#vedit-blur").value) || 0,
      exposure: Number($("#vedit-exposure") && $("#vedit-exposure").value) || 0,
      gamma: Number($("#vedit-gamma") && $("#vedit-gamma").value) || 1,
      vignette: Number($("#vedit-vignette") && $("#vedit-vignette").value) || 0,
      tintRed: Number($("#vedit-tint-r") && $("#vedit-tint-r").value) || 0,
      tintGreen: Number($("#vedit-tint-g") && $("#vedit-tint-g").value) || 0,
      tintBlue: Number($("#vedit-tint-b") && $("#vedit-tint-b").value) || 0,
    };
  }

  function writeVideoEditFiltersToUi(filters) {
    const f =
      (window.R98ImageEdit && window.R98ImageEdit.normalizeFilters(filters)) ||
      filters ||
      {};
    const map = {
      "vedit-brightness": f.brightness,
      "vedit-contrast": f.contrast,
      "vedit-saturation": f.saturation,
      "vedit-hue": f.hueRotate,
      "vedit-invert": f.invert,
      "vedit-sepia": f.sepia,
      "vedit-blur": f.blur,
      "vedit-exposure": f.exposure,
      "vedit-gamma": f.gamma,
      "vedit-vignette": f.vignette,
      "vedit-tint-r": f.tintRed,
      "vedit-tint-g": f.tintGreen,
      "vedit-tint-b": f.tintBlue,
    };
    Object.keys(map).forEach((id) => {
      const el = $("#" + id);
      if (el && map[id] !== undefined) el.value = map[id];
    });
    if ($("#vedit-grayscale")) $("#vedit-grayscale").checked = !!f.grayscale;
    if ($("#vedit-sharpen")) $("#vedit-sharpen").checked = !!f.sharpen;
    syncVideoEditValueLabels();
  }

  function syncVideoEditValueLabels() {
    document.querySelectorAll("#win-video-edit .edit-val[data-for]").forEach((el) => {
      const id = el.getAttribute("data-for");
      const input = id && $("#" + id);
      if (input) el.textContent = input.value;
    });
    if ($("#vedit-rotation-label") && $("#vedit-rotation")) {
      $("#vedit-rotation-label").textContent = $("#vedit-rotation").value + "°";
    }
  }

  function findSegmentIndexAtTime(t) {
    return videoEdit.segments.findIndex(
      (s) => t >= s.start - 0.001 && t <= s.end + 0.001
    );
  }

  function syncPlaySegIdxFromTime(t) {
    const idx = findSegmentIndexAtTime(t);
    if (idx >= 0) videoEdit.playSegIdx = idx;
  }

  /**
   * Seek to an edit-order segment. Guards against stale timeupdate races while seeking,
   * and resumes playback when continuing past source EOF (HTMLVideoElement 'ended').
   */
  function seekToEditedSegment(idx, opts) {
    opts = opts || {};
    const play = opts.play !== false;
    const player = $("#video-edit-player");
    const segs = videoEdit.segments;
    if (!player || idx < 0 || idx >= segs.length) return;
    const target = Math.max(0, segs[idx].start);
    videoEdit.playSegIdx = idx;
    if (segs[idx]) videoEdit.selectedSegId = segs[idx].id;
    videoEdit.boundarySeeking = true;

    const clearGuard = () => {
      videoEdit.boundarySeeking = false;
      player.removeEventListener("seeked", onSeeked);
    };
    const onSeeked = () => clearGuard();
    player.addEventListener("seeked", onSeeked);
    window.setTimeout(clearGuard, 500);

    try {
      player.currentTime = target;
    } catch (_) {
      /* ignore */
    }
    if (play) {
      const p = player.play();
      if (p && typeof p.catch === "function") {
        p.catch(() => {
          /* autoplay / play() rejection */
        });
      }
    }
  }

  /** Jump from the current edit-order segment to the next, or stop at timeline end. */
  function continueEditedPlaybackFromBoundary() {
    const player = $("#video-edit-player");
    if (!player || !videoEdit.segments.length) return false;
    const segs = videoEdit.segments;
    let idx = videoEdit.playSegIdx;
    if (idx < 0 || idx >= segs.length) {
      idx = findSegmentIndexAtTime(player.currentTime);
      if (idx < 0) idx = 0;
      videoEdit.playSegIdx = idx;
    }
    const next = idx + 1;
    if (next >= segs.length) {
      videoEdit.playSegIdx = Math.max(0, segs.length - 1);
      try {
        player.pause();
      } catch (_) {
        /* ignore */
      }
      scheduleVideoFilterPreview();
      return false;
    }
    seekToEditedSegment(next, { play: true });
    return true;
  }

  /** During playback, stay inside segments in edit order (skip deletes / honor reorder). */
  function advanceEditedPlayback() {
    const player = $("#video-edit-player");
    if (!player || !videoEdit.segments.length) return;
    if (videoEdit.boundarySeeking) return;
    // When a segment ends at source EOF, the element pauses via 'ended' before
    // the next timeupdate — still allow advancing in that case.
    if (player.paused && !player.ended) return;

    const segs = videoEdit.segments;
    let idx = videoEdit.playSegIdx;
    if (idx < 0 || idx >= segs.length) {
      idx = findSegmentIndexAtTime(player.currentTime);
      if (idx < 0) idx = 0;
      videoEdit.playSegIdx = idx;
    }
    const seg = segs[idx];
    const t = player.currentTime;
    const mediaDur = Number(player.duration);
    const nearMediaEnd =
      Number.isFinite(mediaDur) && mediaDur > 0 && t >= mediaDur - 0.15;

    if (!player.ended && t < seg.start - 0.02) {
      seekToEditedSegment(idx, { play: !player.paused });
      return;
    }

    // Only treat as segment-complete when time is actually in/near this segment
    // (avoids stale currentTime after a seek to an earlier source range).
    const inOrPastSeg =
      player.ended ||
      nearMediaEnd ||
      (t >= seg.start - 0.05 && t >= seg.end - 0.05);
    if (inOrPastSeg && (player.ended || nearMediaEnd || t >= seg.end - 0.04)) {
      continueEditedPlaybackFromBoundary();
    }
  }

  function onVideoEditEnded() {
    // Source EOF while more edit-order clips remain (e.g. end clip moved first).
    if (videoEdit.boundarySeeking) return;
    continueEditedPlaybackFromBoundary();
    updateVideoEditTimeLabel();
  }

  function updateVideoEditTimeLabel() {
    const player = $("#video-edit-player");
    if (!player || !$("#vedit-time-label")) return;
    advanceEditedPlayback();
    const editedDur = segmentTotalDuration();
    let edited = editedTimeFromSource(player.currentTime || 0);
    if (edited == null) {
      // Outside kept ranges (e.g. just deleted) — snap to timeline start
      snapPlayerToEditedTimeline(0);
      edited = editedTimeFromSource(player.currentTime || 0) || 0;
    }
    $("#vedit-time-label").textContent =
      edited.toFixed(2) + "s / " + editedDur.toFixed(2) + "s";
    if ($("#vedit-scrub") && editedDur > 0) {
      $("#vedit-scrub").value = String(
        Math.round((edited / editedDur) * 1000)
      );
    }
    updateVideoTimelinePlayhead();
  }

  function scheduleVideoFilterPreview() {
    if (videoEdit.raf) cancelAnimationFrame(videoEdit.raf);
    videoEdit.raf = requestAnimationFrame(() => {
      videoEdit.raf = 0;
      renderVideoFilterPreview();
    });
  }

  function renderVideoFilterPreview() {
    const player = $("#video-edit-player");
    const canvas = $("#video-edit-preview-canvas");
    const stage = $("#video-edit-stage");
    if (!player || !stage || !videoEdit.creationId) return;

    // Always keep the native player visible (size + play controls). Preview via CSS.
    if (canvas) canvas.hidden = true;
    if (stage) stage.classList.remove("previewing-filters");

    const filters = readVideoEditFiltersFromUi();
    videoEdit.rotation = Number($("#vedit-rotation") && $("#vedit-rotation").value) || 0;
    const cssFilter = cssFilterFromVideoEdit(filters);
    player.style.filter = cssFilter || "";
    player.style.transform = videoEdit.rotation
      ? "rotate(" + videoEdit.rotation + "deg)"
      : "";
    videoEdit.showFilterPreview = !!(cssFilter || videoEdit.rotation || videoEdit.crop);
    updateVideoCropOverlay();
    syncVideoEditPlayButton();
  }

  function updateVideoCropOverlay() {
    const box = $("#video-edit-crop-box");
    const stage = $("#video-edit-stage");
    const player = $("#video-edit-player");
    if (!box || !stage) return;
    const crop = videoEdit.crop;
    if (!crop || videoEdit.rotation) {
      box.hidden = true;
      return;
    }
    const target = player;
    if (!target) {
      box.hidden = true;
      return;
    }
    const targetRect = target.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const scaleX = targetRect.width;
    const scaleY = targetRect.height;
    box.hidden = false;
    box.style.left =
      targetRect.left - stageRect.left + stage.scrollLeft + crop.x * scaleX + "px";
    box.style.top =
      targetRect.top - stageRect.top + stage.scrollTop + crop.y * scaleY + "px";
    box.style.width = Math.max(1, crop.w * scaleX) + "px";
    box.style.height = Math.max(1, crop.h * scaleY) + "px";
  }

  async function openVideoEditor(creation, opts) {
    opts = opts || {};
    if (!creation || creationModality(creation) !== "video") {
      showToast("Edit is available for video creations.");
      return false;
    }
    const a = api();
    if (!a) {
      showToast("Python bridge required to edit videos.");
      return false;
    }
    const status = await a.ffmpeg_status();
    if (!status || !status.ok) {
      showToast(
        (status && status.error) ||
          "ffmpeg not found. Install ffmpeg and add it to PATH."
      );
      return false;
    }

    const payload = await a.get_media_payload(creation);
    if (!payload || !payload.ok || !payload.fileUrl) {
      showToast((payload && payload.error) || "Could not load video.");
      return false;
    }

    let info = { duration: 0 };
    try {
      info = await a.get_video_info(creation.id);
    } catch (_) {
      /* ignore */
    }

    videoEdit.creationId = creation.id;
    videoEdit.standalone =
      typeof opts.standalone === "boolean" ? opts.standalone : true;
    videoEdit.fileUrl = payload.fileUrl;
    videoEdit.duration = Number(info.duration) || 0;
    videoEdit.crop = null;
    videoEdit.cropDrag = null;
    videoEdit.rotation = 0;
    videoEdit.dirty = false;
    clearVideoFilterPreview();
    if ($("#vedit-rotation")) $("#vedit-rotation").value = 0;
    writeVideoEditFiltersToUi(
      (window.R98ImageEdit && window.R98ImageEdit.DEFAULT_FILTERS) || {}
    );
    initVideoSegments(videoEdit.duration || 0.1);

    const player = $("#video-edit-player");
    if (player) {
      player.pause();
      player.src = payload.fileUrl;
      player.onloadedmetadata = () => {
        if (!videoEdit.duration && player.duration) {
          videoEdit.duration = player.duration;
          initVideoSegments(player.duration);
          renderVideoSegments();
        }
        updateVideoEditTimeLabel();
        scheduleVideoFilterPreview();
        syncVideoEditPlayButton();
      };
      player.ontimeupdate = () => updateVideoEditTimeLabel();
      player.onplay = () => syncVideoEditPlayButton();
      player.onpause = () => {
        syncVideoEditPlayButton();
        scheduleVideoFilterPreview();
      };
      player.onseeked = () => scheduleVideoFilterPreview();
      player.onended = () => {
        syncVideoEditPlayButton();
        onVideoEditEnded();
      };
    }

    renderVideoSegments();
    setVideoEditLoadedLabel(creation);
    syncVideoEditChrome();
    openWindow("video-edit");
    scheduleVideoFilterPreview();
    return true;
  }

  function resetVideoEditor() {
    writeVideoEditFiltersToUi(
      (window.R98ImageEdit && window.R98ImageEdit.DEFAULT_FILTERS) || {}
    );
    videoEdit.crop = null;
    videoEdit.rotation = 0;
    videoEdit.dirty = false;
    if ($("#vedit-rotation")) $("#vedit-rotation").value = 0;
    initVideoSegments(videoEdit.duration || 0.1);
    syncVideoEditValueLabels();
    clearVideoFilterPreview();
    renderVideoSegments();
    scheduleVideoFilterPreview();
  }

  function buildVideoEditOps() {
    const filters = readVideoEditFiltersFromUi();
    const rotation = Number($("#vedit-rotation") && $("#vedit-rotation").value) || 0;
    const ops = {
      filters,
      rotation,
      segments: videoEdit.segments.map((s) => ({
        start: s.start,
        end: s.end,
      })),
    };
    if (videoEdit.crop) {
      ops.crop = {
        x: videoEdit.crop.x,
        y: videoEdit.crop.y,
        w: videoEdit.crop.w,
        h: videoEdit.crop.h,
        normalized: true,
      };
    }
    return ops;
  }

  async function persistEditedVideoToArchives() {
    if (!videoEdit.creationId) {
      showToast("Load a video first.");
      return null;
    }
    if (!videoEdit.segments.length) {
      showToast("Keep at least one segment.");
      return null;
    }
    const a = api();
    if (!a) return null;
    const res = await a.edit_video(videoEdit.creationId, buildVideoEditOps());
    if (!res || !res.ok) {
      showToast((res && res.error) || "Failed to save edited video");
      return null;
    }
    const saved = res.creation;
    state.creations = [saved].concat(
      state.creations.filter((c) => c.id !== saved.id)
    );
    state.active = saved;
    renderArchives();
    return saved;
  }

  async function applyVideoEditor() {
    beginBusy("Saving video edit", "Cutting and assembling segments…", {
      delayMs: 0,
    });
    try {
      const saved = await persistEditedVideoToArchives();
      if (!saved) return;
      renderDocument(saved);
      closeVideoEditor();
      showToast("Video edit applied");
    } catch (err) {
      showToast("Video edit failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveVideoEditor() {
    const keepStandalone = videoEdit.standalone;
    beginBusy("Saving video", "Cutting and assembling segments…", {
      delayMs: 0,
    });
    try {
      const saved = await persistEditedVideoToArchives();
      if (!saved) return;
      await openVideoEditor(saved, { standalone: keepStandalone });
      showToast("Video saved");
    } catch (err) {
      showToast("Save failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveVideoEditorAndSendToCreator() {
    const keepStandalone = videoEdit.standalone;
    beginBusy("Sending to Creator", "Saving the edited video…", {
      delayMs: 0,
    });
    try {
      const saved = await persistEditedVideoToArchives();
      if (!saved) return;
      await openVideoEditor(saved, { standalone: keepStandalone });
      await sendCreationToCreator(saved);
    } catch (err) {
      showToast("Send to Creator failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  async function saveVideoEditorAs() {
    if (!videoEdit.creationId) {
      showToast("Load a video first.");
      return;
    }
    if (!videoEdit.segments.length) {
      showToast("Keep at least one segment.");
      return;
    }
    const a = api();
    if (!a) return;
    beginBusy("Save As", "Rendering edited video…", { delayMs: 0 });
    try {
      const res = await a.export_edited_video(
        videoEdit.creationId,
        buildVideoEditOps()
      );
      if (res && res.cancelled) return;
      if (!res || !res.ok) {
        showToast((res && res.error) || "Save As failed");
        return;
      }
      showToast("Saved to " + (res.path || "file"));
    } catch (err) {
      showToast("Save As failed: " + err);
    } finally {
      endBusy("Ready");
    }
  }

  function setupVideoEditCropInteraction() {
    const stage = $("#video-edit-stage");
    if (!stage) return;

    stage.addEventListener("pointerdown", (e) => {
      if (!videoEdit.creationId) return;
      if (videoEdit.rotation) {
        showToast("Set rotation to 0° before drawing a crop.");
        return;
      }
      const player = $("#video-edit-player");
      if (player && !player.paused) player.pause();
      const target = player;
      if (!target) return;
      const rect = target.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) return;
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      if (x < 0 || y < 0 || x > 1 || y > 1) return;
      videoEdit.cropDrag = { x0: x, y0: y, pointerId: e.pointerId };
      stage.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    stage.addEventListener("pointermove", (e) => {
      if (!videoEdit.cropDrag || e.pointerId !== videoEdit.cropDrag.pointerId) return;
      const player = $("#video-edit-player");
      const target = player;
      if (!target) return;
      const rect = target.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
      const x0 = videoEdit.cropDrag.x0;
      const y0 = videoEdit.cropDrag.y0;
      videoEdit.crop = {
        x: Math.min(x0, x),
        y: Math.min(y0, y),
        w: Math.max(0.01, Math.abs(x - x0)),
        h: Math.max(0.01, Math.abs(y - y0)),
        normalized: true,
      };
      updateVideoCropOverlay();
    });

    const endDrag = (e) => {
      if (!videoEdit.cropDrag || e.pointerId !== videoEdit.cropDrag.pointerId) return;
      videoEdit.cropDrag = null;
      try {
        stage.releasePointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      if (videoEdit.crop) markVideoEditDirty();
      scheduleVideoFilterPreview();
    };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
  }

  function wireVideoEditEvents() {
    if ($("#btn-edit-video")) {
      $("#btn-edit-video").addEventListener("click", () => {
        void openVideoEditor(state.active, { standalone: false });
      });
    }
    const sliderIds = [
      "vedit-brightness",
      "vedit-contrast",
      "vedit-saturation",
      "vedit-hue",
      "vedit-invert",
      "vedit-sepia",
      "vedit-blur",
      "vedit-exposure",
      "vedit-gamma",
      "vedit-vignette",
      "vedit-tint-r",
      "vedit-tint-g",
      "vedit-tint-b",
      "vedit-rotation",
    ];
    sliderIds.forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", () => {
        markVideoEditDirty();
        syncVideoEditValueLabels();
        scheduleVideoFilterPreview();
      });
      el.addEventListener("change", () => {
        markVideoEditDirty();
        syncVideoEditValueLabels();
        scheduleVideoFilterPreview();
      });
    });
    ["vedit-grayscale", "vedit-sharpen"].forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("change", () => {
        markVideoEditDirty();
        scheduleVideoFilterPreview();
      });
    });

    if ($("#vedit-scrub")) {
      $("#vedit-scrub").addEventListener("input", () => {
        const player = $("#video-edit-player");
        const editedDur = segmentTotalDuration();
        if (!player || editedDur <= 0) return;
        const edited =
          (Number($("#vedit-scrub").value) / 1000) * editedDur;
        const mapped = sourceFromEditedTime(edited);
        videoEdit.playSegIdx = mapped.segIdx;
        player.currentTime = mapped.sourceTime;
        updateVideoEditTimeLabel();
      });
    }
    if ($("#btn-vedit-play")) {
      $("#btn-vedit-play").addEventListener("click", () => {
        toggleVideoEditPlayback();
      });
    }
    if ($("#btn-vedit-rewind")) {
      $("#btn-vedit-rewind").addEventListener("click", () => {
        const player = $("#video-edit-player");
        if (!player || !videoEdit.segments.length) return;
        player.pause();
        snapPlayerToEditedTimeline(0);
        updateVideoEditTimeLabel();
        scheduleVideoFilterPreview();
        syncVideoEditPlayButton();
      });
    }
    if ($("#btn-vedit-split")) {
      $("#btn-vedit-split").addEventListener("click", () =>
        splitVideoSegmentAtPlayhead()
      );
    }
    if ($("#btn-vedit-seg-delete")) {
      $("#btn-vedit-seg-delete").addEventListener("click", () =>
        deleteSelectedVideoSegment()
      );
    }
    if ($("#btn-vedit-seg-left")) {
      $("#btn-vedit-seg-left").addEventListener("click", () =>
        moveSelectedVideoSegment(-1)
      );
    }
    if ($("#btn-vedit-seg-right")) {
      $("#btn-vedit-seg-right").addEventListener("click", () =>
        moveSelectedVideoSegment(1)
      );
    }
    if ($("#btn-vedit-rot-cw")) {
      $("#btn-vedit-rot-cw").addEventListener("click", () => {
        const cur = Number($("#vedit-rotation").value) || 0;
        $("#vedit-rotation").value = String((cur + 90) % 360);
        markVideoEditDirty();
        syncVideoEditValueLabels();
        scheduleVideoFilterPreview();
      });
    }
    if ($("#btn-vedit-rot-ccw")) {
      $("#btn-vedit-rot-ccw").addEventListener("click", () => {
        const cur = Number($("#vedit-rotation").value) || 0;
        $("#vedit-rotation").value = String((cur + 270) % 360);
        markVideoEditDirty();
        syncVideoEditValueLabels();
        scheduleVideoFilterPreview();
      });
    }
    if ($("#btn-vedit-crop-clear")) {
      $("#btn-vedit-crop-clear").addEventListener("click", () => {
        if (videoEdit.crop) markVideoEditDirty();
        videoEdit.crop = null;
        scheduleVideoFilterPreview();
      });
    }
    if ($("#btn-vedit-reset")) {
      $("#btn-vedit-reset").addEventListener("click", () => {
        resetVideoEditor();
      });
    }
    if ($("#btn-vedit-cancel")) {
      $("#btn-vedit-cancel").addEventListener("click", () =>
        requestCloseVideoEditor()
      );
    }
    if ($("#btn-vedit-apply")) {
      $("#btn-vedit-apply").addEventListener("click", () => applyVideoEditor());
    }
    if ($("#btn-vedit-save")) {
      $("#btn-vedit-save").addEventListener("click", () => saveVideoEditor());
    }
    if ($("#btn-vedit-save-as")) {
      $("#btn-vedit-save-as").addEventListener("click", () => saveVideoEditorAs());
    }
    if ($("#btn-vedit-send-creator")) {
      $("#btn-vedit-send-creator").addEventListener("click", () => {
        saveVideoEditorAndSendToCreator();
      });
    }
    setupVideoEditCropInteraction();
  }

  function wireStudioBasisSplitter() {
    const splitter = $("#studio-basis-splitter");
    if (!splitter || splitter.dataset.wired === "1") return;
    splitter.dataset.wired = "1";
    let drag = null;

    splitter.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || splitter.hidden) return;
      const panel = $("#studio-basis-panel");
      const layout = $("#studio-layout");
      if (!panel || !layout || panel.hidden) return;
      const scale = Number(state.uiScale) || 1;
      drag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startW: panel.getBoundingClientRect().width / scale,
        scale,
      };
      splitter.classList.add("is-dragging");
      try {
        splitter.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      e.preventDefault();
    });

    splitter.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.pointerId) return;
      const delta = (drag.startX - e.clientX) / drag.scale;
      applyStudioBasisWidth(drag.startW + delta);
    });

    const endDrag = (e) => {
      if (!drag) return;
      if (e && e.pointerId != null && e.pointerId !== drag.pointerId) return;
      try {
        splitter.releasePointerCapture(drag.pointerId);
      } catch (_) {
        /* ignore */
      }
      splitter.classList.remove("is-dragging");
      drag = null;
      persistStudioBasisWidthSoon();
    };

    splitter.addEventListener("pointerup", endDrag);
    splitter.addEventListener("pointercancel", endDrag);
    splitter.addEventListener("dblclick", () => {
      applyStudioBasisWidth(280, { persist: true });
    });
    splitter.addEventListener("keydown", (e) => {
      if (splitter.hidden) return;
      const step = e.shiftKey ? 40 : 16;
      if (e.key === "ArrowLeft") {
        applyStudioBasisWidth(state.studioBasisWidth + step, { persist: true });
        e.preventDefault();
      } else if (e.key === "ArrowRight") {
        applyStudioBasisWidth(state.studioBasisWidth - step, { persist: true });
        e.preventDefault();
      } else if (e.key === "Home") {
        applyStudioBasisWidth(160, { persist: true });
        e.preventDefault();
      } else if (e.key === "End") {
        applyStudioBasisWidth(1200, { persist: true });
        e.preventDefault();
      }
    });
  }

  function wireEvents() {
    if ($("#screen-select")) {
      $("#screen-select").addEventListener("change", () => {
        showScreen($("#screen-select").value);
      });
    }

    if ($("#menu-app-btn")) {
      $("#menu-app-btn").addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleAppMenu();
      });
    }
    wireStudioBasisSplitter();

    document.addEventListener("click", (e) => {
      if (e.target.closest(".app-menu")) {
        if (e.target.closest(".app-menu-panel [role='menuitem']")) closeAppMenus();
        return;
      }
      closeAppMenus();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAppMenus();
    });

    document.addEventListener("focusin", (e) => {
      const el = e.target;
      if (isImeField(el)) {
        attachIme(el);
        return;
      }
      if (ime.target) detachIme();
    });

    window.addEventListener("blur", () => detachIme({ resume: true }));
    window.addEventListener("focus", () => {
      const field = ime.resume;
      ime.resume = null;
      if (!field || !document.body.contains(field) || field.disabled || field.readOnly) {
        return;
      }
      const win = field.closest(".app-window");
      if (!win || win.dataset.window !== state.focused) return;
      attachIme(field);
    });
    document.addEventListener(
      "scroll",
      () => {
        if (ime.target) syncImeCaret();
      },
      true
    );

    $("#create-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await startGeneration();
    });

    $("#btn-generate").addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await startGeneration();
    });

    if ($("#btn-studio-load-text")) {
      $("#btn-studio-load-text").addEventListener("click", () => studioLoadTextFile());
    }
    if ($("#btn-studio-load-image")) {
      $("#btn-studio-load-image").addEventListener("click", () =>
        studioLoadMediaFile("image")
      );
    }
    if ($("#btn-studio-load-video")) {
      $("#btn-studio-load-video").addEventListener("click", () =>
        studioLoadMediaFile("video")
      );
    }
    if ($("#studio-saved-prompt")) {
      $("#studio-saved-prompt").addEventListener("change", () =>
        onStudioSavedPromptChange()
      );
    }
    ["studio-prompt", "studio-search", "studio-tool-use"].forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      ["keyup", "click", "select", "input", "blur"].forEach((evt) => {
        el.addEventListener(evt, () => rememberStudioCaret(el));
      });
    });
    if ($("#prompt-editor-list")) {
      $("#prompt-editor-list").addEventListener("change", () =>
        onPromptEditorListChange()
      );
    }
    if ($("#btn-prompt-add")) {
      $("#btn-prompt-add").addEventListener("click", () => startNewPrompt());
    }
    if ($("#btn-prompt-edit")) {
      $("#btn-prompt-edit").addEventListener("click", () => editSelectedPrompt());
    }
    if ($("#btn-prompt-save")) {
      $("#btn-prompt-save").addEventListener("click", () => saveCurrentPrompt());
    }
    if ($("#btn-prompt-delete")) {
      $("#btn-prompt-delete").addEventListener("click", () => deleteCurrentPrompt());
    }
    if ($("#btn-studio-clear-basis")) {
      $("#btn-studio-clear-basis").addEventListener("click", () => {
        clearStudioBasis();
        showToast("Media basis cleared");
      });
    }
    if ($("#btn-viewer-open")) {
      $("#btn-viewer-open").addEventListener("click", (e) => {
        e.preventDefault();
        viewerOpenFile();
      });
    }
    if ($("#btn-use-basis")) {
      $("#btn-use-basis").addEventListener("click", () =>
        useCreationAsBasis(state.active)
      );
    }
    if ($("#btn-viewer-send-creator")) {
      $("#btn-viewer-send-creator").addEventListener("click", () =>
        sendCreationToCreator(state.active)
      );
    }
    if ($("#btn-iedit-load")) {
      $("#btn-iedit-load").addEventListener("click", () =>
        loadImageIntoEditorFromFile()
      );
    }
    if ($("#btn-vedit-load")) {
      $("#btn-vedit-load").addEventListener("click", () =>
        loadVideoIntoEditorFromFile()
      );
    }

    if ($("#busy-cancel")) {
      $("#busy-cancel").addEventListener("click", () => {
        requestCancelBusyJob();
      });
    }

    $("#archive-search").addEventListener("input", renderArchives);
    document.querySelectorAll(".arch-sort-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        setArchiveSort(btn.getAttribute("data-sort"));
      });
    });

    $("#btn-export-all").addEventListener("click", async () => {
      const a = api();
      if (!a) return;
      const json = await a.export_creations_json();
      const date = new Date().toISOString().slice(0, 10);
      await a.save_file_dialog("synthetic_text_extruder_archives_" + date + ".json", json);
    });

    $("#btn-import").addEventListener("click", async () => {
      const a = api();
      if (!a) return;
      const res = await a.open_json_import();
      if (res.ok) {
        state.creations = res.creations;
        renderArchives();
        showToast("Imported " + res.imported + " item(s)");
      } else if (!res.cancelled) {
        showToast(res.error || "Import failed");
      }
    });

    if ($("#btn-import-text")) {
      $("#btn-import-text").addEventListener("click", () => archivesImportText());
    }
    if ($("#btn-import-image")) {
      $("#btn-import-image").addEventListener("click", () =>
        archivesImportMedia("image")
      );
    }
    if ($("#btn-import-video")) {
      $("#btn-import-video").addEventListener("click", () =>
        archivesImportMedia("video")
      );
    }
    if ($("#btn-import-audio")) {
      $("#btn-import-audio").addEventListener("click", () =>
        archivesImportMedia("audio")
      );
    }

    $("#btn-export-txt").addEventListener("click", async () => {
      if (!state.active) return;
      const modality = creationModality(state.active);
      const extracted = getExtractedText(state.active);
      if (modality !== "text" && !extracted && !(modality === "audio" && creationLyrics(state.active))) {
        showToast(
          "Prompt Studio to extract the text or transcribe first, or open a text creation."
        );
        return;
      }
      const a = api();
      if (!a) return;
      try {
        const txt = await a.export_creation_txt(state.active);
        const suffix =
          modality === "video"
            ? "_transcript.txt"
            : modality === "image"
              ? "_ocr.txt"
              : modality === "audio"
                ? "_lyrics.txt"
                : ".txt";
        const name =
          modality === "text"
            ? exportBaseName(state.active) + ".txt"
            : exportBaseName(state.active) + suffix;
        await a.save_file_dialog(name, txt);
      } catch (err) {
        showToast(String(err));
      }
    });

    const docCanvas = $("#doc-canvas");
    if (docCanvas) {
      docCanvas.addEventListener("click", async (e) => {
        const copyExtracted =
          e.target && e.target.closest && e.target.closest("#btn-copy-extracted");
        const copyLayout =
          e.target && e.target.closest && e.target.closest("#btn-copy-layout");
        if (!copyExtracted && !copyLayout) return;
        try {
          if (copyLayout) {
            const layout = getExtractedLayout(state.active);
            if (!layout) return;
            await navigator.clipboard.writeText(JSON.stringify(layout, null, 2));
            showToast("Copied layout JSON.");
            return;
          }
          const text = getExtractedText(state.active);
          if (!text) return;
          await navigator.clipboard.writeText(text);
          showToast("Copied extracted text.");
        } catch (_) {
          showToast("Could not copy to clipboard.");
        }
      });
    }

    $("#btn-export-json").addEventListener("click", async () => {
      if (!state.active) return;
      const a = api();
      if (!a) return;
      const name = exportBaseName(state.active) + ".json";
      const payload = exportCreationMetadata(state.active);
      await a.save_file_dialog(name, JSON.stringify(payload, null, 2));
    });

    $("#btn-export-png").addEventListener("click", () => {
      exportDocumentImage("png");
    });

    $("#btn-export-pdf").addEventListener("click", () => {
      exportDocumentImage("pdf");
    });

    if ($("#btn-export-media")) {
      $("#btn-export-media").addEventListener("click", async () => {
        if (!state.active) return;
        const a = api();
        if (!a) return;
        const res = await a.export_creation_media(state.active);
        if (res.ok) {
          showToast(
            creationModality(state.active) === "video"
              ? "Saved MP4"
              : creationModality(state.active) === "audio"
                ? "Saved audio"
                : "Saved media file"
          );
        } else if (!res.cancelled) {
          showToast(res.error || "Media save failed");
        }
      });
    }

    $("#btn-voice").addEventListener("click", () => {
      toggleVoiceReader();
    });

    document.querySelectorAll(".viewer-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        setViewerTab(btn.getAttribute("data-tab"));
      });
    });

    ["hf-text-model", "hf-image-model", "hf-video-model"].forEach((id) => {
      const el = $("#" + id);
      if (!el) return;
      el.addEventListener("change", () => {
        updateStudioBackendLabel({
          config: {
            backend: {
              provider:
                ($("#backend-provider") && $("#backend-provider").value) ||
                "huggingface",
            },
            gemini: currentGeminiUiConfig(),
            openrouter: currentOpenRouterUiConfig(),
            huggingface: currentHfUiConfig(),
          },
        });
      });
    });

    [
      "gemini-text-model",
      "gemini-image-model",
      "gemini-video-model",
      "gemini-audio-model",
    ].forEach(
      (id) => {
        const el = $("#" + id);
        if (!el) return;
        el.addEventListener("change", () => {
          updateStudioBackendLabel({
            config: {
              backend: { provider: "gemini" },
              gemini: currentGeminiUiConfig(),
            },
          });
        });
      }
    );

    if ($("#gemini-search")) {
      $("#gemini-search").addEventListener("change", () => {
        syncGeminiTwoPassAvailability();
        syncGeminiSearchEnrichmentAvailability();
        syncStudioToolsPanel();
      });
    }

    if ($("#gemini-use-tools")) {
      $("#gemini-use-tools").addEventListener("change", () => {
        syncGeminiToolsAvailability();
      });
    }

    if ($("#studio-enable-tools")) {
      $("#studio-enable-tools").addEventListener("change", () => {
        const enabled = studioToolsEnabled();
        if (enabled) {
          const prompt = getStudioPrompt();
          if (prompt && !getStudioToolUse()) {
            setStudioToolUse(prompt);
          }
        } else {
          const toolUse = getStudioToolUse();
          if (toolUse && !getStudioPrompt()) {
            setStudioPrompt(toolUse);
          }
        }
        syncStudioToolsPanel();
      });
    }

    if ($("#btn-studio-add-tool")) {
      $("#btn-studio-add-tool").addEventListener("click", async () => {
        if (!studioToolsEnabled()) {
          showToast("Turn on Enable Tools in Creation Studio first.");
          return;
        }
        const alias = await showAddToolDialog();
        if (!alias) return;
        if (!(state.studioTools || []).includes(alias)) {
          state.studioTools = (state.studioTools || []).concat([alias]);
          renderStudioToolsList();
        }
      });
    }

    geminiApiKeyInputs().forEach((input) => {
      input.addEventListener("input", () => syncGeminiApiKeyInputs(input));
    });
    ["btn-save-gemini-key", "btn-save-gemini-key-google"].forEach((id) => {
      const btn = $("#" + id);
      if (!btn) return;
      btn.addEventListener("click", () => {
        void saveGeminiApiKeyFromControls();
      });
    });

    if ($("#btn-gemini-refresh-models")) {
      $("#btn-gemini-refresh-models").addEventListener("click", async () => {
        await persistSettingsNow({ applyDisplay: false });
        void refreshGeminiModelsForControlPanel();
      });
    }

    if ($("#btn-pick-media-folder")) {
      $("#btn-pick-media-folder").addEventListener("click", async () => {
        const a = api();
        if (!a) {
          showToast("Python bridge not ready.");
          return;
        }
        const res = await a.pick_media_folder();
        if (res.cancelled) return;
        if (!res.ok) {
          showToast(res.error || "Could not pick a media folder");
          return;
        }
        if ($("#media-folder-path")) {
          $("#media-folder-path").value = res.path || "media";
        }
        void persistSettingsNow({ applyDisplay: false });
      });
    }

    if ($("#btn-reset-media-folder")) {
      $("#btn-reset-media-folder").addEventListener("click", () => {
        if ($("#media-folder-path")) {
          $("#media-folder-path").value = "media";
        }
        void persistSettingsNow({ applyDisplay: false });
      });
    }

    if ($("#btn-google-workspace-pick-credentials")) {
      $("#btn-google-workspace-pick-credentials").addEventListener("click", async () => {
        const a = api();
        if (!a) {
          showToast("Python bridge not ready.");
          return;
        }
        const picker = a.pick_google_workspace_credentials || a.pick_gmail_credentials;
        const res = await picker.call(a);
        if (res.cancelled) return;
        if (!res.ok) {
          showToast(res.error || "Could not pick OAuth client JSON");
          return;
        }
        if ($("#google-workspace-credentials-path")) {
          $("#google-workspace-credentials-path").value = res.path || "";
        }
        updateGoogleWorkspaceAuthIndicators();
        void persistSettingsNow({ applyDisplay: false });
      });
    }

    if ($("#btn-google-workspace-connect")) {
      $("#btn-google-workspace-connect").addEventListener("click", async () => {
        const a = api();
        if (!a) {
          showToast("Python bridge not ready.");
          return;
        }
        const path =
          ($("#google-workspace-credentials-path") &&
            $("#google-workspace-credentials-path").value.trim()) ||
          "";
        if (!path) {
          showToast("Pick OAuth client JSON before connecting.");
          return;
        }
        const saved =
          (state.config &&
            ((state.config.google_workspace &&
              state.config.google_workspace.credentials_path) ||
              (state.config.gmail && state.config.gmail.credentials_path))) ||
          "";
        if (saved !== path) {
          await persistSettingsNow({ applyDisplay: false });
        }
        const authorize = a.authorize_google_workspace || a.authorize_gmail;
        const res = await authorize.call(a);
        if (!res.ok) {
          showToast(res.error || "Google Workspace authorization failed");
          return;
        }
        showToast(res.message || "Google Workspace connected.");
        await refreshGoogleWorkspaceAuthStatus();
      });
    }

    if ($("#btn-gemini-recommend-models")) {
      $("#btn-gemini-recommend-models").addEventListener("click", async () => {
        await persistSettingsNow({ applyDisplay: false });
        void runRecommendModels("gemini");
      });
    }

    document.querySelectorAll(".settings-nav-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        setSettingsPage(btn.getAttribute("data-settings-page"));
      });
    });

    $("#opt-sound").addEventListener("change", () => {
      state.soundEnabled = $("#opt-sound").checked;
      if ($("#opt-sound-volume")) {
        $("#opt-sound-volume").disabled = !state.soundEnabled;
      }
      if (state.soundEnabled) playUiSound("notify");
    });
    let _soundVolPreviewTimer = null;
    if ($("#opt-sound-volume")) {
      $("#opt-sound-volume").disabled = !state.soundEnabled;
      const onVolumeInput = () => {
        applySoundVolume($("#opt-sound-volume").value);
        clearTimeout(_soundVolPreviewTimer);
        _soundVolPreviewTimer = setTimeout(() => {
          playUiSound("notify");
        }, 90);
      };
      $("#opt-sound-volume").addEventListener("input", onVolumeInput);
      $("#opt-sound-volume").addEventListener("change", () => {
        // Final settle after drag; input debounce may already have previewed.
        clearTimeout(_soundVolPreviewTimer);
        applySoundVolume($("#opt-sound-volume").value, { preview: true });
      });
    }
    if ($("#app-theme")) {
      $("#app-theme").addEventListener("change", () => {
        applyAppTheme($("#app-theme").value);
      });
    }
    if ($("#ui-font")) {
      $("#ui-font").addEventListener("change", () => {
        applyUiFont($("#ui-font").value);
      });
    }
    if ($("#ui-font-size")) {
      $("#ui-font-size").addEventListener("change", () => {
        applyUiFontSize($("#ui-font-size").value);
      });
    }

    wireImageEditEvents();
    wireVideoEditEvents();
  }

  async function init() {
    // Catalogs first — never depend on Python for dropdowns
    fillCatalogs(null);
    fillAppThemeSelect();
    fillUiFontSelect();
    fillUiFontSizeSelect();
    applyUiFont(state.uiFont || "inter");
    applyUiFontSize(state.uiFontSize || UI_FONT_SIZE_DEFAULT);
    applyAppTheme(state.appTheme || "light");
    syncControlPanelWidth();
    adoptWindowsIntoLayer();
    ensureImeBridge();
    wireEvents();
    setSettingsPage("models", { skipSave: true });
    showScreen("form");
    window.addEventListener("resize", () => {
      syncDesktopScrollExtent();
      const basisPanel = $("#studio-basis-panel");
      if (basisPanel && !basisPanel.hidden) {
        applyStudioBasisWidth(state.studioBasisWidth);
      }
    });

    const a = await waitForApi();
    if (!a) {
      showToast(
        "Running without Python bridge — open via: python -m synthetic_text_extruder"
      );
      return;
    }

    try {
      const boot = await a.get_bootstrap();
      state.config = boot.config;
      if (Array.isArray(boot.geminiTools)) {
        state.geminiToolsCatalog = boot.geminiTools.slice();
      }
      state.creations = boot.creations || [];
      applySavedPrompts(boot.prompts || []);
      fillCatalogs(boot);
      fillControlPanel(boot);
      renderArchives();
      // Do not auto-open Viewer/Archives on launch — user opens them explicitly
      renderTaskbar();
      syncStudioToolsPanel();
    } catch (err) {
      console.error(err);
      showToast("Bootstrap failed: " + err);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
