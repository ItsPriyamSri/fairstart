/* FirstJob Verifier — no-dependency chat + mini markdown renderer. */
(function () {
  "use strict";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function inline(s) {
    // escape first, then apply formatting on safe text
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return s;
  }

  function md(src) {
    var lines = String(src || "").split("\n");
    var html = "", list = null, i, line, m;
    function close() { if (list) { html += "</" + list + ">"; list = null; } }
    for (i = 0; i < lines.length; i++) {
      line = lines[i].trim();
      if (!line) { close(); continue; }
      if (/^#{1,3}\s/.test(line)) { close(); html += "<h3>" + inline(line.replace(/^#{1,3}\s*/, "")) + "</h3>"; continue; }
      m = line.match(/^([-*])\s+(.*)/);
      if (m) {
        if (list !== "ul") { close(); html += "<ul>"; list = "ul"; }
        html += "<li>" + inline(m[2]) + "</li>"; continue;
      }
      m = line.match(/^\d+[.)]\s+(.*)/);
      if (m) {
        if (list !== "ol") { close(); html += "<ol>"; list = "ol"; }
        html += "<li>" + inline(m[1]) + "</li>"; continue;
      }
      close();
      html += "<p>" + inline(line) + "</p>";
    }
    close();
    return html || "<p></p>";
  }

  function bubble(who, bodyHtml, via) {
    var row = document.createElement("div");
    row.className = "bubble-row " + (who === "You" ? "you" : "senior");
    var b = document.createElement("div");
    b.className = "bubble md";
    b.innerHTML = '<span class="who">' + esc(who) + "</span>" + bodyHtml +
      (via ? ' <span class="via">(' + esc(via) + ")</span>" : "");
    row.appendChild(b);
    return row;
  }

  function scrollChat(box) {
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }

  // animate verdict gauges from empty to their scored value
  document.querySelectorAll(".gauge .value").forEach(function (el) {
    var target = el.getAttribute("stroke-dashoffset") || "0";
    el.style.strokeDashoffset = "326.7";
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.style.strokeDashoffset = target; });
    });
  });

  // render any server-rendered plain-text replies as markdown on load
  document.querySelectorAll("[data-md]").forEach(function (el) {
    el.innerHTML = md(el.textContent);
  });

  var form = document.getElementById("chat-form");
  if (!form) return;
  var box = document.getElementById("thread");
  var input = form.querySelector('input[name="question"]');
  var btn = form.querySelector("button");

  // session-local thread cache: survives reloads/back-nav within this tab
  // session. Server thread wins; session only fills messages the server
  // hasn't rendered (JS-sent exchanges). Keyed per thread.
  var tid = form.dataset.threadId || "t0";
  var skey = "fs-thread-" + tid;
  function loadSession() {
    try {
      var items = JSON.parse(sessionStorage.getItem(skey) || "[]");
      var have = box.querySelectorAll(".bubble-row.senior").length;
      items.slice(have).forEach(function (m) {
        box.appendChild(bubble("You", md(m.q || ""), ""));
        box.appendChild(bubble("Guardian", md(m.a || ""), m.via || ""));
      });
    } catch (e) { /* private mode etc: chat still works, just not cached */ }
  }
  function saveSession(q, a, via) {
    try {
      var items = JSON.parse(sessionStorage.getItem(skey) || "[]");
      items.push({ q: q, a: a, via: via });
      sessionStorage.setItem(skey, JSON.stringify(items.slice(-30)));
    } catch (e) { /* ignore */ }
  }
  loadSession();
  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = (input.value || "").trim();
    if (!q) return;
    box.appendChild(bubble("You", md(q), ""));
    input.value = "";
    btn.disabled = true;
    var typing = bubble("Guardian", '<span class="typing"><span></span><span></span><span></span></span>', "");
    box.appendChild(typing);
    scrollChat(box);
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: parseInt(form.dataset.runId || "0", 10),
        idx: parseInt(form.dataset.idx || "0", 10),
        thread_id: form.dataset.threadId || "t0",
        question: q
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        typing.remove();
        btn.disabled = false;
        if (d.error) {
          box.appendChild(bubble("Guardian", md("Hmm, that didn't go through (" + d.error + ") — try again?"), "rules"));
        } else {
          var last = (d.thread || []).slice(-1)[0] || {};
          var answer = last.a || d.reply || "";
          var via = last.via || d.via || "";
          box.appendChild(bubble("Guardian", md(answer), via));
          saveSession(q, answer, via);
        }
        scrollChat(box);
        input.focus();
      })
      .catch(function () {
        typing.remove();
        btn.disabled = false;
        box.appendChild(bubble("Guardian", md("Network hiccup — the server didn't answer. Try again?"), "rules"));
      });
  });
})();
