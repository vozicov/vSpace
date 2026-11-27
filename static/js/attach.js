/* The image / video attach button on the new post form. The real file input is hidden; the
   round icon is its label. When a file is picked it shows a small chip with a preview, the
   name and the size, and a x to take it off again. */
(function () {
    'use strict';

    var root = document.querySelector('.attach');
    var input = root && root.querySelector('input[type="file"]');
    var chip = root && root.querySelector('[data-file-chip]');
    if (!input || !chip) return;

    var button = root.querySelector('label.attach-btn');
    var thumb = chip.querySelector('[data-file-thumb]');
    var icon = chip.querySelector('[data-file-icon]');
    var name = chip.querySelector('[data-file-name]');
    var size = chip.querySelector('[data-file-size]');
    var remove = chip.querySelector('[data-file-remove]');
    var preview = null;   // object URL of the picture being shown

    function megabytes(bytes) {
        return bytes < 1024 * 1024
            ? Math.max(1, Math.round(bytes / 1024)) + ' KB'
            : (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function forget() {
        if (preview) { URL.revokeObjectURL(preview); preview = null; }
        thumb.removeAttribute('src');
    }

    function show() {
        forget();
        var file = input.files && input.files[0];
        chip.hidden = !file;
        if (button) button.classList.toggle('is-on', !!file);
        if (!file) return;

        name.textContent = file.name;
        size.textContent = (file.type.indexOf('video/') === 0 ? 'Video' : 'Image') + ' · ' + megabytes(file.size);

        var isImage = file.type.indexOf('image/') === 0 && window.URL && URL.createObjectURL;
        if (isImage) { preview = URL.createObjectURL(file); thumb.src = preview; }
        thumb.hidden = !isImage;
        icon.hidden = !!isImage;
    }

    input.addEventListener('change', show);
    remove.addEventListener('click', function () { input.value = ''; show(); });
    window.addEventListener('pageshow', show);   // the back button can bring a file back
    show();
}());
