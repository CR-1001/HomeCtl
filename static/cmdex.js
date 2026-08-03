/* This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
   Distributed under terms of the GPL3 license. */

/*
Handles view-model functionalities, collects arguments entered in fields, and  
calls server functions via WebSocket.
*/

let socket = null;
let _uploadInProgress = false;

document.addEventListener('DOMContentLoaded', function() {
    initializeWebSocket();
    initialize();
    
    processNotifications();

    // react to command
    document.addEventListener("click", function(event) {
        if (event.target.matches(".execute, input.execute")) {
            if (event.target.dataset.confirm) {
                if (confirm(event.target.dataset.confirm) == false) {
                    return;
                }
            }
            process(event.target);
        }
    });
    
    let debounceTimer;
    document.addEventListener("input", function(event) {
        if (event.target.matches(".execute, input.execute")) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function() {
                process(event.target);
            }, 400);
        }
    });

    // Enter in a text input triggers the nearest execute element instead of form submit
    document.addEventListener("keydown", function(event) {
        if (event.key !== "Enter") return;
        if (!event.target.matches("input[type='text'], input:not([type])")) return;
        event.preventDefault();
        const form = event.target.closest("form");
        if (!form) return;
        const btn = form.querySelector(".execute");
        if (btn) process(btn);
    });

    // invert selection in multiple-selection fields
    document.addEventListener("click", function(event) {        if (event.target.matches('#_popup_close')) {
            closePopup();
        }
    });

    document.addEventListener('click', function(event) {        if (event.target.matches(".invert-selection")) {
            invertSelection(event.target.parentElement);
        }
    });

    // bring into view
    document.addEventListener("click", function(event) {
        if (event.target.matches(".bring_into_view")) {
            const containerId = event.target.dataset.container;
            setTimeout(function() {
                bringIntoView(containerId);
            }, 1000);
        }
    });

    // Show details on click
    document.addEventListener("click", function(event) {
        // Don't show details if clicking on an execute button
        if (event.target.closest(".execute")) return;
        
        const el = event.target.closest("[data-details]");
        if (!el) return;
        const details = el.dataset.details;
        if (details && details.trim() !== "") {
            showDetailsPopup(details);
        }
    });
});

// Initialize WebSocket connection
function initializeWebSocket() {
    // Check if Socket.IO is loaded
    if (typeof io === 'undefined') {
        console.error('Socket.IO library not loaded');
        setTimeout(initializeWebSocket, 100);
        return;
    }
    
    // Configure Socket.IO with reconnection settings
    socket = io({
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        reconnectionAttempts: 10
    });
    
    socket.on('connect', function() {
        console.log('WebSocket connected');
    });
    
    socket.on('disconnect', function() {
        console.log('WebSocket disconnected');
        if (_uploadInProgress) return;
        hideProcessing();
        enable(true);
    });
    
    socket.on('response', function(views) {
        applyResponse(views);
    });
    
    socket.on('connect_error', function(error) {
        console.error('WebSocket connection error:', error);
        if (_uploadInProgress) return;
        hideProcessing();
        enable(true);
    });
}

function process(sourceElement) {
    const isAutoupdate = !!sourceElement.dataset.autoupdatedelay;
    if (!isAutoupdate && document.querySelectorAll(".execute.inactive").length > 0) return;
    
    const funcPath = sourceElement.dataset.func;
    const form = sourceElement.closest("form");
    const fieldset1 = sourceElement.closest("fieldset");
    const fieldset2 = sourceElement.closest(".fieldset");

    // Route file uploads through XHR for real transfer-progress tracking
    const uploadContainer = fieldset1 || fieldset2 || form;
    const fileInput = uploadContainer && uploadContainer.querySelector('input[type="file"]');
    if (fileInput && fileInput.files && fileInput.files.length > 0) {
        processFileUpload(fileInput, uploadContainer);
        return;
    }

    const args = {};
    
    // Extract vm and func from the func path (e.g., "start/ctl")
    const parts = funcPath.split('/');
    const vm = parts[0];
    const func = parts[1] || 'ctl';
    
    [form, fieldset1, fieldset2].forEach(function(container) {
        if (!container) return;
        container.querySelectorAll("input, select, textarea").forEach(function(elem) {
            // When collecting from the form, skip inputs inside child fieldsets —
            // those are scoped to specific execute_params buttons and collected via fieldset1/fieldset2.
            if (container.tagName === 'FORM') {
                const nearestFieldset = elem.closest('fieldset, .fieldset');
                if (nearestFieldset) return;
            }
            const key = elem.name;
            if (key === undefined || key === "") return;

            // Handle select, textarea elements
            if (elem.matches("input[type='text'], textarea, select")) {
                args[key] = elem.value;
            } else if (elem.matches("input")) {
                const value = elem.value;
                
                // Case multiple selected options
                if (elem.type === "checkbox") {
                    if (!args.hasOwnProperty(key)) {
                        args[key] = [];
                    }
                    if (elem.checked) {
                        args[key].push(value);
                    }
                } else {
                    args[key] = value;
                }
            }
        });
    });

    // triggers
    const param = sourceElement.dataset.param;
    if (param) {
        args[param] = sourceElement.dataset.value;
    }

    if (!sourceElement.dataset.autoupdatedelay) {
        showProcessing();
        enable(false);
    }
    execute(vm, func, args);
}

