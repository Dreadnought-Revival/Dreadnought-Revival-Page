(function () {
  "use strict";

  var TABS = ["about", "join", "status", "patch-notes", "community"];

  // Mobile nav toggle
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Tabs: the nav is a tablist; panels switch, hash routes deep links
  function selectTab(id, updateHash) {
    if (TABS.indexOf(id) === -1) id = "about";
    TABS.forEach(function (t) {
      var panel = document.getElementById(t);
      var tab = document.getElementById("tab-" + t);
      if (!panel || !tab) return;
      var on = t === id;
      panel.hidden = !on;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      tab.classList.toggle("active", on);
    });
    if (updateHash !== false && location.hash !== "#" + id) {
      history.pushState(null, "", "#" + id);
    }
  }

  function wireTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        selectTab(tab.getAttribute("data-panel"));
        if (links && links.classList.contains("open")) {
          links.classList.remove("open");
          if (toggle) toggle.setAttribute("aria-expanded", "false");
        }
      });
      tab.addEventListener("keydown", function (e) {
        var i = tabs.indexOf(tab);
        var n = null;
        if (e.key === "ArrowRight") n = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") n = 0;
        else if (e.key === "End") n = tabs.length - 1;
        if (n === null) return;
        e.preventDefault();
        tabs[n].focus();
        selectTab(tabs[n].getAttribute("data-panel"));
      });
    });
    window.addEventListener("hashchange", function () {
      selectTab(location.hash.slice(1), false);
    });
    window.addEventListener("popstate", function () {
      selectTab(location.hash.slice(1), false);
    });
    selectTab(location.hash.slice(1), false);
  }

  // Server status badge: static fallback, upgraded if data/server-status.json exists
  function loadStatus() {
    var badge = document.getElementById("status-badge");
    var detail = document.getElementById("status-detail");
    if (!badge) return;
    fetch("data/server-status.json")
      .then(function (r) {
        if (!r.ok) throw new Error("no status file");
        return r.json();
      })
      .then(function (s) {
        badge.textContent = s.online ? "Online" : "Offline";
        badge.classList.add(s.online ? "online" : "offline");
        if (typeof s.players === "number") {
          detail.textContent = s.players + " player" + (s.players === 1 ? "" : "s") + " online" +
            (s.updated_at ? " (updated " + s.updated_at + ")" : "");
        }
      })
      .catch(function () {
        badge.textContent = "Community-run";
        detail.textContent = "Live status is reported by the community — see the links below.";
      });
  }

  // Patch notes: player-facing, rendered from data/patch-notes.json
  var state = { notes: [] };

  function dayLabel(iso) {
    var d = new Date(iso + "T00:00:00Z");
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "long", timeZone: "UTC" });
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // minimal markdown: **bold** for new or returning maps and features
  function fmt(s) {
    return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  function render() {
    var host = document.getElementById("patch-notes-list");
    if (!host) return;
    if (!state.notes.length) {
      host.innerHTML = '<p class="muted">No patch notes yet.</p>';
      return;
    }
    var html = "";
    state.notes.forEach(function (n) {
      html += '<div class="patch-day"><h3>Patch notes – ' + escapeHtml(dayLabel(n.date)) + "</h3>";
      (n.sections || []).forEach(function (sec) {
        html += "<h4>" + fmt(sec.title) + "</h4><ul>";
        (sec.bullets || []).forEach(function (b) {
          html += '<li><span class="msg">' + fmt(b) + "</span></li>";
        });
        html += "</ul>";
      });
      html += "</div>";
    });
    host.innerHTML = html;
  }

  function loadPatchNotes() {
    var host = document.getElementById("patch-notes-list");
    if (!host) return;
    fetch("data/patch-notes.json")
      .then(function (r) {
        if (!r.ok) throw new Error("no patch notes file");
        return r.json();
      })
      .then(function (data) {
        state.notes = data.notes || [];
        render();
      })
      .catch(function () {
        host.innerHTML = '<p class="muted">Patch notes could not be loaded. See the commit history on GitHub instead.</p>';
      });
  }

  wireTabs();
  loadStatus();
  loadPatchNotes();
})();
