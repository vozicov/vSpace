/* Animated mouse cursors.
   Browsers cannot play a .ani file or an animated picture as a cursor, so the server stores an
   animated cursor as one tall png of its frames (a "strip") plus a list of steps
   [[frame, milliseconds], ...]. Here the strip is cut into one still picture per frame and the
   cursor picture is swapped on a timer.

   A page opts in with data-cursor-src, data-cursor-frames and data-cursor-steps on an element
   (the <body> of a profile page). The profile editor calls SpaceCursor.play() for its preview.
   The animation pauses while the tab is hidden and stays on its first frame for people who
   asked their system for less motion. Without JavaScript the normal cursor is shown. */
(function () {
    'use strict';

    var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // strip image -> array of blob: urls, one per frame
    function slice(src, frames, done) {
        var img = new Image();
        img.onload = function () {
            var w = img.naturalWidth, h = Math.floor(img.naturalHeight / frames), urls = [];
            if (!w || !h) { done([]); return; }
            (function next(i) {
                if (i >= frames) { done(urls); return; }
                var canvas = document.createElement('canvas');
                canvas.width = w; canvas.height = h;
                canvas.getContext('2d').drawImage(img, 0, i * h, w, h, 0, 0, w, h);
                canvas.toBlob(function (blob) {
                    urls.push(blob ? URL.createObjectURL(blob) : '');
                    next(i + 1);
                }, 'image/png');
            }(0));
        };
        img.onerror = function () { done([]); };
        img.src = src;
    }

    // Plays the animation on `host` (sets its --profile-cursor). Returns a function that stops it.
    function play(host, src, frames, steps) {
        var urls = [], at = 0, timer = 0, stopped = false;

        function show(url) {
            if (url) host.style.setProperty('--profile-cursor', 'url("' + url + '") 0 0, auto');
        }

        function tick() {
            window.clearTimeout(timer);
            if (stopped || document.hidden) return;
            var step = steps[at];
            show(urls[step[0]]);
            at = (at + 1) % steps.length;
            timer = window.setTimeout(tick, step[1]);
        }

        function visibility() { if (!document.hidden && urls.length && !calm) tick(); }
        document.addEventListener('visibilitychange', visibility);

        slice(src, frames, function (list) {
            if (stopped) { list.forEach(function (u) { if (u) URL.revokeObjectURL(u); }); return; }
            urls = list;
            if (!urls.length) return;
            show(urls[steps[0][0]]);
            if (steps.length > 1 && !calm) tick();
        });

        return function stop() {
            stopped = true;
            window.clearTimeout(timer);
            document.removeEventListener('visibilitychange', visibility);
            urls.forEach(function (u) { if (u) URL.revokeObjectURL(u); });
            host.style.removeProperty('--profile-cursor');
        };
    }

    window.SpaceCursor = { play: play };

    Array.prototype.forEach.call(document.querySelectorAll('[data-cursor-src]'), function (host) {
        var steps;
        try { steps = JSON.parse(host.getAttribute('data-cursor-steps')); } catch (e) { return; }
        var frames = parseInt(host.getAttribute('data-cursor-frames'), 10);
        if (!Array.isArray(steps) || !steps.length || !(frames > 0)) return;
        play(host, host.getAttribute('data-cursor-src'), frames, steps);
    });
}());
