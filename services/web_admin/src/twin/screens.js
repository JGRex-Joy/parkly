import * as THREE from 'three'

const MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, monospace'
const DISPLAY = 'Orbitron, "Inter", sans-serif'

export const SCREEN_W = 1024
export const SCREEN_H = 512

function hash(str) {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}

function bezel(g, color) {
  g.fillStyle = '#04080e'
  g.fillRect(0, 0, SCREEN_W, SCREEN_H)
  g.strokeStyle = color
  g.lineWidth = 8
  g.shadowColor = color
  g.shadowBlur = 24
  g.strokeRect(14, 14, SCREEN_W - 28, SCREEN_H - 28)
  g.shadowBlur = 0
}

function scanlines(g, alpha = 0.07) {
  g.fillStyle = `rgba(255,255,255,${alpha})`
  for (let y = 20; y < SCREEN_H - 20; y += 6) g.fillRect(20, y, SCREEN_W - 40, 1)
}

/** Entrance LED panel: live availability. */
export function drawEntryScreen(g, free, total) {
  const ok = free > 0
  const color = ok ? '#10b981' : '#ef4444'
  bezel(g, '#06b6d4')
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.fillStyle = '#67e8f9'
  g.shadowColor = '#06b6d4'
  g.shadowBlur = 18
  g.font = `700 54px ${DISPLAY}`
  g.fillText('SLOT AVAILABILITY:', SCREEN_W / 2, 130)
  g.fillStyle = color
  g.shadowColor = color
  g.shadowBlur = 36
  g.font = `800 210px ${DISPLAY}`
  g.fillText(`${free}/${total}`, SCREEN_W / 2, 300)
  g.shadowBlur = 0
  g.fillStyle = ok ? '#6ee7b7' : '#fca5a5'
  g.font = `600 40px ${MONO}`
  g.fillText(ok ? 'WELCOME · PLEASE PROCEED' : 'LOT FULL', SCREEN_W / 2, 436)
  scanlines(g)
}

function drawQr(g, x, y, size, seed) {
  const n = 25
  const cell = size / n
  g.fillStyle = '#f8fafc'
  g.fillRect(x - 14, y - 14, size + 28, size + 28)
  g.fillStyle = '#0a0e14'
  let h = hash(seed) || 1
  const rnd = () => { h ^= h << 13; h >>>= 0; h ^= h >>> 17; h ^= h << 5; h >>>= 0; return h / 4294967296 }
  const finder = (cx, cy) => {
    g.fillRect(x + cx * cell, y + cy * cell, 7 * cell, 7 * cell)
    g.fillStyle = '#f8fafc'
    g.fillRect(x + (cx + 1) * cell, y + (cy + 1) * cell, 5 * cell, 5 * cell)
    g.fillStyle = '#0a0e14'
    g.fillRect(x + (cx + 2) * cell, y + (cy + 2) * cell, 3 * cell, 3 * cell)
  }
  const inFinder = (i, j) => (i < 8 && j < 8) || (i > n - 9 && j < 8) || (i < 8 && j > n - 9)
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      if (!inFinder(i, j) && rnd() > 0.52) g.fillRect(x + i * cell, y + j * cell, cell + 0.5, cell + 0.5)
    }
  }
  finder(0, 0); finder(n - 7, 0); finder(0, n - 7)
}

/**
 * Exit panel. state: { mode: 'idle' } | { mode: 'info', plate, minutes, fee, currency } | { mode: 'success' }
 */
export function drawExitScreen(g, state) {
  if (state.mode === 'idle') {
    g.fillStyle = '#03060b'
    g.fillRect(0, 0, SCREEN_W, SCREEN_H)
    g.strokeStyle = 'rgba(6,182,212,0.28)'
    g.lineWidth = 4
    g.strokeRect(14, 14, SCREEN_W - 28, SCREEN_H - 28)
    g.fillStyle = 'rgba(148,163,184,0.35)'
    g.font = `600 34px ${MONO}`
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    g.fillText('STANDBY', SCREEN_W / 2, SCREEN_H / 2)
    scanlines(g, 0.03)
    return
  }
  if (state.mode === 'success') {
    bezel(g, '#10b981')
    g.fillStyle = 'rgba(16,185,129,0.1)'
    g.fillRect(20, 20, SCREEN_W - 40, SCREEN_H - 40)
    g.strokeStyle = '#10b981'
    g.lineWidth = 18
    g.lineCap = 'round'
    g.lineJoin = 'round'
    g.shadowColor = '#10b981'
    g.shadowBlur = 30
    g.beginPath()
    g.moveTo(SCREEN_W / 2 - 70, 160); g.lineTo(SCREEN_W / 2 - 22, 208); g.lineTo(SCREEN_W / 2 + 74, 108)
    g.stroke()
    g.fillStyle = '#34d399'
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    g.font = `800 72px ${DISPLAY}`
    g.fillText('PAYMENT SUCCESS', SCREEN_W / 2, 300)
    g.shadowBlur = 0
    g.fillStyle = '#a7f3d0'
    g.font = `700 50px ${DISPLAY}`
    g.fillText('GATE OPENING', SCREEN_W / 2, 400)
    scanlines(g)
    return
  }
  bezel(g, '#06b6d4')
  g.textAlign = 'left'
  g.textBaseline = 'alphabetic'
  const col = 70
  g.fillStyle = '#67e8f9'
  g.font = `600 28px ${MONO}`
  g.fillText('PLATE', col, 100)
  g.fillStyle = '#ffffff'
  g.shadowColor = 'rgba(255,255,255,.6)'
  g.shadowBlur = 14
  g.font = `700 76px ${MONO}`
  g.fillText(state.plate, col, 176, 520)
  g.shadowBlur = 0
  g.fillStyle = '#67e8f9'
  g.font = `600 28px ${MONO}`
  g.fillText('DURATION', col, 244)
  g.fillStyle = '#e2e8f0'
  g.font = `700 54px ${MONO}`
  g.fillText(state.minutesText, col, 304)
  g.fillStyle = '#67e8f9'
  g.font = `600 28px ${MONO}`
  g.fillText('TOTAL FEE', col, 372)
  g.fillStyle = '#fbbf24'
  g.shadowColor = '#f59e0b'
  g.shadowBlur = 22
  g.font = `800 78px ${DISPLAY}`
  g.fillText(`${state.fee} ${state.currency}`, col, 452, 540)
  g.shadowBlur = 0
  drawQr(g, 690, 96, 250, state.plate)
  g.fillStyle = '#94a3b8'
  g.textAlign = 'center'
  g.font = `600 26px ${MONO}`
  g.fillText('SCAN TO PAY', 815, 420)
  scanlines(g, 0.05)
}

/** Canvas-backed emissive screen plane. */
export function makeScreenTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = SCREEN_W
  canvas.height = SCREEN_H
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return { canvas, ctx: canvas.getContext('2d'), tex }
}
