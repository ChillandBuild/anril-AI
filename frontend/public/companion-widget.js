/*!
 * Anril Companion web widget loader.
 *
 * On the business's page:
 *   <script src="https://www.anrilaitech.com/companion-widget.js" defer></script>
 *   AnrilCompanion.init({ companionId, userId, exp, signature, displayName, tools, onToolCall })
 *
 * userId, exp and signature come from the business's SERVER (it signs the user id with its
 * secret key). The secret key never reaches this page.
 *
 * The chat itself runs in an iframe on Anril's site, so it talks only to Anril's API. This
 * script draws the launcher button, opens the iframe and, when the character asks for an
 * app-run tool, runs onToolCall(call) on this page and sends the result back.
 * Messages go both ways by postMessage, checked against the exact iframe window and origin.
 */
(function () {
  "use strict";
  if (window.AnrilCompanion) return;

  var script = document.currentScript;
  var ORIGIN = script ? new URL(script.src).origin : "https://www.anrilaitech.com";
  var TOOL_TIMEOUT_MS = 60000;
  var state = null;

  function el(tag, css, attrs) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    for (var k in attrs || {}) node.setAttribute(k, attrs[k]);
    return node;
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve) {
      var timer = setTimeout(function () { resolve({ error: "timeout" }); }, ms);
      Promise.resolve(promise).then(
        function (v) { clearTimeout(timer); resolve(v); },
        function () { clearTimeout(timer); resolve({ error: "tool failed" }); }
      );
    });
  }

  function post(message) {
    if (state && state.frame.contentWindow) state.frame.contentWindow.postMessage(message, ORIGIN);
  }

  function runTools(requestId, calls) {
    var handler = state.opts.onToolCall;
    Promise.all((calls || []).map(function (call) {
      var out = typeof handler === "function"
        ? withTimeout(Promise.resolve().then(function () { return handler(call); }), TOOL_TIMEOUT_MS)
        : Promise.resolve({ error: "no tool handler on this page" });
      return out.then(function (output) {
        if (output === undefined) output = null;
        return { id: call.id, output: output };
      });
    })).then(function (results) {
      post({ type: "anril:tool_results", requestId: requestId, results: results });
    });
  }

  function onMessage(event) {
    if (!state || event.origin !== ORIGIN || event.source !== state.frame.contentWindow) return;
    var data = event.data || {};
    if (data.type === "anril:ready") {
      var o = state.opts;
      post({
        type: "anril:init",
        auth: { companion_id: o.companionId, user_id: String(o.userId), exp: Number(o.exp), signature: o.signature },
        displayName: o.displayName || null,
        tools: o.tools || [],
      });
    } else if (data.type === "anril:tool_calls") {
      runTools(data.requestId, data.calls);
    } else if (data.type === "anril:close") {
      setOpen(false);
    }
  }

  function setOpen(open) {
    state.open = open;
    state.panel.style.display = open ? "block" : "none";
    state.button.setAttribute("aria-expanded", String(open));
    state.button.setAttribute("aria-label", open ? "Close chat" : (state.opts.label || "Open chat"));
    state.button.innerHTML = open ? "&#x2715;" : "&#x1F4AC;";
    if (open && !state.frame.src) state.frame.src = ORIGIN + "/companion-widget?c=" + encodeURIComponent(state.opts.companionId);
  }

  function init(opts) {
    opts = opts || {};
    var missing = ["companionId", "userId", "exp", "signature"].filter(function (k) { return !opts[k]; });
    if (missing.length) {
      console.error("AnrilCompanion.init: missing " + missing.join(", "));
      return;
    }
    if (state) destroy();
    var color = opts.color || "#038285";
    var side = opts.position === "left" ? "left:20px;" : "right:20px;";
    var button = el("button",
      "position:fixed;bottom:20px;" + side + "z-index:2147483000;width:56px;height:56px;border-radius:50%;" +
      "border:0;background:" + color + ";color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.25);",
      { type: "button", "aria-label": opts.label || "Open chat", "aria-expanded": "false" });
    var panel = el("div",
      "position:fixed;bottom:88px;" + side + "z-index:2147483000;width:min(380px,calc(100vw - 32px));" +
      "height:min(600px,calc(100vh - 120px));border-radius:16px;overflow:hidden;display:none;" +
      "box-shadow:0 8px 32px rgba(0,0,0,.25);background:#fff;");
    var frame = el("iframe", "width:100%;height:100%;border:0;",
      { title: opts.label || "Chat", allow: "clipboard-write" });
    panel.appendChild(frame);
    document.body.appendChild(panel);
    document.body.appendChild(button);
    state = { opts: opts, button: button, panel: panel, frame: frame, open: false };
    button.addEventListener("click", function () { setOpen(!state.open); });
    window.addEventListener("message", onMessage);
    if (opts.open) setOpen(true);
  }

  function destroy() {
    if (!state) return;
    window.removeEventListener("message", onMessage);
    state.button.remove();
    state.panel.remove();
    state = null;
  }

  window.AnrilCompanion = {
    init: init,
    open: function () { if (state) setOpen(true); },
    close: function () { if (state) setOpen(false); },
    destroy: destroy,
  };
})();
