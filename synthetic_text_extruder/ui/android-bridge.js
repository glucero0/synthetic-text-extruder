/*
 * Android WebView & Foldable Bridge.
 *
 * No-op on desktop pywebview. On Android (when window.__STE_ANDROID_TOKEN__ is
 * injected by android_server.py), provides:
 *  - window.pywebview.api Proxy -> POST /api/rpc/<method>
 *  - Android file picker / OAuth JSON import / native Share Sheet hooks
 *  - Foldable posture sync (compact / expanded / tabletop + hinge bounds)
 *  - Touch navigation bar / rail and long-press menus for Lineage
 */
(function () {
  "use strict";

  const token = window.__STE_ANDROID_TOKEN__ || "";
  const isAndroid =
    window.__STE_PLATFORM__ === "android" || Boolean(token) || Boolean(window.AndroidHost);

  if (!isAndroid) return;

  const docEl = document.documentElement;
  docEl.setAttribute("data-platform", "android");

  // ── 1. HTTP JSON-RPC bridge mimicking pywebview.api ──────────────────
  async function rpcCall(method, args) {
    const resp = await fetch("/api/rpc/" + encodeURIComponent(method), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-STE-Token": token,
      },
      body: JSON.stringify({ args: args || [], kwargs: {} }),
    });
    const data = await resp.json().catch(() => ({ ok: false, error: "Invalid server response" }));
    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || "RPC failed (" + resp.status + ")");
    }
    return data.result;
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || "");
        const idx = result.indexOf(",");
        resolve(idx >= 0 ? result.slice(idx + 1) : result);
      };
      reader.onerror = () => reject(reader.error || new Error("Could not read file"));
      reader.readAsDataURL(file);
    });
  }

  function fileToText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("Could not read file"));
      reader.readAsText(file, "utf-8");
    });
  }

  function pickFilesViaInput({ accept = "*/*", multiple = false, capture = "" } = {}) {
    return new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = accept;
      if (multiple) input.multiple = true;
      if (capture) input.setAttribute("capture", capture);
      input.style.position = "fixed";
      input.style.left = "-9999px";
      let settled = false;
      const finish = (files) => {
        if (settled) return;
        settled = true;
        input.remove();
        resolve(files ? Array.from(files) : []);
      };
      input.addEventListener("change", () => finish(input.files));
      input.addEventListener("cancel", () => finish([]));
      // Fallback when Android WebView file chooser is dismissed without cancel event
      window.addEventListener(
        "focus",
        () => {
          setTimeout(() => {
            if (!settled && (!input.files || input.files.length === 0)) {
              finish([]);
            }
          }, 600);
        },
        { once: true }
      );
      document.body.appendChild(input);
      input.click();
    });
  }

  async function uploadPickedFiles(opts, mode, extraArgs = []) {
    const files = await pickFilesViaInput(opts);
    if (!files.length) return { ok: false, cancelled: true };
    const payloads = [];
    for (const f of files) {
      payloads.push({
        name: f.name || "file",
        mimeType: f.type || "",
        data_b64: await fileToBase64(f),
      });
    }
    return rpcCall("import_uploaded_files", [payloads, mode, ...extraArgs]);
  }

  function triggerBlobDownload(filename, mimeType, bytesOrText, isBase64) {
    let blob;
    if (isBase64) {
      const bin = atob(bytesOrText);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      blob = new Blob([arr], { type: mimeType || "application/octet-stream" });
    } else {
      blob = new Blob([bytesOrText], { type: mimeType || "text/plain;charset=utf-8" });
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "export";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    return { ok: true, path: filename };
  }

  function shareOrSaveNative(filename, mimeType, contentOrB64, isBase64) {
    const host = window.AndroidHost;
    if (host) {
      try {
        if (isBase64 && typeof host.shareBinaryFile === "function") {
          const ok = host.shareBinaryFile(filename || "export", mimeType || "application/octet-stream", contentOrB64);
          return { ok: Boolean(ok), path: filename, shared: true };
        }
        if (!isBase64 && typeof host.shareTextFile === "function") {
          const ok = host.shareTextFile(filename || "export.txt", mimeType || "text/plain", String(contentOrB64 || ""));
          return { ok: Boolean(ok), path: filename, shared: true };
        }
      } catch (err) {
        return { ok: false, error: String(err && err.message ? err.message : err) };
      }
    }
    return triggerBlobDownload(filename, mimeType, contentOrB64, isBase64);
  }

  const androidOverrides = {
    async pick_google_workspace_credentials() {
      const files = await pickFilesViaInput({ accept: ".json,application/json", multiple: false });
      if (!files.length) return { ok: false, cancelled: true };
      const raw = await fileToText(files[0]);
      return rpcCall("import_google_workspace_json", [raw]);
    },
    async pick_gmail_credentials() {
      return androidOverrides.pick_google_workspace_credentials();
    },
    async import_studio_sources(already) {
      return uploadPickedFiles({ accept: "*/*", multiple: true }, "sources", [already || 0]);
    },
    async import_studio_sources_folder(already) {
      return uploadPickedFiles({ accept: "*/*", multiple: true }, "sources", [already || 0]);
    },
    async import_media_file(modality) {
      const mod = String(modality || "image").toLowerCase();
      const accept =
        mod === "video" ? "video/*" : mod === "audio" ? "audio/*" : "image/*";
      return uploadPickedFiles({ accept, multiple: false }, "media", [0, mod]);
    },
    async import_text_file(saveToArchives) {
      return uploadPickedFiles(
        { accept: ".txt,.md,.markdown,.csv,.json,text/*", multiple: false },
        "text",
        [0, "text", Boolean(saveToArchives)]
      );
    },
    async import_pdf_file() {
      return uploadPickedFiles({ accept: ".pdf,application/pdf", multiple: false }, "pdf");
    },
    async open_viewer_file() {
      return uploadPickedFiles({ accept: "*/*", multiple: false }, "viewer");
    },
    async open_json_import() {
      return uploadPickedFiles({ accept: ".json,application/json", multiple: false }, "json");
    },
    async save_file_dialog(defaultName, content) {
      const name = String(defaultName || "document.txt");
      const mime = name.endsWith(".json")
        ? "application/json"
        : name.endsWith(".md")
          ? "text/markdown"
          : "text/plain";
      return shareOrSaveNative(name, mime, String(content || ""), false);
    },
    async save_binary_file_dialog(defaultName, base64Data) {
      const name = String(defaultName || "export.bin");
      const lower = name.toLowerCase();
      const mime = lower.endsWith(".pdf")
        ? "application/pdf"
        : lower.endsWith(".png")
          ? "image/png"
          : lower.endsWith(".jpg") || lower.endsWith(".jpeg")
            ? "image/jpeg"
            : lower.endsWith(".mp4")
              ? "video/mp4"
              : lower.endsWith(".mp3")
                ? "audio/mpeg"
                : "application/octet-stream";
      let b64 = String(base64Data || "");
      const comma = b64.indexOf(",");
      if (b64.startsWith("data:") && comma >= 0) b64 = b64.slice(comma + 1);
      return shareOrSaveNative(name, mime, b64, true);
    },
    async export_creation_media(creation) {
      const res = await rpcCall("prepare_export_payload", [creation || {}]);
      if (!res || !res.ok) return res || { ok: false, error: "Export failed" };
      return shareOrSaveNative(res.filename, res.mimeType, res.base64, true);
    },
    async pick_media_folder() {
      return { ok: false, error: "Android manages app library storage automatically." };
    },
    async pick_exports_folder() {
      return { ok: false, error: "Exports use the Android Share / Save sheet." };
    },
    async reveal_in_explorer(creationId) {
      const creations = await rpcCall("list_creations", []);
      const found = (creations || []).find((c) => c && c.id === creationId);
      if (!found) return { ok: false, error: "Item not found" };
      return androidOverrides.export_creation_media(found);
    },
  };

  if (!window.pywebview) {
    const apiProxy = new Proxy(
      {},
      {
        get(_target, prop) {
          if (typeof prop !== "string") return undefined;
          if (Object.prototype.hasOwnProperty.call(androidOverrides, prop)) {
            return androidOverrides[prop];
          }
          return (...args) => rpcCall(prop, args);
        },
      }
    );
    window.pywebview = { api: apiProxy };
  }

  // ── 2. Foldable Posture & Hinge Awareness ────────────────────────────
  function applyPosture(info) {
    const width = window.innerWidth || 360;
    const posture = (info && info.posture) || (width >= 680 ? "expanded" : "compact");
    const foldOrientation = (info && info.foldOrientation) || "none";
    const hingeLeft = Number((info && info.hingeLeftDp) || 0);
    const hingeWidth = Number((info && info.hingeWidthDp) || 0);
    const hingeTop = Number((info && info.hingeTopDp) || 0);
    const hingeHeight = Number((info && info.hingeHeightDp) || 0);

    docEl.setAttribute("data-posture", posture);
    docEl.setAttribute("data-fold-orientation", foldOrientation);
    docEl.style.setProperty("--hinge-left", hingeLeft + "px");
    docEl.style.setProperty("--hinge-width", hingeWidth + "px");
    docEl.style.setProperty("--hinge-top", hingeTop + "px");
    docEl.style.setProperty("--hinge-height", hingeHeight + "px");
    if (foldOrientation === "vertical" && hingeLeft > 220) {
      docEl.style.setProperty("--fold-pane-left", hingeLeft + "px");
    } else {
      docEl.style.removeProperty("--fold-pane-left");
    }
  }

  window.__STE_SET_POSTURE__ = applyPosture;
  applyPosture();
  window.addEventListener("resize", () => {
    if (!window.__STE_NATIVE_POSTURE_LOCK__) {
      applyPosture();
    }
  });

  // ── 3. Mobile Navigation Bar / Foldable Rail + Touch Enhancements ────
  function buildMobileChrome() {
    const shell = document.getElementById("app-shell");
    const screenSelect = document.getElementById("screen-select");
    if (!shell || !screenSelect || document.getElementById("mobile-nav")) return;

    const nav = document.createElement("nav");
    nav.id = "mobile-nav";
    nav.className = "mobile-nav";
    nav.setAttribute("aria-label", "Primary navigation");

    const items = [
      { id: "form", label: "Studio", icon: "✦" },
      { id: "viewer", label: "Viewer", icon: "◫" },
      { id: "library", label: "Archives", icon: "▤" },
      { id: "lineage", label: "Lineage", icon: "⎇" },
      { id: "more", label: "More", icon: "⋯" },
    ];

    const moreSheet = document.createElement("div");
    moreSheet.id = "mobile-more-sheet";
    moreSheet.className = "mobile-more-sheet";
    moreSheet.hidden = true;
    moreSheet.innerHTML =
      '<div class="mobile-sheet-backdrop"></div>' +
      '<div class="mobile-sheet-card" role="menu" aria-label="More screens">' +
      '  <div class="mobile-sheet-title">More</div>' +
      '  <button type="button" data-nav-target="image-edit" role="menuitem">Image Editor</button>' +
      '  <button type="button" data-nav-target="prompt-editor" role="menuitem">Prompt Editor</button>' +
      '  <button type="button" data-nav-target="control" role="menuitem">Settings</button>' +
      '  <button type="button" data-nav-close="1" class="mobile-sheet-cancel">Close</button>' +
      "</div>";

    function switchScreen(id) {
      moreSheet.hidden = true;
      screenSelect.value = id;
      screenSelect.dispatchEvent(new Event("change", { bubbles: true }));
      syncNavActive();
    }

    function syncNavActive() {
      const cur = screenSelect.value || "form";
      const secondary = new Set(["image-edit", "video-edit", "prompt-editor", "control"]);
      nav.querySelectorAll(".mobile-nav-btn").forEach((btn) => {
        const target = btn.getAttribute("data-nav-id");
        const active = target === cur || (target === "more" && secondary.has(cur));
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-current", active ? "page" : "false");
      });
    }

    items.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mobile-nav-btn";
      btn.setAttribute("data-nav-id", item.id);
      btn.innerHTML =
        '<span class="mobile-nav-icon" aria-hidden="true">' +
        item.icon +
        '</span><span class="mobile-nav-label">' +
        item.label +
        "</span>";
      btn.addEventListener("click", () => {
        if (item.id === "more") {
          moreSheet.hidden = !moreSheet.hidden;
        } else {
          switchScreen(item.id);
        }
      });
      nav.appendChild(btn);
    });

    moreSheet.addEventListener("click", (ev) => {
      const targetBtn = ev.target.closest("[data-nav-target]");
      if (targetBtn) {
        switchScreen(targetBtn.getAttribute("data-nav-target"));
        return;
      }
      if (ev.target.closest("[data-nav-close]") || ev.target.classList.contains("mobile-sheet-backdrop")) {
        moreSheet.hidden = true;
      }
    });

    screenSelect.addEventListener("change", syncNavActive);
    shell.appendChild(nav);
    document.body.appendChild(moreSheet);
    syncNavActive();

    // Add Camera Photo shortcut inside Studio Sources actions on Android
    const sourcesActions = document.querySelector(".studio-sources-actions");
    if (sourcesActions && !document.getElementById("btn-studio-camera-photo")) {
      const camBtn = document.createElement("button");
      camBtn.type = "button";
      camBtn.id = "btn-studio-camera-photo";
      camBtn.textContent = "Take Photo…";
      camBtn.addEventListener("click", async () => {
        const res = await uploadPickedFiles(
          { accept: "image/*", multiple: false, capture: "environment" },
          "sources",
          [0]
        );
        if (res && res.ok && res.creations && res.creations.length) {
          window.dispatchEvent(new CustomEvent("ste:sources-imported", { detail: res }));
        }
      });
      sourcesActions.insertBefore(camBtn, sourcesActions.firstChild);
    }

    // Long-press on Lineage SVG nodes opens the existing contextmenu handler
    const lineageSvg = document.getElementById("lineage-svg");
    if (lineageSvg) {
      let lpTimer = null;
      let lpTouch = null;
      lineageSvg.addEventListener(
        "touchstart",
        (ev) => {
          if (ev.touches.length !== 1) {
            clearTimeout(lpTimer);
            return;
          }
          const touch = ev.touches[0];
          lpTouch = { x: touch.clientX, y: touch.clientY, target: ev.target };
          lpTimer = setTimeout(() => {
            if (!lpTouch || !lpTouch.target) return;
            lpTouch.target.dispatchEvent(
              new MouseEvent("contextmenu", {
                bubbles: true,
                cancelable: true,
                clientX: lpTouch.x,
                clientY: lpTouch.y,
              })
            );
          }, 520);
        },
        { passive: true }
      );
      lineageSvg.addEventListener(
        "touchmove",
        (ev) => {
          if (!lpTouch || !ev.touches.length) return;
          const dx = ev.touches[0].clientX - lpTouch.x;
          const dy = ev.touches[0].clientY - lpTouch.y;
          if (Math.hypot(dx, dy) > 12) clearTimeout(lpTimer);
        },
        { passive: true }
      );
      lineageSvg.addEventListener("touchend", () => clearTimeout(lpTimer), { passive: true });
      lineageSvg.addEventListener("touchcancel", () => clearTimeout(lpTimer), { passive: true });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    buildMobileChrome();
    window.dispatchEvent(new Event("pywebviewready"));
  });
})();
