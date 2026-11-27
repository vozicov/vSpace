/* The search drawer. As you type, it asks the server for matching people, posts and tweets
   and fills the drawer under the bar. The server does the real work (a full-text index), this
   file only waits a moment after you stop typing, drops answers that are already out of date,
   and remembers answers it has seen. Enter still opens the full results page. */
(function () {
    'use strict';

    var box = document.querySelector('[data-search-box]');
    if (!box) return;
    var input = box.querySelector('[data-input]');
    var drawer = box.querySelector('[data-drawer]');
    var clear = box.querySelector('[data-clear]');
    var url = box.getAttribute('data-url');
    var DELAY = 160;          // ms to wait after the last key
    var MIN = 2;              // same rule as the server

    var type = 'all';
    var timer = null;
    var request = null;       // the request in flight, so a newer one can cancel it
    var seen = {};            // answers already fetched: backspacing is instant

    function term() { return input.value.trim(); }

    function open() {
        drawer.classList.add('open');
        input.setAttribute('aria-expanded', 'true');
    }
    function close() {
        drawer.classList.remove('open');
        input.setAttribute('aria-expanded', 'false');
        if (request) { request.abort(); request = null; }
    }

    function show(html) {
        drawer.innerHTML = html;
        drawer.classList.remove('loading');
        open();
    }

    function hint(text) {
        show('<p class="drawer-hint">' + text + '</p>');
    }

    function load() {
        var q = term();
        if (!q) { close(); return; }
        if (q.length < MIN) { hint('Keep typing: at least 2 letters.'); return; }

        var key = type + '|' + q;
        if (seen[key]) { show(seen[key]); return; }

        if (request) request.abort();
        request = new AbortController();
        drawer.classList.add('loading');
        open();

        fetch(url + '?fragment=1&type=' + encodeURIComponent(type) + '&q=' + encodeURIComponent(q), {
            signal: request.signal,
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'fetch' }
        }).then(function (r) {
            if (r.redirected) { location.reload(); throw new Error('login'); }   // session ended
            if (!r.ok) throw new Error(r.status);
            return r.text();
        }).then(function (html) {
            seen[key] = html;
            if (term() === q) show(html);     // ignore an answer for something no longer typed
        }).catch(function (e) {
            if (e.name === 'AbortError') return;
            drawer.classList.remove('loading');
            hint('Search is not available right now. Press Enter to try the full page.');
        });
    }

    function later() {
        clearTimeout(timer);
        clear.hidden = !input.value;
        timer = setTimeout(load, DELAY);
    }

    input.addEventListener('input', later);
    var quiet = false;        // true while we move focus back to the bar ourselves (after Escape)
    input.addEventListener('focus', function () {
        if (quiet) { quiet = false; return; }
        if (term()) { clear.hidden = false; if (drawer.innerHTML) open(); else load(); }
    });

    clear.addEventListener('click', function () {
        input.value = ''; clear.hidden = true; close(); input.focus();
    });

    // tabs: load the tab in place instead of leaving the page
    drawer.addEventListener('click', function (e) {
        var tab = e.target.closest && e.target.closest('[data-type]');
        if (!tab) return;
        e.preventDefault();
        type = tab.getAttribute('data-type');
        load();
        var again = drawer.querySelector('[data-type="' + type + '"]');
        if (again) again.focus();
    });

    // close: Escape, or any click / focus outside the bar and drawer
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && drawer.classList.contains('open')) { close(); quiet = document.activeElement !== input; input.focus(); }
    });
    document.addEventListener('click', function (e) { if (!box.contains(e.target)) close(); });
    document.addEventListener('focusin', function (e) { if (!box.contains(e.target)) close(); });

    // arrow keys walk through the results, and back up to the bar
    box.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
        if (!drawer.classList.contains('open')) return;
        var items = Array.prototype.slice.call(drawer.querySelectorAll('.sr-item, .drawer-all'));
        if (!items.length) return;
        var at = items.indexOf(document.activeElement);
        var next;
        if (e.key === 'ArrowDown') next = at < 0 ? items[0] : items[Math.min(items.length - 1, at + 1)];
        else if (at <= 0) next = input;
        else next = items[at - 1];
        e.preventDefault();
        next.focus();
    });

    // the page came back from history with something already typed
    if (term()) { clear.hidden = false; }
}());
