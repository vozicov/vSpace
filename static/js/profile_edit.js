/* Edit profile: the live preview next to the tools.
   The preview is the real profile card, filled from the form's current values every time
   something changes. Nothing is sent to the server until Publish is pressed. Chosen pictures are
   shown straight from the browser (object URLs) and never uploaded by the preview. The page
   background colour / picture is drawn behind the card, inside the preview only.
   On narrow screens the tools and the preview take turns (Tools | Preview switch).
   Without JavaScript the form works as a normal form (no preview). */
(function () {
    'use strict';

    var root = document.querySelector('.pe');
    if (!root) return;
    function all(selector) { return Array.prototype.slice.call(root.querySelectorAll(selector)); }
    var form = root.querySelector('.pe-form');
    var card = root.querySelector('[data-card]');
    var stage = root.querySelector('[data-stage]');
    var nameEls = all('[data-p-name]');
    var bioEl = root.querySelector('[data-p-bio]');
    var avatarImgs = all('[data-p-avatar]');
    var initialEls = all('[data-p-initial]');
    var bannerEl = root.querySelector('[data-banner]');
    var bannerImg = root.querySelector('[data-banner-img]');
    var username = root.getAttribute('data-username');

    // pictures that are already published, and pictures just chosen (object URLs)
    var saved = {
        avatar: root.getAttribute('data-avatar'),
        banner: root.getAttribute('data-banner'),
        bgimage: root.getAttribute('data-bgimage'),
        cursor: root.getAttribute('data-cursor'),
        cursorFrames: parseInt(root.getAttribute('data-cursor-frames'), 10) || 0,
        cursorSteps: (function () {
            try { return JSON.parse(root.getAttribute('data-cursor-steps')) || []; } catch (e) { return []; }
        }())
    };
    var savedAnimated = !!(saved.cursor && saved.cursorSteps.length && saved.cursorFrames);
    var cursorShown = null;   // what the preview cursor is showing now, so it is not restarted on every key press
    var stopCursor = null;    // stops a playing animated cursor

    // the cursor picker tile for an animated cursor has no thumbnail: say what it is instead
    if (savedAnimated) {
        var cursorTile = root.querySelector('[data-upload-field="cursor"]');
        if (cursorTile) {
            var cursorPick = cursorTile.querySelector('[data-pick]');
            var cursorPlus = cursorTile.querySelector('[data-plus]');
            if (cursorPick) cursorPick.textContent = 'Change';
            if (cursorPlus) cursorPlus.textContent = '\u25B6';
        }
    }
    var cursorLook = '';      // the chosen cursor picture, already shrunk to cursor size (a data: URL)
    var cursorJob = 0;        // tells a slow, out-of-date shrink job to give up
    var chosen = {};
    var FIELD_KEY = { avatar: 'avatar', banner: 'banner', background_image: 'bgimage', cursor: 'cursor' };

    function val(name) { return form.elements[name] ? form.elements[name].value : ''; }
    function checked(name) { return !!(form.elements[name] && form.elements[name].checked); }

    // same rule as Profile._text_on in accounts/models.py
    function textOn(hex) {
        var r = parseInt(hex.substr(1, 2), 16), g = parseInt(hex.substr(3, 2), 16), b = parseInt(hex.substr(5, 2), 16);
        return (0.299 * r + 0.587 * g + 0.114 * b) < 140 ? '#faf6f0' : '#080603';
    }

    function setPrefixed(node, prefix, value) {
        Array.prototype.slice.call(node.classList).forEach(function (c) {
            if (c.indexOf(prefix) === 0) node.classList.remove(c);
        });
        node.classList.add(prefix + value);
    }

    function isHex(v) { return /^#[0-9a-f]{6}$/i.test(v); }

    // Same rules as make_cursor() on the server, so the preview shows the real thing: trim the
    // see-through border, shrink to cursor size (never enlarge), keep transparency.
    var CURSOR_SIDE = 32;
    function shrinkCursor(src, done) {
        var img = new Image();
        img.onload = function () {
            var w = img.naturalWidth, h = img.naturalHeight;
            if (!w || !h) { done(''); return; }
            var pre = Math.min(1, 1024 / Math.max(w, h));               // huge pictures: look at a smaller copy
            var cw = Math.max(1, Math.round(w * pre)), ch = Math.max(1, Math.round(h * pre));
            var big = document.createElement('canvas'); big.width = cw; big.height = ch;
            var bx = big.getContext('2d'); bx.drawImage(img, 0, 0, cw, ch);
            var px = bx.getImageData(0, 0, cw, ch).data, x0 = cw, y0 = ch, x1 = -1, y1 = -1;
            for (var y = 0; y < ch; y++) for (var x = 0; x < cw; x++) {
                if (px[(y * cw + x) * 4 + 3] > 8) {
                    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
                }
            }
            if (x1 < 0) { done(''); return; }                          // nothing visible
            var bw = x1 - x0 + 1, bh = y1 - y0 + 1, k = Math.min(1, CURSOR_SIDE / Math.max(bw, bh));
            var out = document.createElement('canvas');
            out.width = Math.max(1, Math.round(bw * k)); out.height = Math.max(1, Math.round(bh * k));
            var ox = out.getContext('2d'); ox.imageSmoothingQuality = 'high';
            ox.drawImage(big, x0, y0, bw, bh, 0, 0, out.width, out.height);
            done(out.toDataURL('image/png'));
        };
        img.onerror = function () { done(''); };
        img.src = src;
    }

    function applyCursor() {
        var look = '', key;
        if (chosen.cursor) { look = cursorLook; key = 'new:' + chosen.cursor + ':' + look.length; }
        else if (checked('remove_cursor')) key = 'none';
        else if (savedAnimated) key = 'animated';
        else { look = saved.cursor; key = 'still'; }
        if (key === cursorShown) return;
        cursorShown = key;

        if (stopCursor) { stopCursor(); stopCursor = null; }
        stage.style.removeProperty('--profile-cursor');
        if (key === 'animated') {
            stage.classList.add('has-cursor');
            if (window.SpaceCursor) stopCursor = window.SpaceCursor.play(stage, saved.cursor, saved.cursorFrames, saved.cursorSteps);
            return;
        }
        stage.classList.toggle('has-cursor', !!look);
        if (look) stage.style.setProperty('--profile-cursor', 'url("' + look + '") 0 0, auto');
    }

    function applyPage() {
        var color = val('background_color');
        if (isHex(color)) {
            stage.style.setProperty('--stage-bg', color);
            stage.style.setProperty('--song-bg', color);              // the music player wears it too
            stage.style.setProperty('--song-ink', textOn(color));
        }
        var image = chosen.bgimage || (checked('remove_background_image') ? '' : saved.bgimage);
        if (image) stage.style.setProperty('--stage-img', 'url("' + image + '")');
        else stage.style.removeProperty('--stage-img');
        applyCursor();
    }

    function render() {
        var name = val('display_name').trim() || username;
        nameEls.forEach(function (n) { n.textContent = name; });
        var bio = val('bio').trim();
        bioEl.textContent = bio;
        bioEl.hidden = !bio;

        var shape = val('avatar_shape') || 'circle';
        var avatar = chosen.avatar || saved.avatar;
        avatarImgs.forEach(function (img) {
            setPrefixed(img, 'shape-', shape);
            if (avatar) img.src = avatar;
            img.hidden = !avatar;
        });
        initialEls.forEach(function (n) {
            setPrefixed(n, 'shape-', shape);
            n.hidden = !!avatar;
            n.textContent = username.charAt(0).toUpperCase();
        });

        // The banner element is added to / taken out of the card (not hidden), because the
        // card's CSS reacts to a banner being the card's first child.
        var banner = chosen.banner || (checked('remove_banner') ? '' : saved.banner);
        if (banner) {
            bannerImg.src = banner;
            if (!bannerEl.parentNode) card.insertBefore(bannerEl, card.firstChild);
        } else if (bannerEl.parentNode) {
            bannerEl.parentNode.removeChild(bannerEl);
        }

        var bg = val('card_color');
        if (isHex(bg)) {
            card.style.setProperty('--card-bg', bg);
            card.style.setProperty('--card-fg', textOn(bg));
        }
        setPrefixed(card, 'font-', val('font') || 'default');
        applyPage();
    }

    /* ---------- file tiles ---------- */
    function sizeText(bytes) {
        return bytes < 1048576 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB';
    }

    function fileChanged(input) {
        var key = FIELD_KEY[input.name];
        var tile = input.closest('.upload-field');
        if (!key || !tile) return;
        var thumb = tile.querySelector('[data-thumb]');
        var plus = tile.querySelector('[data-plus]');
        var label = tile.querySelector('[data-filename]');
        var pick = tile.querySelector('[data-pick]');
        var file = input.files && input.files[0];

        // a Windows animated cursor: the browser cannot show it, the server turns it into frames
        var isAni = !!file && key === 'cursor' && /\.ani$/i.test(file.name);

        if (file && !isAni && file.type.indexOf('image/') !== 0) {
            input.value = '';
            file = null;
            label.textContent = key === 'cursor'
                ? 'That file is not a cursor. Choose a PNG, GIF or .ani file.'
                : 'That file is not a picture. Choose a JPG, PNG, WebP or GIF.';
        } else if (file) {
            label.textContent = file.name + ' · ' + sizeText(file.size) + (isAni ? ' · animated, shown after you save' : '');
        } else {
            label.textContent = label.getAttribute('data-hint');
        }

        if (chosen[key]) URL.revokeObjectURL(chosen[key]);   // (does nothing for the 'ani' marker below)
        if (isAni) chosen[key] = 'ani';                      // chosen, but there is nothing to draw
        else if (file) chosen[key] = URL.createObjectURL(file); else delete chosen[key];

        // a saved animated cursor is a strip of frames: no use as a thumbnail
        var current = key === 'cursor' && savedAnimated ? '' : saved[key];
        var shown = isAni ? '' : (chosen[key] || current);
        if (shown) thumb.src = shown;
        thumb.hidden = !shown;
        plus.hidden = !!shown;
        pick.textContent = (isAni || shown || (key === 'cursor' && savedAnimated && !file)) ? 'Change' : 'Choose';

        if (key === 'cursor') {
            var job = ++cursorJob;
            cursorLook = '';
            if (chosen.cursor && !isAni) shrinkCursor(chosen.cursor, function (look) { if (job === cursorJob) { cursorLook = look; render(); } });
        }
    }

    /* ---------- color buttons ---------- */
    function syncColor(field) {
        var input = field.querySelector('input[type="color"]');
        var value = input.value;
        field.querySelector('.swatch-btn').style.setProperty('--sw', value);
        field.querySelector('[data-hex]').textContent = value;
        Array.prototype.forEach.call(field.querySelectorAll('.preset'), function (p) {
            p.classList.toggle('on', p.getAttribute('data-color') === value.toLowerCase());
        });
    }

    var colorFields = Array.prototype.slice.call(root.querySelectorAll('[data-color-field]'));
    colorFields.forEach(function (field) {
        field.querySelector('[data-presets]').hidden = false;
        syncColor(field);
    });

    form.addEventListener('click', function (e) {
        var preset = e.target.closest && e.target.closest('.preset');
        if (!preset) return;
        var input = preset.closest('[data-color-field]').querySelector('input[type="color"]');
        input.value = preset.getAttribute('data-color');
        input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    function onChange(e) {
        var t = e.target;
        if (t.type === 'file') fileChanged(t);
        var field = t.closest && t.closest('[data-color-field]');
        if (field) syncColor(field);
        render();
    }
    form.addEventListener('input', onChange);
    form.addEventListener('change', onChange);

    /* ---------- Edit / Preview switch ---------- */
    var seg = root.querySelector('[data-seg]');
    var segButtons = Array.prototype.slice.call(root.querySelectorAll('[data-mode-btn]'));

    // (only used on narrow screens; on wide screens the tools and the preview are both on screen)
    function setMode(next) {
        root.setAttribute('data-mode', next);
        segButtons.forEach(function (b) {
            var on = b.getAttribute('data-mode-btn') === next;
            b.classList.toggle('on', on);
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        window.scrollTo(0, 0);
    }
    segButtons.forEach(function (b) {
        b.addEventListener('click', function () { setMode(b.getAttribute('data-mode-btn')); });
    });
    seg.hidden = false;
    root.classList.add('is-live');   // the preview is only shown when this script is running

    // the browser may restore typed values when you come back to the page
    window.addEventListener('pageshow', function () {
        Array.prototype.forEach.call(root.querySelectorAll('input[type="file"]'), fileChanged);
        colorFields.forEach(syncColor);
        render();
    });
    render();
}());
