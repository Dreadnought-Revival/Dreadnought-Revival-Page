/* Dreadnought Revival — HUD landing page script.
 * Sections: header/nav behaviour, scrollspy, reveal-on-scroll, status badge,
 * patch-notes renderer, ship gallery lightbox, copy button. */
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

  if (burger && navLinks) {
    burger.addEventListener('click', function () {
      var open = navLinks.classList.toggle('open');
      burger.classList.toggle('open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    navLinks.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'A') {
        navLinks.classList.remove('open');
        burger.classList.remove('open');
        burger.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* ---------- reveal on scroll ---------- */

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
    revealEls.forEach(function (el) { revealObs.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('visible'); });
  }

  /* ---------- scrollspy ---------- */

  var navAnchors = $all('.nav-links a[href^="#"]');
  var sections = navAnchors.map(function (a) {
    return document.getElementById(a.getAttribute('href').slice(1));
  }).filter(Boolean);

  function onScrollSpy() {
    if (!sections.length) return;
    var pos = window.scrollY + window.innerHeight * 0.35;
    var current = sections[0];
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].offsetTop <= pos) current = sections[i];
    }
    navAnchors.forEach(function (a) {
      var active = a.getAttribute('href') === '#' + current.id;
      a.classList.toggle('active', active);
      if (active) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
  }
  window.addEventListener('scroll', onScrollSpy, { passive: true });
  onScrollSpy();

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
          text.textContent = 'Status: Servers Online';
        } else {
          badge.classList.remove('online');
          badge.classList.add('offline');
          text.textContent = 'Status: Offline';
        }
      })
      .catch(function () {
        /* keep default text: Active Development — Revival in Progress */
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
      html += '<h3>' + escapeHtml(dayLabel(note.date)) + '</h3>';
      (note.sections || []).forEach(function (section) {
        var title = String(section.title || '').toLowerCase();
        var h = /^summary|release|general/.test(title) ? 'h4' : 'h4';
        html += '<' + h + '>' + escapeHtml(section.title || '') + '</' + h + '>';
        html += '<ul>';
        (section.bullets || []).forEach(function (b) {
          html += '<li>' + fmt(b) + '</li>';
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

  /* ---------- copy button ---------- */

  var copyBtn = $('#copy-btn');
  var copyCmd = $('#clone-cmd');
  if (copyBtn && copyCmd) {
    copyBtn.addEventListener('click', function () {
      var done = function () {
        copyBtn.textContent = 'Copied!';
        setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1500);
      };
      var text = copyCmd.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (err) { /* noop */ }
        document.body.removeChild(ta);
        done();
      }
    });
  }

  /* ---------- boot ---------- */

  loadStatus();
  loadPatchNotes();
})();
