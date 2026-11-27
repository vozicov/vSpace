/* The little record player under a post (templates/feed/_music.html).
   Play / pause the 30 second clip, a progress bar you can tap to jump around, and only one
   song plays at a time. The play button starts hidden and is shown here, so without
   JavaScript the card is just the song's name (which links to Apple Music). */
(function () {
    'use strict';

    var cards = document.querySelectorAll('[data-player]');
    if (!cards.length) return;

    var current = null;   // the audio element that is playing now

    // media events do not bubble, but they can be caught on the way down
    document.addEventListener('play', function (e) {
        if (current && current !== e.target) current.pause();
        current = e.target;
    }, true);

    function clock(seconds) {
        seconds = Math.max(0, Math.round(seconds));
        return Math.floor(seconds / 60) + ':' + ('0' + (seconds % 60)).slice(-2);
    }

    function setup(card) {
        var audio = card.querySelector('audio');
        var button = card.querySelector('[data-toggle]');
        var bar = card.querySelector('[data-bar]');
        var time = card.querySelector('[data-time]');
        if (!audio || !button) return;

        var length = function () { return isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 30; };

        function paint() {
            var share = Math.min(1, audio.currentTime / length());
            card.style.setProperty('--pct', (share * 100).toFixed(1) + '%');
            if (bar) bar.setAttribute('aria-valuenow', Math.round(share * 100));
            if (time) time.textContent = clock(length() - audio.currentTime);
        }

        function state(playing) {
            card.classList.toggle('is-playing', playing);
            button.setAttribute('aria-label', playing ? 'Pause preview' : 'Play 30 second preview');
        }

        button.hidden = false;

        button.addEventListener('click', function () {
            if (audio.paused) {
                audio.play().catch(function () { state(false); });
            } else {
                audio.pause();
            }
        });

        if (bar) {
            bar.addEventListener('click', function (e) {
                var box = bar.getBoundingClientRect();
                if (!box.width) return;
                audio.currentTime = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) * length();
                paint();
            });
        }

        audio.addEventListener('play', function () { state(true); });
        audio.addEventListener('pause', function () { state(false); });
        audio.addEventListener('timeupdate', paint);
        audio.addEventListener('loadedmetadata', paint);
        audio.addEventListener('ended', function () { audio.currentTime = 0; state(false); paint(); });
        audio.addEventListener('error', function () {
            state(false);
            if (time) time.textContent = 'oops';
        });
    }

    Array.prototype.forEach.call(cards, setup);
}());