// initialize module (extract view-model, function, and arguments from the URL)
function initialize() {
    enable(false);

    const parts = window.location.pathname.split('/');
    const vm = parts[1];
    const func = parts[2];

    const params = {};
    const searchParams = new URLSearchParams(window.location.search);
    searchParams.forEach(function(value, key) {
        params[key] = value;
    });

    execute(vm, func, params);
}

// execute a command and refresh view via WebSocket
function execute(vm, func, args) {
    if (!socket) {
        console.error("WebSocket not initialized");
        enable(true);
        return;
    }
    
    // If not connected, wait for connection
    if (!socket.connected) {
        console.log("Waiting for WebSocket connection...");
        socket.once('connect', function() {
            socket.emit('execute', {
                vm: vm,
                func: func,
                args: args
            });
        });
        return;
    }
    
    // Send command via WebSocket
    socket.emit('execute', {
        vm: vm,
        func: func,
        args: args
    });
}

// close popup
function closePopup() {
    const popup = document.getElementById('_popup');
    if (popup) popup.innerHTML = '';
    syncPopupOverlay();
}

// sync popup overlay visibility with _popup content
function syncPopupOverlay() {
    const popup = document.getElementById('_popup');
    const overlay = document.getElementById('_popup_overlay');
    if (!overlay || !popup) return;
    const form = popup.querySelector('form');
    const hasContent = form ? form.children.length > 0 : popup.innerHTML.trim() !== '';
    overlay.classList.toggle('hidden', !hasContent);
}

// handle auto-update
const processedAutoUpdates = new Set();
function handleAutoUpdate(key) {
    if (processedAutoUpdates.has(key)) return;

    const updatedElement = document.getElementById(key);
    const elems = updatedElement
        ? updatedElement.querySelectorAll('[data-autoupdatedelay]')
        : [];
    if (elems.length === 0) return;

    processedAutoUpdates.add(key);
    elems.forEach(elem => {
        const delay = elem.dataset.autoupdatedelay;
        setTimeout(function() { 
            processedAutoUpdates.delete(key); 
            process(elem);
        }, delay);
    });
}

// process notifications and show alerts
function processNotifications() {
    const notifications = document.querySelectorAll('[data-alert]');
    notifications.forEach(elem => {
        const message = elem.dataset.alert;
        if (message && message.trim() !== "") {
            alert(message);
        }
        elem.remove();
    });
}

// enable or disable controls   
function enable(active) {
    controls = document.querySelectorAll(".execute");
    if (active) {
        controls.forEach(el => el.classList.remove("inactive"));
    }
    else {
        controls.forEach(el => el.classList.add("inactive"));
    }
}

// show details text in the popup overlay (client-side, no server round-trip)
function showDetailsPopup(text) {
    const popup = document.getElementById('_popup');
    if (!popup) return;
    const div = document.createElement('div');
    div.style.whiteSpace = 'pre-wrap';
    div.style.padding = '0.5rem';
    div.textContent = text;
    popup.innerHTML = '';
    popup.appendChild(div);
    syncPopupOverlay();
}

