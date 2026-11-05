/* Dreadnought Revival — HUD landing page script.
 * Sections: header/nav behaviour, ARIA tabs + hash routing, reveal,
 * status badge, patch-notes renderer, ship gallery lightbox. */
(function () {
  'use strict';

  /* ---------- helpers ---------- */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* render **bold** markers inside escaped text */
  function fmt(s) {
    var parts = String(s).split('**');
    var out = '';
    for (var i = 0; i < parts.length; i++) {
      out += i % 2 ? '<b>' + escapeHtml(parts[i]) + '</b>' : escapeHtml(parts[i]);
    }
    return out;
  }

  function dayLabel(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var months = ['January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'];
    return months[d.getUTCMonth()] + ' ' + d.getUTCDate() + ', ' + d.getUTCFullYear();
  }

  var prefersReduced = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- header / burger ---------- */

  var header = $('#site-header');
  var burger = $('#burger');
  var navLinks = $('#nav-links');

  function onScrollHeader() {
    if (!header) return;
    if (window.scrollY > 40) header.classList.add('scrolled');
    else header.classList.remove('scrolled');
  }
  window.addEventListener('scroll', onScrollHeader, { passive: true });
  onScrollHeader();

  function closeMenu() {
    if (!navLinks || !navLinks.classList.contains('open')) return;
    navLinks.classList.remove('open');
    if (burger) {
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    }
  }

  if (burger && navLinks) {
    burger.addEventListener('click', function () {
      var open = navLinks.classList.toggle('open');
      burger.classList.toggle('open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  /* ---------- tabs (the nav is a tablist; panels switch, hash routes deep links) ---------- */

  var TABS = ['play', 'status', 'modes', 'patch-notes', 'gallery', 'roadmap', 'contribute'];
  /* tab ids before the 2026-11 reorganisation, so old links still land */
  var ALIASES = { briefing: 'status', systems: 'status', community: 'play' };
  function tabFromHash() {
    var id = location.hash.slice(1);
    return ALIASES[id] || id;
  }
  var tabButtons = $all('[role="tab"]');
  var panelsEl = $('#panels');

  function scrollToPanels(smooth) {
    if (!panelsEl) return;
    var top = panelsEl.getBoundingClientRect().top + window.scrollY - 84;
    window.scrollTo({ top: top, behavior: smooth && !prefersReduced ? 'smooth' : 'auto' });
  }

  function revealPanel(panel) {
    if (!panel) return;
    $all('.reveal', panel).forEach(function (el, i) {
      el.style.transitionDelay = Math.min(i * 30, 300) + 'ms';
      el.classList.add('visible');
    });
  }

  function selectTab(id, pushHash, scroll) {
    if (TABS.indexOf(id) === -1) return false;
    tabButtons.forEach(function (btn) {
      var pid = btn.getAttribute('data-panel');
      var panel = document.getElementById(pid);
      var on = pid === id;
      if (panel) panel.hidden = !on;
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
      btn.tabIndex = on ? 0 : -1;
      btn.classList.toggle('active', on);
    });
    revealPanel(document.getElementById(id));
    if (pushHash && location.hash !== '#' + id) {
      history.pushState(null, '', '#' + id);
    }
    if (scroll) scrollToPanels(true);
    return true;
  }

  tabButtons.forEach(function (btn, i) {
    btn.addEventListener('click', function () {
      selectTab(btn.getAttribute('data-panel'), true, true);
      closeMenu();
    });
    btn.addEventListener('keydown', function (e) {
      var n = null;
      if (e.key === 'ArrowRight') n = (i + 1) % tabButtons.length;
      else if (e.key === 'ArrowLeft') n = (i - 1 + tabButtons.length) % tabButtons.length;
      else if (e.key === 'Home') n = 0;
      else if (e.key === 'End') n = tabButtons.length - 1;
      if (n === null) return;
      e.preventDefault();
      tabButtons[n].focus();
      selectTab(tabButtons[n].getAttribute('data-panel'), true, false);
    });
  });

  function onHashChange() {
    var id = tabFromHash();
    /* #top and unknown hashes: leave the tabs alone */
    if (TABS.indexOf(id) === -1) return;
    if (selectTab(id, false, false)) scrollToPanels(true);
  }
  window.addEventListener('hashchange', onHashChange);
  window.addEventListener('popstate', onHashChange);

  /* initial state: deep link selects the tab, otherwise play */
  if (!selectTab(tabFromHash(), false, false)) {
    selectTab('play', false, false);
  } else {
    scrollToPanels(false);
  }

  /* ---------- reveal on scroll (elements outside the tab panels) ---------- */

  var revealEls = $all('.reveal');

  if (!prefersReduced && 'IntersectionObserver' in window) {
    var revealObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          en.target.classList.add('visible');
          revealObs.unobserve(en.target);
        }
      });
    }, { threshold: 0.12 });
    revealEls.forEach(function (el) {
      /* panel content is revealed by selectTab instead */
      if (!panelsEl || !panelsEl.contains(el)) revealObs.observe(el);
    });
  } else {
    revealEls.forEach(function (el) { el.classList.add('visible'); });
  }

  /* ---------- status badge ---------- */

  function loadStatus() {
    var badge = $('#status-badge');
    var text = $('#status-text');
    if (!badge || !text) return;
    fetch('data/server-status.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('status ' + r.status); return r.json(); })
      .then(function (data) {
        var online = !!(data && (data.online === true ||
          (typeof data.online === 'string' && data.online.toLowerCase() === 'true')));
        if (online) {
          badge.classList.remove('offline');
          badge.classList.add('online');
          text.textContent = 'Public Test Server Live';
        } else {
          badge.classList.remove('online');
          badge.classList.add('offline');
          text.textContent = 'Public Test Server Offline';
        }
      })
      .catch(function () {
        /* keep the default text: Public Test Server Live */
      });
  }

  /* ---------- patch notes ---------- */

  function renderPatchNotes(data) {
    var list = $('#patch-notes-list');
    if (!list) return;
    var notes = (data && Array.isArray(data.notes)) ? data.notes : [];
    if (!notes.length) {
      list.innerHTML = '<p class="patch-fallback">No patch notes yet — check back after the next server update.</p>';
      return;
    }
    var html = '';
    notes.forEach(function (note) {
      html += '<article class="patch-day">';
      html += '<h3>Patch notes – ' + escapeHtml(dayLabel(note.date)) + '</h3>';
      (note.sections || []).forEach(function (section) {
        html += '<h4>' + escapeHtml(section.title || '') + '</h4>';
        html += '<ul>';
        (section.bullets || []).forEach(function (b) {
          html += '<li><span class="msg">' + fmt(b) + '</span></li>';
        });
        html += '</ul>';
      });
      html += '</article>';
    });
    list.innerHTML = html;
  }

  function loadPatchNotes() {
    var list = $('#patch-notes-list');
    if (!list) return;
    fetch('data/patch-notes.json', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('notes ' + r.status); return r.json(); })
      .then(renderPatchNotes)
      .catch(function () {
        list.innerHTML = '<p class="patch-fallback">Patch notes could not be loaded — read the commit history on GitHub.</p>';
      });
  }

  /* ---------- gallery lightbox ---------- */

  var lightbox = $('#lightbox');

  function openLightbox(card) {
    if (!lightbox) return;
    var img = $('#lightbox-img');
    var name = $('#lightbox-name');
    var cls = $('#lightbox-cls');
    if (!img || !name || !cls) return;
    var srcImg = card.querySelector('img');
    img.src = srcImg ? srcImg.getAttribute('src') : '';
    img.alt = srcImg ? srcImg.alt : '';
    name.textContent = card.getAttribute('data-name') || '';
    cls.textContent = card.getAttribute('data-cls') || '';
    lightbox.classList.add('open');
    document.body.style.overflow = 'hidden';
    var closeBtn = $('#lightbox-close');
    if (closeBtn) closeBtn.focus();
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.classList.remove('open');
    document.body.style.overflow = '';
  }

  $all('.ship-card').forEach(function (card) {
    card.addEventListener('click', function () { openLightbox(card); });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openLightbox(card);
      }
    });
  });

  if (lightbox) {
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox) closeLightbox();
    });
    var closeBtn = $('#lightbox-close');
    if (closeBtn) closeBtn.addEventListener('click', closeLightbox);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && lightbox.classList.contains('open')) closeLightbox();
    });
  }

  /* ---------- boot ---------- */

  loadStatus();
  loadPatchNotes();
})();
