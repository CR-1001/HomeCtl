/* This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
   Distributed under terms of the GPL3 license. */

/*
Common.
*/

function setInput(selector, value) {
    const element = document.querySelector(selector);
    if (element) {
        element.setAttribute("value", value);
        element.style.visibility = value === "-" ? "collapse" : "visible";
    }
}

function setText(selector, text) {
    const element = document.querySelector(selector);
    if (element) {
        element.textContent = text;
    }
}

function setColor(selector, red1, gre1, blu1, red2, gre2, blu2) {
    const element = document.querySelector(selector);
    if (element) {
        const col1 = toRgbCss(red1, gre1, blu1, 1);
        const col2 = toRgbCss(red2, gre2, blu2, 1);
        element.style.backgroundImage = `linear-gradient(to right, ${col1}, ${col2})`;
    }
}

function setVisible(selector, isVisible) {
    const element = document.querySelector(selector);
    if (element) {
        element.style.visibility = isVisible ? "visible" : "collapse";
    }
}

function getData(selector, key) {
    const dataKey = `data-${key}`;
    const element = document.querySelector(selector);
    if (element) {
        const closestElement = element.closest(`[${dataKey}]`);
        return closestElement ? closestElement.getAttribute(dataKey) : null;
    }
    return null;
}

function setData(selector, key, value) {
    const element = document.querySelector(selector);
    if (element) {
        const dataKey = `data-${key}`;
        element.setAttribute(dataKey, value);
    }
}

function getSearchParameter(key, defaultValue = null) {
    const value = new URLSearchParams(window.location.search).get(key);
    return value !== null ? value : defaultValue;
}

function setSearchParameter(key, value) {
    const url = new URL(location);
    url.searchParams.set(key, value);
    history.replaceState({}, "", url);
}

function pushStateHistoryWithSearchParameter(key, value) {
    const url = new URL(location);
    url.searchParams.set(key, value);
    history.pushState({}, "", url);
}

function toRgbCss(red, gre, blu, transparency) {
    return `rgb(${red}, ${gre}, ${blu}, ${transparency})`;
}

function isNumber(str) {
    return /^[0-9]+$/.test(str);
}

function clean(text) {
    return text.replace(/\n/g, '<br>').replace(/\s/g, '&nbsp;');
}

function invertSelection(container) {
    const checkboxes = document.querySelectorAll(`${container} :checkbox`);
    checkboxes.forEach(checkbox => {
        checkbox.checked = !checkbox.checked;
    });
}

function bringIntoView(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.scrollIntoView({ behavior: 'instant', block: 'start' });
    }
}

function loadEmbedded(src, elementId) {
    if (!src || !elementId) {
        console.error("Source URL or element ID is missing.");
        return;
    }

    const targetElement = document.getElementById(elementId);
    if (!targetElement) {
        console.error(`Element with ID "${elementId}" not found.`);
        return;
    }

    fetch(src)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load content from ${src}: ${response.status} ${response.statusText}`);
            }
            return response.text();
        })
        .then(data => {
            targetElement.outerHTML = data;
        })
        .catch(error => {
            console.error("Error loading embedded content:", error);
            targetElement.outerHTML = `Error loading embedded content.`;
        });
}

document.addEventListener("click", function(event) {
    const menu = document.getElementsByClassName('menu')[0];

    if (!menu) return;

    if (event.target.closest("#logo")) {
        const onStartPage = ["/start/ctl", "/start", "/"].includes(window.location.pathname);
        if (!onStartPage) menu.classList.toggle('hidden');
    }

    if (event.target.closest("details") || event.target.closest(".execute")) {
        const onStartPage = ["/start/ctl", "/start", "/"].includes(window.location.pathname);
        if (!onStartPage) menu.classList.add('hidden');
    }
});

// Sound: client-side progress time interpolation
(function () {
    function _fmtMs(ms) {
        const s = Math.floor(ms / 1000);
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }
    setInterval(function () {
        const el = document.getElementById('sound_progress_time');
        if (!el) return;
        const raw = el.dataset.interp;
        if (!raw) return;
        const parts = raw.split(',');
        if (parts.length < 4) return;
        const progressMs = parseInt(parts[0]);
        const durationMs = parseInt(parts[1]);
        const isPlaying  = parts[2] === '1';
        const serverTs   = parseFloat(parts[3]);
        if (!isPlaying) return;
        const currentMs = progressMs + (Date.now() / 1000 - serverTs) * 1000;
        const clamped   = durationMs > 0 ? Math.min(currentMs, durationMs) : currentMs;
        el.textContent  = durationMs > 0
            ? _fmtMs(clamped) + ' / ' + _fmtMs(durationMs)
            : _fmtMs(clamped);
    }, 1000);
}());