// show/hide the global processing overlay
function showProcessing(text) {
    const el = document.getElementById('_processing');
    if (el) el.classList.remove('hidden');
    const textEl = document.getElementById('_processing_text');
    if (textEl) textEl.textContent = text || 'Processing...';
}

function setProcessingText(text) {
    const textEl = document.getElementById('_processing_text');
    if (textEl) textEl.textContent = text;
}

function hideProcessing() {
    const el = document.getElementById('_processing');
    if (el) el.classList.add('hidden');
}

// expose the socket instance for other scripts (e.g. live.js)
function getSocket() { return socket; }

// apply a {key: html} response dict to the DOM
function applyResponse(views) {
    if ('_back' in views) {
        history.back();
        return;
    }
    Object.keys(views).forEach(key => {
        const element = document.getElementById(key);
        if (element) {
            element.outerHTML = views[key];
            handleAutoUpdate(key);
        } else if (key === '_notification') {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = views[key];
            document.body.appendChild(tempDiv);
        }
    });
    if ('_error' in views) {
        const tmp = document.createElement('div');
        tmp.innerHTML = views['_error'];
        const msg = tmp.textContent.trim();
        if (msg) alert(msg);
    }
    syncPopupOverlay();
    processNotifications();
    requestAnimationFrame(function() {
        if (!_uploadInProgress) {
            hideProcessing();
            enable(true);
        }
    });
}

// upload files via XHR with byte-level progress shown in the processing overlay
// pre-flight check skips files that already exist without transferring their bytes
function processFileUpload(fileInput, container) {
    enable(false);
    const allFiles  = Array.from(fileInput.files);
    const renameInp = container.querySelector('input[name="rename"]');
    const rename    = renameInp ? renameInp.value.trim() : '';
    const names     = allFiles.map(function(f) { return f.name; });

    fetch('/files/upload/check', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({names: names, rename: rename})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        const skipSet  = new Set(data.skip_originals || []);
        const toUpload = allFiles.filter(function(f) { return !skipSet.has(f.name); });

        if (skipSet.size > 0) {
            const div = document.createElement('div');
            const label = skipSet.size === 1 ? 'file already exists' : 'files already exist';
            div.dataset.alert = skipSet.size + ' ' + label + ', not replaced:\n' + Array.from(skipSet).join(', ');
            document.body.appendChild(div);
        }

        if (toUpload.length === 0) {
            processNotifications();
            enable(true);
            return;
        }

        _doFileUpload(toUpload, fileInput.name, container);
    })
    .catch(function() {
        // On check failure, proceed with full upload (server still guards against overwrites)
        _doFileUpload(allFiles, fileInput.name, container);
    });
}

function _doFileUpload(files, inputName, container, _retries) {
    if (_retries === undefined) _retries = 2;

    const totalBytes = files.reduce(function(s, f) { return s + f.size; }, 0);
    const totalMB    = (totalBytes / 1048576).toFixed(2);

    const formData = new FormData();
    files.forEach(function(f) { formData.append(inputName, f); });
    // Collect companion text inputs (e.g. rename)
    container.querySelectorAll('input[type="text"], input:not([type])').forEach(function(inp) {
        if (inp.name && inp.value.trim()) formData.append(inp.name, inp.value.trim());
    });

    _uploadInProgress = true;
    showProcessing('0.00 / ' + totalMB + ' MB');

    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = function(e) {
        if (e.lengthComputable) {
            setProcessingText(
                (e.loaded / 1048576).toFixed(2) + ' / ' +
                (e.total  / 1048576).toFixed(2) + ' MB'
            );
        }
    };
    xhr.onload = function() {
        _uploadInProgress = false;
        try {
            applyResponse(JSON.parse(xhr.responseText));
        } catch(err) {
            console.error('Upload response error', err);
            hideProcessing();
            enable(true);
        }
    };
    xhr.onerror = function() {
        if (_retries > 0) {
            setProcessingText('Interrupted – retrying (' + _retries + ')…');
            setTimeout(function() {
                _doFileUpload(files, inputName, container, _retries - 1);
            }, 3000);
        } else {
            _uploadInProgress = false;
            hideProcessing();
            enable(true);
        }
    };
    xhr.open('POST', '/files/upload');
    xhr.send(formData);
}