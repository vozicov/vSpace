/* The only JavaScript on the site. It does three small things for forms marked data-once:
   1. locks the submit button after the first click (the server also refuses duplicates),
   2. on forms marked data-upload, sends the file with a live "42%" progress bar,
   3. on textareas marked data-counter, shows how many characters are left.
   Without JavaScript every form still works. */
(function () {
    'use strict';

    function samePath(a, b) {
        return new URL(a, location.href).pathname === new URL(b, location.href).pathname;
    }

    function setup(form) {
        var button = form.querySelector('[data-submit]');
        var bar = form.querySelector('[data-progress]');
        var fill = form.querySelector('[data-fill]');
        var pct = form.querySelector('[data-pct]');
        var error = form.querySelector('[data-error]');
        var label = button ? button.textContent : '';
        var busy = false;

        function lock() {
            busy = true;
            if (button) {
                button.disabled = true;
                button.textContent = button.getAttribute('data-busy') || label;
            }
        }

        function unlock() {
            busy = false;
            if (button) { button.disabled = false; button.textContent = label; }
            if (bar) bar.hidden = true;
        }

        function show(percent, text) {
            bar.hidden = false;
            bar.classList.toggle('is-processing', percent >= 100);
            bar.setAttribute('aria-valuenow', percent);
            fill.style.setProperty('--pct', percent + '%');
            pct.textContent = text || percent + '%';
        }

        function fail(message) {
            unlock();
            if (error) { error.textContent = message; error.hidden = false; }
        }

        // Back button restores the page from memory with the button still locked
        window.addEventListener('pageshow', function (e) { if (e.persisted) unlock(); });

        form.addEventListener('submit', function (e) {
            if (busy) { e.preventDefault(); return; }
            if (error) error.hidden = true;
            lock();

            var inputs = Array.prototype.slice.call(form.querySelectorAll('input[type="file"]'));
            var hasFile = inputs.some(function (i) { return i.files.length; });
            var wantsProgress = form.hasAttribute('data-upload') && hasFile
                && window.XMLHttpRequest && window.FormData;
            if (!wantsProgress) return;   // normal submit, the button is already locked

            e.preventDefault();
            var action = form.getAttribute('action') || location.href;
            var xhr = new XMLHttpRequest();
            xhr.open('POST', action);

            show(0);
            xhr.upload.onprogress = function (ev) {
                if (ev.lengthComputable) show(Math.min(100, Math.round(ev.loaded / ev.total * 100)));
            };
            // the file is up; the server now compresses it, which can take a while for video
            xhr.upload.onload = function () { show(100, 'Processing…'); };

            xhr.onload = function () {
                if (xhr.status >= 400) {
                    fail('Something went wrong (error ' + xhr.status + '). Please try again.');
                } else if (xhr.responseURL && !samePath(xhr.responseURL, action)) {
                    location.assign(xhr.responseURL);          // saved: go to the new post
                } else {
                    document.open(); document.write(xhr.responseText); document.close();  // form errors
                }
            };
            xhr.onerror = function () { fail('The upload failed. Check your connection and try again.'); };
            xhr.send(new FormData(form));
        });
    }

    function counter(area) {
        var form = area.form;
        var out = form && form.querySelector('[data-count]');
        var max = parseInt(area.getAttribute('maxlength'), 10);
        if (!out || !max) return;
        function update() { out.textContent = area.value.length + ' / ' + max; }
        area.addEventListener('input', update);
        update();
    }

    document.querySelectorAll('form[data-once]').forEach(setup);
    document.querySelectorAll('textarea[data-counter]').forEach(counter);
}());
