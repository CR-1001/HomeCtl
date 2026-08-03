/* This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
   Distributed under terms of the GPL3 license. */

/*
Handles live inline editing for .live-md files.
Clicking a plain-text line opens an input field; Enter/blur saves the line
via WebSocket. All users viewing the same file are kept in sync via a
Socket.IO room named "live:<path>".
*/

let _currentLivePath = null;
let _mutationTimer = null;

document.addEventListener('DOMContentLoaded', function() {

    // Watch for live-md containers appearing/disappearing/changing in the DOM
    const observer = new MutationObserver(function() {
        clearTimeout(_mutationTimer);
        _mutationTimer = setTimeout(_syncLiveRoom, 50);
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Initial join
    _syncLiveRoom();

    // Click handler for checkbox toggle
    document.addEventListener('click', function(event) {
        const cb = event.target.closest('.live-md-checkbox');
        if (!cb) return;
        event.stopPropagation();
        const line = cb.closest('.live-md-line');
        if (!line) return;
        const container = line.closest('[data-live-path]');
        if (!container) return;
        const raw = line.dataset.raw;
        let newRaw;
        if (raw.startsWith('[ ] '))       newRaw = '[x] ' + raw.slice(4);
        else if (raw.startsWith('[x] ')) newRaw = '[ ] ' + raw.slice(4);
        else return;
        execute('files', 'update_line', {
            live_path: container.dataset.livePath,
            line_idx:  line.dataset.lineIdx,
            content:   newRaw
        });
    });

    // Click handler for editable label lines
    document.addEventListener('click', function(event) {
        if (event.target.closest('.live-md-checkbox')) return;
        const el = event.target.closest('.live-md-line');
        if (!el) return;
        if (el.classList.contains('live-md-editing')) return;
        // Don't open editor if click was inside a <details> summary toggle
        if (event.target.closest('summary')) return;
        _openLineEditor(el);
    });

    // Click handler for the append-line button
    document.addEventListener('click', function(event) {
        const btn = event.target.closest('.live-md-append');
        if (!btn) return;
        if (btn.classList.contains('live-md-editing')) return;
        _openAppendEditor(btn);
    });
});


function _syncLiveRoom() {
    const el = document.querySelector('[data-live-path]');
    const newPath = el ? el.dataset.livePath : null;
    if (newPath === _currentLivePath) return;

    const socket = getSocket();
    if (!socket) return;

    function doSync() {
        if (_currentLivePath) socket.emit('leave_live', { path: _currentLivePath });
        if (newPath)          socket.emit('join_live',  { path: newPath });
        _currentLivePath = newPath;
    }

    if (socket.connected) {
        doSync();
    } else {
        socket.once('connect', doSync);
    }
}


function _openLineEditor(el) {
    el.classList.add('live-md-editing');

    const lineIdx  = el.dataset.lineIdx;
    const raw      = el.dataset.raw;
    const container = el.closest('[data-live-path]');
    if (!container) { el.classList.remove('live-md-editing'); return; }

    const input = document.createElement('input');
    input.type  = 'text';
    input.value = raw;
    input.className = 'live-md-input';

    let saved = false;

    function save() {
        if (saved) return;
        saved = true;
        execute('files', 'update_line', {
            live_path: container.dataset.livePath,
            line_idx:  lineIdx,
            content:   input.value
        });
    }

    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') {
            saved = true;          // prevent blur from saving
            input.replaceWith(el);
            el.classList.remove('live-md-editing');
        }
    });

    input.addEventListener('blur', save);

    el.replaceWith(input);
    input.focus();
    input.select();
}


function _openAppendEditor(btn) {
    btn.classList.add('live-md-editing');

    const container = btn.closest('[data-live-path]');
    if (!container) { btn.classList.remove('live-md-editing'); return; }

    const input = document.createElement('input');
    input.type      = 'text';
    input.value     = '';
    input.className = 'live-md-input';

    let saved = false;

    function save() {
        if (saved) return;
        saved = true;
        if (input.value.trim() !== '') {
            execute('files', 'append_line', {
                live_path: container.dataset.livePath,
                content:   input.value
            });
        } else {
            // nothing to append — restore the button
            input.replaceWith(btn);
            btn.classList.remove('live-md-editing');
        }
    }

    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') {
            saved = true;
            input.replaceWith(btn);
            btn.classList.remove('live-md-editing');
        }
    });

    input.addEventListener('blur', save);

    btn.replaceWith(input);
    input.focus();
}
