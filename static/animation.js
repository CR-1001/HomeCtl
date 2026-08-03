/* This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
   Distributed under terms of the GPL3 license. */

/* Background animation: twinkling stars (~5% drift) + colorful tiles and spheres. */

function rand(a, b) { return a + Math.random() * (b - a); }

/* ---- Stars ---- */

function initScene() {
    const grid = document.querySelector('.background-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const W = window.innerWidth, H = window.innerHeight;
    const stars = [];

    for (let i = 0; i < 15; i++) {
        const el  = document.createElement('div');
        const dur = rand(8, 30);
        el.className = 'bg-star';
        Object.assign(el.style, {
            left:              `${rand(0, W)}px`,
            top:               `${rand(0, H)}px`,
            animationDuration: `${dur}s`,
            animationDelay:    `${rand(-dur, 0)}s`,
        });
        grid.appendChild(el);
        stars.push(el);
    }
}

/* ---- Colorful tiles / spheres ---- */

let colorBase = "#00FFFF";
let colorBasePart = 0;
let randomX = 0, randomY = 0;
const tilesToCreate = 8;

function getRandomColor() {
    return '#' + Array.from({ length: 6 }, () => '0123456789ABCDEF'[Math.floor(Math.random() * 16)]).join('');
}

function combineColors(color1, color2) {
    return '#' + [color1.slice(1, 3), color2.slice(3, 5), color1.slice(5, 7)]
        .map((part, i) => i === colorBasePart ? color2.slice(i * 2 + 1, i * 2 + 3) : part)
        .join('');
}

function updateBaseColor() {
    const second = new Date().getSeconds();
    const baseColors = ["#FF0000", "#FFFF00", "#00FF00", "#00FFFF", "#0000FF", "#FF00FF"];
    const interval = Math.floor(second / 10);
    colorBase = (Math.random() < 0.05) ? "#000000" :
        (Math.random() < 0.5) ? combineColors(colorBase, getRandomColor()) : baseColors[interval];
    if (Math.random() < 0.3) colorBasePart = Math.floor(Math.random() * 3);
}

function adjustTileSize(tile, size) {
    const scale = Math.random() < 0.6 ? 0.5 : 0.3;
    tile.style.width  = `${size * scale}px`;
    tile.style.height = `${size * scale}px`;
}

function positionTile(tile, size) {
    tile.style.position = 'absolute';
    tile.style.width    = `${size}px`;
    tile.style.height   = `${size}px`;
    randomX = Math.random() < 0.5 ? randomX : Math.random() * (window.innerWidth  - size);
    randomY = Math.random() < 0.5 ? randomY : Math.random() * (window.innerHeight - size);
    tile.style.left = `${randomX}px`;
    tile.style.top  = `${randomY}px`;
}

function createTile() {
    const grid     = document.querySelector('.background-grid');
    const tileSize = Math.min(window.innerWidth, window.innerHeight) * ((Math.random() * 80 + 30) / 100);
    const tile     = document.createElement('div');
    tile.classList.add('tile');
    if      (Math.random() < 0.5) tile.classList.add('tile-round');
    else if (Math.random() < 0.3) adjustTileSize(tile, tileSize);
    positionTile(tile, tileSize);
    tile.style.backgroundColor = combineColors(colorBase, getRandomColor());
    updateBaseColor();
    grid.appendChild(tile);
}

function duplicateTiles() {
    const grid  = document.querySelector('.background-grid');
    const tiles = Array.from(grid.querySelectorAll('.tile'));
    const count = Math.floor(tiles.length * 0.7);
    for (let i = 0; i < count; i++) {
        const orig  = tiles[Math.floor(Math.random() * tiles.length)];
        const clone = orig.cloneNode(true);
        const w     = parseFloat(orig.style.width  || 0);
        const h     = parseFloat(orig.style.height || 0);
        const mul   = [0.2, 0.4, 0.6][Math.floor(Math.random() * 3)];
        const t     = Math.random();
        let ox = 0, oy = 0;
        if      (t < 0.25) oy = h * mul * (Math.random() < 0.5 ? 1 : -1);
        else if (t < 0.5)  ox = w * mul * (Math.random() < 0.5 ? 1 : -1);
        else { ox = w * mul * (Math.random() < 0.5 ? 1 : -1);
               oy = h * mul * (Math.random() < 0.5 ? 1 : -1); }
        clone.style.left = `${parseFloat(orig.style.left || 0) + ox}px`;
        clone.style.top  = `${parseFloat(orig.style.top  || 0) + oy}px`;
        grid.appendChild(clone);
    }
}

function initializeGrid() {
    const grid  = document.querySelector('.background-grid');
    const tiles = grid.querySelectorAll('.tile');
    if (tiles.length === 0) {
        for (let i = 0; i < tilesToCreate; i++) createTile();
    }
}

/* ---- Init ---- */

document.addEventListener('DOMContentLoaded', () => {
    initScene();
    initializeGrid();
    duplicateTiles();
});
