/* The music note button on the new post form. It opens a search box; as you type, it asks our
   server for matching songs (the server asks Apple) and lists them under the box. Click a song
   to attach it; the post only sends the song's id. Each result has a 30 second preview.
   Nothing here is trusted: the server checks the song again when the post is published.
   Text is always put on the page with textContent, never as HTML. */
(function () {
    'use strict';

    var root = document.querySelector('[data-music]');
    if (!root) return;

    var url = root.getAttribute('data-url');
    var hidden = root.querySelector('[data-music-id]');
    var toggle = root.querySelector('[data-music-toggle]');
    var wrap = root.querySelector('[data-search-wrap]');
    var input = root.querySelector('[data-q]');
    var list = root.querySelector('[data-results]');
    var chosen = root.querySelector('[data-chosen]');
    var chosenArt = root.querySelector('[data-chosen-art]');
    var chosenTitle = root.querySelector('[data-chosen-title]');
    var chosenArtist = root.querySelector('[data-chosen-artist]');
    var remove = root.querySelector('[data-remove]');

    var DELAY = 250;          // ms to wait after the last key
    var MIN = 2;              // same rule as the server
    var timer = null;
    var request = null;       // the request in flight, so a newer one can cancel it
    var seen = {};            // answers already fetched
    var audio = null;         // the one preview that may play at a time
    var playing = null;       // the button of the preview that is playing

    // the form came back with an error and no song to show: drop the leftover id
    if (hidden.value && chosen.hidden) hidden.value = '';

    // the note button only works with JavaScript, so it is only shown here
    toggle.hidden = false;
    toggle.classList.toggle('is-on', !chosen.hidden);

    function openPanel() {
        wrap.hidden = false;
        toggle.setAttribute('aria-expanded', 'true');
        input.focus();
    }

    function closePanel() {
        wrap.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        clearList();
    }

    function stopAudio() {
        if (audio) { audio.pause(); audio = null; }
        if (playing) { playing.textContent = '\u25B6'; playing.setAttribute('aria-label', 'Play preview'); playing = null; }
    }

    function clearList() {
        stopAudio();
        list.textContent = '';
        list.hidden = true;
    }

    function note(text) {
        stopAudio();
        list.textContent = '';
        var li = document.createElement('li');
        li.className = 'music-note';
        li.textContent = text;
        list.appendChild(li);
        list.hidden = false;
    }

    function line(song) {
        var li = document.createElement('li');
        li.className = 'music-row';

        var pick = document.createElement('button');
        pick.type = 'button';
        pick.className = 'music-choose';
        if (song.art) {
            var img = document.createElement('img');
            img.className = 'music-art';
            img.src = song.art;
            img.alt = '';
            pick.appendChild(img);
        }
        var meta = document.createElement('span');
        meta.className = 'music-meta';
        var title = document.createElement('strong');
        title.className = 'music-title';
        title.textContent = song.title;
        var artist = document.createElement('span');
        artist.className = 'music-artist';
        artist.textContent = song.artist + (song.album ? ' · ' + song.album : '');
        meta.appendChild(title);
        meta.appendChild(artist);
        pick.appendChild(meta);
        pick.addEventListener('click', function () { choose(song); });
        li.appendChild(pick);

        if (song.preview) {
            var play = document.createElement('button');
            play.type = 'button';
            play.className = 'music-play';
            play.textContent = '\u25B6';
            play.setAttribute('aria-label', 'Play preview');
            play.addEventListener('click', function () { toggle(play, song.preview); });
            li.appendChild(play);
        }
        return li;
    }

    function render(songs) {
        stopAudio();
        list.textContent = '';
        if (!songs.length) { note('No songs found. Try the artist name too.'); return; }
        songs.forEach(function (song) { list.appendChild(line(song)); });
        list.hidden = false;
    }

    function toggle(button, src) {
        var same = playing === button;
        stopAudio();
        if (same) return;
        audio = new Audio(src);
        playing = button;
        button.textContent = '\u25A0';
        button.setAttribute('aria-label', 'Stop preview');
        audio.addEventListener('ended', stopAudio);
        audio.play().catch(stopAudio);
    }

    function choose(song) {
        stopAudio();
        hidden.value = song.id;
        chosenTitle.textContent = song.title;
        chosenArtist.textContent = song.artist;
        if (song.art) { chosenArt.src = song.art; chosenArt.hidden = false; } else { chosenArt.hidden = true; }
        chosen.hidden = false;
        toggle.classList.add('is-on');
        input.value = '';
        closePanel();
    }

    toggle.addEventListener('click', function () {
        if (wrap.hidden) openPanel(); else closePanel();
    });

    remove.addEventListener('click', function () {
        hidden.value = '';
        chosen.hidden = true;
        toggle.classList.remove('is-on');
        closePanel();
    });

    function load() {
        var q = input.value.trim().replace(/\s+/g, ' ');
        if (q.length < MIN) { clearList(); return; }
        var key = q.toLowerCase();
        if (seen[key]) { render(seen[key]); return; }

        if (request) request.abort();
        request = new AbortController();
        note('Searching…');

        fetch(url + '?q=' + encodeURIComponent(q), {
            signal: request.signal,
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'fetch' }
        }).then(function (r) {
            if (r.redirected) { location.reload(); throw new Error('login'); }   // session ended
            return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        }).then(function (answer) {
            if (!answer.ok) throw new Error(answer.data.error || 'Search is not available right now.');
            seen[key] = answer.data.results;
            if (input.value.trim().replace(/\s+/g, ' ').toLowerCase() === key) render(answer.data.results);
        }).catch(function (e) {
            if (e.name === 'AbortError' || e.message === 'login') return;
            note(e.message && e.message.length < 120 ? e.message : 'Search is not available right now.');
        });
    }

    input.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(load, DELAY);
    });
    // Enter must not publish the post while you are still searching
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timer); load(); }
        if (e.key === 'Escape') { closePanel(); toggle.focus(); }
    });
    input.form.addEventListener('submit', stopAudio);
}());
