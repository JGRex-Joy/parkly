import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { gsap } from 'gsap'

import { createCar } from './carFactory.js'
import { drawEntryScreen, drawExitScreen, makeScreenTexture } from './screens.js'
import { fmtMinutes, hmsToMinutes } from '../lib/format.js'
import {
  COLORS, SLOT_COUNT, SLOT_X, SLOT_Z, SLOT_W, SLOT_D, LANE_Z, LANE_W, GATE_X, GATE_ARM_LEN,
  STOP_GAP, WAIT_X, QUEUE_GAP, SPAWN_X, ROAD_END, PLATFORM_HALF,
} from './constants.js'

const APPROACH_SPEED = 11 // units / s on the long access road
const LANE_SPEED = 7
const GATE_TIME = 0.9
const FRAME_T = 0.12
const HEADING_E = 0 // nose along +x
const HEADING_SLOT = -Math.PI / 2 // nose toward +z (parked rear-in)

// ---------------------------------------------------------------- helpers
function bezier(p0, p1, p2, p3, t) {
  const u = 1 - t
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t
  return {
    x: a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
    z: a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
  }
}
function bezierTangent(p0, p1, p2, p3, t) {
  const u = 1 - t
  const a = 3 * u * u, b = 6 * u * t, c = 3 * t * t
  return {
    x: a * (p1[0] - p0[0]) + b * (p2[0] - p1[0]) + c * (p3[0] - p2[0]),
    z: a * (p1[1] - p0[1]) + b * (p2[1] - p1[1]) + c * (p3[1] - p2[1]),
  }
}
// Car local +X is the nose; rotation.y = atan2(-fz, fx) maps a forward vector (fx, fz) to a heading.
const headingOf = (fx, fz) => Math.atan2(-fz, fx)

function tweenColor(color, hex, duration = 0.5) {
  const target = new THREE.Color(hex)
  return gsap.to(color, { r: target.r, g: target.g, b: target.b, duration, ease: 'power2.out', overwrite: 'auto' })
}

/** Serialises async tasks (a shared physical resource such as the gate or the driving lane). */
class Mutex {
  constructor() { this.tail = Promise.resolve() }
  run(fn) {
    const result = this.tail.then(fn)
    this.tail = result.then(() => {}, () => {})
    return result
  }
}

function makeLabelTexture(text) {
  const c = document.createElement('canvas')
  c.width = c.height = 256
  const g = c.getContext('2d')
  g.font = '700 120px Orbitron, sans-serif'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.shadowColor = 'rgba(6,182,212,.9)'
  g.shadowBlur = 18
  g.fillStyle = '#e2e8f0'
  g.fillText(text, 128, 128)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

function makeBannerTexture(text, color = '#22d3ee') {
  const c = document.createElement('canvas')
  c.width = 512; c.height = 128
  const g = c.getContext('2d')
  g.font = '700 54px Orbitron, sans-serif'
  g.textAlign = 'center'; g.textBaseline = 'middle'
  g.shadowColor = color; g.shadowBlur = 20
  g.fillStyle = color
  g.fillText(text, 256, 66)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function makePlateTexture(plate, slotNo) {
  const c = document.createElement('canvas')
  c.width = 768; c.height = 220
  const g = c.getContext('2d')
  const r = 36, x = 24, y = 24, w = 720, h = 172
  g.beginPath()
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r)
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath()
  g.fillStyle = 'rgba(13,17,23,0.88)'
  g.shadowColor = '#ef4444'; g.shadowBlur = 28
  g.fill()
  g.lineWidth = 7; g.strokeStyle = '#ef4444'; g.stroke()
  g.shadowBlur = 0
  g.fillStyle = '#fca5a5'
  g.font = '600 30px "JetBrains Mono", ui-monospace, monospace'
  g.textAlign = 'left'; g.textBaseline = 'middle'
  g.fillText(`SLOT ${slotNo}`, x + 34, y + 36)
  g.fillStyle = '#ffffff'
  g.font = '700 88px "JetBrains Mono", ui-monospace, monospace'
  g.textAlign = 'center'
  g.shadowColor = 'rgba(255,255,255,.55)'; g.shadowBlur = 12
  g.fillText(plate, 384, y + 108, 650)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

// ---------------------------------------------------------------- scene
export class ParkingTwin {
  constructor(container, { onGateChange, onStats } = {}) {
    this.container = container
    this.onGateChange = onGateChange || (() => {})
    this.onStats = onStats || (() => {})
    this.currency = '₸'
    this.gateState = { entry: 'CLOSED', exit: 'CLOSED' }
    this.slots = []
    this.gates = {}
    this.cams = {}
    this.screens = {}
    this.timelines = new Set()
    this.disposed = false
    this.colorCursor = 0
    this.epoch = 0
    this._resetLogic()

    this._initRenderer()
    this._buildEnvironment()
    this._buildSlots()
    this._buildGates()
    this._buildScreens()
    this._buildCameras()

    this._ro = new ResizeObserver(() => this._onResize())
    this._ro.observe(container)
    this._onResize()
    this._loop = this._loop.bind(this)
    this._raf = requestAnimationFrame(this._loop)

    // canvas text needs the web fonts; redraw the screens once they are available
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => !this.disposed && this._redrawScreens())
    this._emitStats()
    this._refreshExitScreen()
  }

  _resetLogic() {
    this.cars = new Map() // plate -> car record
    this.exitQueue = []
    this.headWaiters = []
    this.waitCar = null
    this.waitQueue = []
    this.entryMutex = new Mutex()
    this.laneMutex = new Mutex()
  }

  // ------------------------------------------------------------ setup
  _initRenderer() {
    const { clientWidth: w, clientHeight: h } = this.container
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setSize(w || 1, h || 1)
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.05
    this.renderer.domElement.style.display = 'block'
    this.container.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(COLORS.base)
    // roads fade into the fog well before the spawn points, so cars never pop in or out
    this.scene.fog = new THREE.Fog(COLORS.base, 42, 90)

    this.camera = new THREE.PerspectiveCamera(45, (w || 1) / (h || 1), 0.1, 300)
    this.defaultCam = { pos: new THREE.Vector3(0, 17.5, 26), target: new THREE.Vector3(0, 0, -0.5) }
    this.camera.position.copy(this.defaultCam.pos)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.target.copy(this.defaultCam.target)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.07
    this.controls.minDistance = 8
    this.controls.maxDistance = 55
    this.controls.maxPolarAngle = Math.PI * 0.485
    this.controls.update()

    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera))
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w || 1, h || 1), 0.6, 0.55, 0.34)
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())
  }

  _buildEnvironment() {
    const s = this.scene

    s.add(new THREE.AmbientLight(0x7083a8, 0.7))
    s.add(new THREE.HemisphereLight(0x3b82f6, 0x0b1020, 0.55))
    const sun = new THREE.DirectionalLight(0xaec6ff, 1.15)
    sun.position.set(-9, 22, 14)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    Object.assign(sun.shadow.camera, { left: -30, right: 30, top: 18, bottom: -18, near: 1, far: 70 })
    sun.shadow.bias = -0.0004
    s.add(sun)
    const cyanA = new THREE.PointLight(COLORS.cyan, 100, 40, 2)
    cyanA.position.set(-14, 6, 5)
    const cyanB = cyanA.clone()
    cyanB.position.set(14, 6, 5)
    s.add(cyanA, cyanB)

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(500, 500),
      new THREE.MeshStandardMaterial({ color: 0x080b11, roughness: 1 }),
    )
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.5
    ground.receiveShadow = true
    s.add(ground)
    const grid = new THREE.GridHelper(500, 250, 0x0e7490, 0x0b2a36)
    grid.position.y = -0.48
    grid.material.transparent = true
    grid.material.opacity = 0.55
    s.add(grid)

    // parking platform
    const platform = new THREE.Mesh(
      new THREE.BoxGeometry(PLATFORM_HALF * 2, 0.5, 15),
      new THREE.MeshStandardMaterial({ color: 0x141b27, roughness: 0.78, metalness: 0.25 }),
    )
    platform.position.set(0, -0.25, -1.5)
    platform.receiveShadow = true
    s.add(platform)

    // extended access roads (entry on the left, exit on the right) running far off-screen
    const roadLen = ROAD_END - PLATFORM_HALF
    const roadMat = new THREE.MeshStandardMaterial({ color: 0x0f151f, roughness: 0.9 })
    const edgeMat = new THREE.MeshBasicMaterial({ color: 0x0e7490 })
    for (const sx of [-1, 1]) {
      const cx = sx * (PLATFORM_HALF + roadLen / 2)
      const road = new THREE.Mesh(new THREE.BoxGeometry(roadLen, 0.5, LANE_W), roadMat)
      road.position.set(cx, -0.25, LANE_Z)
      road.receiveShadow = true
      s.add(road)
      for (const dz of [-LANE_W / 2, LANE_W / 2]) {
        const edge = new THREE.Mesh(new THREE.BoxGeometry(roadLen, 0.04, 0.1), edgeMat)
        edge.position.set(cx, 0.02, LANE_Z + dz)
        s.add(edge)
      }
    }

    // neon platform rim
    const rimMat = new THREE.MeshBasicMaterial({ color: COLORS.cyan })
    const rim = (w, d, x, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.05, d), rimMat)
      m.position.set(x, 0.02, z)
      s.add(m)
    }
    rim(PLATFORM_HALF * 2, 0.12, 0, -9)
    rim(PLATFORM_HALF * 2, 0.12, 0, 6)
    rim(0.12, 15, -PLATFORM_HALF, -1.5)
    rim(0.12, 15, PLATFORM_HALF, -1.5)

    // centre-line dashes along the whole lane + both roads (instanced)
    const dashCount = Math.floor((ROAD_END * 2) / 2.6)
    const dashes = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1.1, 0.02, 0.11), new THREE.MeshBasicMaterial({ color: 0x155e75 }), dashCount,
    )
    const m4 = new THREE.Matrix4()
    for (let i = 0; i < dashCount; i++) {
      m4.setPosition(-ROAD_END + i * 2.6, 0.015, LANE_Z)
      dashes.setMatrixAt(i, m4)
    }
    s.add(dashes)

    // slot numbers painted on the floor
    for (let i = 0; i < SLOT_COUNT; i++) {
      const label = new THREE.Mesh(
        new THREE.PlaneGeometry(1.7, 1.7),
        new THREE.MeshBasicMaterial({
          map: makeLabelTexture(String(i + 1)), transparent: true, opacity: 0.85, depthWrite: false,
        }),
      )
      label.rotation.x = -Math.PI / 2
      label.position.set(SLOT_X[i], 0.03, SLOT_Z - 1.9)
      s.add(label)
    }

    // light poles along the platform and both access roads
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.6, metalness: 0.6, flatShading: true })
    const lampMat = new THREE.MeshBasicMaterial({ color: 0x67e8f9 })
    const poleGeo = new THREE.CylinderGeometry(0.1, 0.14, 4.2, 6)
    const lampGeo = new THREE.OctahedronGeometry(0.28, 0)
    const pole = (x, z) => {
      const p = new THREE.Mesh(poleGeo, poleMat)
      p.position.set(x, 2.1, z)
      p.castShadow = true
      const l = new THREE.Mesh(lampGeo, lampMat)
      l.position.set(x, 4.4, z)
      s.add(p, l)
    }
    for (const [x, z] of [[-22, -8.2], [22, -8.2], [-22, 5.2], [22, 5.2]]) pole(x, z)
    for (let x = PLATFORM_HALF + 10; x < ROAD_END; x += 12) {
      pole(x, LANE_Z + LANE_W / 2 + 1.2)
      pole(-x, LANE_Z + LANE_W / 2 + 1.2)
    }

    // low-poly skyline behind the lot
    let seed = 7
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    const bMat = new THREE.MeshStandardMaterial({ color: 0x0d131c, roughness: 0.7, metalness: 0.3, flatShading: true })
    const winMats = [0x06b6d4, 0x10b981, 0x6366f1].map((c) => new THREE.MeshBasicMaterial({ color: c }))
    for (let i = 0; i < 26; i++) {
      const w = 2.2 + rand() * 3, h = 3 + rand() * 11, d = 2.5 + rand() * 3
      const x = -56 + i * 4.4 + rand() * 1.5
      const z = -15 - rand() * 6
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), bMat)
      b.position.set(x, h / 2 - 0.5, z)
      s.add(b)
      const rows = Math.floor(h / 1.6)
      for (let r = 1; r < rows; r++) {
        if (rand() < 0.35) continue
        const strip = new THREE.Mesh(new THREE.BoxGeometry(w * 0.82, 0.07, 0.05), winMats[Math.floor(rand() * 3)])
        strip.position.set(x, r * 1.6 - 0.5, z + d / 2 + 0.03)
        s.add(strip)
      }
    }
  }

  _buildSlots() {
    for (let i = 0; i < SLOT_COUNT; i++) {
      const x = SLOT_X[i]
      const mats = []
      const group = new THREE.Group()
      group.position.set(x, 0, SLOT_Z)

      const frameMat = new THREE.MeshBasicMaterial({ color: COLORS.free })
      mats.push(frameMat)
      const bars = [
        [SLOT_W, FRAME_T, 0, -SLOT_D / 2],
        [SLOT_W, FRAME_T, 0, SLOT_D / 2],
        [FRAME_T, SLOT_D, -SLOT_W / 2, 0],
        [FRAME_T, SLOT_D, SLOT_W / 2, 0],
      ]
      for (const [w, d, bx, bz] of bars) {
        const bar = new THREE.Mesh(new THREE.BoxGeometry(w, 0.07, d), frameMat)
        bar.position.set(bx, 0.04, bz)
        group.add(bar)
      }
      const fillMat = new THREE.MeshBasicMaterial({
        color: COLORS.free, transparent: true, opacity: 0.13, depthWrite: false,
      })
      mats.push(fillMat)
      const fill = new THREE.Mesh(new THREE.PlaneGeometry(SLOT_W - 0.2, SLOT_D - 0.2), fillMat)
      fill.rotation.x = -Math.PI / 2
      fill.position.y = 0.012
      group.add(fill)

      const light = new THREE.PointLight(COLORS.free, 14, 9, 2)
      light.position.set(0, 2.4, 0.4)
      group.add(light)
      this.scene.add(group)

      // status = what the floor shows; owner = plate that reserved the slot (event received)
      this.slots.push({ index: i, mats, light, status: 'FREE', owner: null })
    }
  }

  _buildGates() {
    const postMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5, metalness: 0.7, flatShading: true })
    const armMat = new THREE.MeshStandardMaterial({
      color: 0xf8fafc, emissive: 0x7f1d1d, emissiveIntensity: 0.6, roughness: 0.4, flatShading: true,
    })
    const stripeMat = new THREE.MeshBasicMaterial({ color: 0xef4444 })

    for (const name of ['entry', 'exit']) {
      const gx = GATE_X[name]
      const group = new THREE.Group()
      group.position.set(gx, 0, 0)

      const post = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.7, 0.7), postMat)
      post.position.set(0, 0.85, LANE_Z + LANE_W / 2 + 0.3)
      post.castShadow = true
      const receiver = new THREE.Mesh(new THREE.BoxGeometry(0.35, 1.0, 0.35), postMat)
      receiver.position.set(0, 0.5, LANE_Z - LANE_W / 2 - 0.2)
      group.add(post, receiver)

      const indMat = new THREE.MeshBasicMaterial({ color: COLORS.occupied })
      const ind = new THREE.Mesh(new THREE.SphereGeometry(0.17, 10, 8), indMat)
      ind.position.set(0, 1.95, LANE_Z + LANE_W / 2 + 0.3)
      group.add(ind)

      // pivot at the post; arm extends toward -z across the lane. rotation.x = +90deg lifts it upright.
      const pivot = new THREE.Group()
      pivot.position.set(0, 1.25, LANE_Z + LANE_W / 2 - 0.05)
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, GATE_ARM_LEN), armMat)
      arm.position.z = -GATE_ARM_LEN / 2
      arm.castShadow = true
      pivot.add(arm)
      for (let k = 0; k < 4; k++) {
        const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.175, 0.175, 0.5), stripeMat)
        stripe.position.z = -0.6 - k * 1.15
        pivot.add(stripe)
      }
      group.add(pivot)

      const banner = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: makeBannerTexture(name === 'entry' ? 'ENTRANCE' : 'EXIT'), transparent: true, depthWrite: false }),
      )
      banner.scale.set(3.4, 0.85, 1)
      banner.position.set(0, 2.9, LANE_Z + LANE_W / 2 + 0.3)
      group.add(banner)

      this.scene.add(group)
      this.gates[name] = { pivot, indMat, tween: null }
    }
  }

  /** Physical LED panels beside each gate (back side of the lane, facing the viewer). */
  _buildScreens() {
    const W = 5.8, H = 2.9, Y = 3.7, Z = -1.7
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x0b111b, roughness: 0.5, metalness: 0.8, flatShading: true })
    const neon = new THREE.MeshBasicMaterial({ color: COLORS.cyan })

    for (const name of ['entry', 'exit']) {
      const x = GATE_X[name]
      const { canvas, ctx, tex } = makeScreenTexture()
      const mat = new THREE.MeshBasicMaterial({ map: tex, toneMapped: false })
      const group = new THREE.Group()
      group.position.set(x, 0, Z)

      const back = new THREE.Mesh(new THREE.BoxGeometry(W + 0.4, H + 0.4, 0.22), frameMat)
      back.position.set(0, Y, -0.06)
      back.castShadow = true
      const panel = new THREE.Mesh(new THREE.PlaneGeometry(W, H), mat)
      panel.position.set(0, Y, 0.07)
      group.add(back, panel)

      for (const [bw, bh, bx, by] of [
        [W + 0.4, 0.06, 0, Y + H / 2 + 0.2], [W + 0.4, 0.06, 0, Y - H / 2 - 0.2],
        [0.06, H + 0.4, -(W / 2 + 0.2), Y], [0.06, H + 0.4, W / 2 + 0.2, Y],
      ]) {
        const bar = new THREE.Mesh(new THREE.BoxGeometry(bw, bh, 0.06), neon)
        bar.position.set(bx, by, 0.06)
        group.add(bar)
      }
      for (const px of [-W / 2 + 0.3, W / 2 - 0.3]) {
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.22, Y - H / 2, 0.22), frameMat)
        post.position.set(px, (Y - H / 2) / 2 - 0.1, -0.06)
        group.add(post)
      }
      this.scene.add(group)
      this.screens[name] = { canvas, ctx, tex }
    }
  }

  _redrawScreens() {
    this._drawEntryScreen()
    this._refreshExitScreen()
  }

  _drawEntryScreen() {
    const free = this.slots.filter((s) => s.status === 'FREE').length
    const sc = this.screens.entry
    drawEntryScreen(sc.ctx, free, this.slots.length)
    sc.tex.needsUpdate = true
  }

  _exitScreenState() {
    const head = this.exitQueue[0]
    if (!head || !head.arrived) return { mode: 'idle' }
    if (head.phase === 'PAYING') return { mode: 'success' }
    const info = head.info || {}
    const minutes = hmsToMinutes(info.duration)
    return {
      mode: 'info',
      plate: head.plate,
      minutesText: minutes == null ? '—' : fmtMinutes(minutes),
      fee: info.fee ?? 0,
      currency: this.currency,
    }
  }

  _refreshExitScreen() {
    const sc = this.screens.exit
    drawExitScreen(sc.ctx, this._exitScreenState())
    sc.tex.needsUpdate = true
  }

  setCurrency(symbol) {
    if (this.currency === symbol) return
    this.currency = symbol
    this._refreshExitScreen()
  }

  /** Decorative low-poly surveillance cameras on poles next to each gate. */
  _buildCameras() {
    const metal = new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.5, metalness: 0.7, flatShading: true })
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0xcbd5e1, roughness: 0.4, metalness: 0.6, flatShading: true })
    const glassMat = new THREE.MeshBasicMaterial({ color: 0x0891b2 })
    for (const name of ['entry', 'exit']) {
      const x = GATE_X[name] - STOP_GAP
      const z = LANE_Z + LANE_W / 2 + 1.3
      const group = new THREE.Group()
      group.position.set(x, 0, z)

      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.42, 0.25, 8), metal)
      base.position.y = 0.12
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, 3.6, 8), metal)
      pole.position.y = 1.9
      pole.castShadow = true
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.1, 0.1), metal)
      arm.position.set(0, 3.7, 0)

      const head = new THREE.Group() // lens points along local +x; yaw it toward -z (the lane)
      head.position.set(0, 3.6, 0)
      head.rotation.order = 'YZX'
      head.rotation.y = headingOf(0, -1)
      const body = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.46, 0.52), bodyMat)
      body.castShadow = true
      const hood = new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.08, 0.6), metal)
      hood.position.y = 0.27
      const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.2, 0.2, 10), glassMat)
      lens.rotation.z = Math.PI / 2
      lens.position.x = 0.55
      const ledMat = new THREE.MeshBasicMaterial({ color: 0xff2e3d })
      const led = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 6), ledMat)
      led.position.set(-0.3, 0.2, 0.28)
      head.add(body, hood, lens, led)
      head.rotation.z = -0.32 // tilt the nose down toward the stopping point
      group.add(base, pole, arm, head)

      const flash = new THREE.PointLight(0xbff3ff, 0, 11, 2)
      flash.position.set(0.4, 3.4, -0.6)
      group.add(flash)
      gsap.to(ledMat.color, { r: 0.25, g: 0.02, b: 0.04, duration: 0.9, yoyo: true, repeat: -1, ease: 'sine.inOut' })

      this.scene.add(group)
      this.cams[name] = { flash, glassMat }
    }
  }

  /** OCR shutter flash on a gate camera. */
  _flash(cam) {
    if (!cam) return
    gsap.timeline()
      .to(cam.flash, { intensity: 70, duration: 0.06 })
      .to(cam.flash, { intensity: 0, duration: 0.45, ease: 'power2.out' })
    gsap.fromTo(cam.glassMat.color, { r: 1, g: 1, b: 1 }, { r: 0.03, g: 0.72, b: 0.83, duration: 0.6, overwrite: 'auto' })
  }

  // ------------------------------------------------------------ rendering
  _onResize() {
    if (this.disposed) return
    const w = this.container.clientWidth, h = this.container.clientHeight
    if (!w || !h) return
    this.renderer.setSize(w, h)
    this.composer.setSize(w, h)
    this.bloom.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.fov = w / h < 1.1 ? 66 : w / h < 1.5 ? 55 : 45
    this.camera.updateProjectionMatrix()
  }

  _loop() {
    if (this.disposed) return
    this._raf = requestAnimationFrame(this._loop)
    this.controls.update()
    this.composer.render()
  }

  resetCamera() {
    gsap.to(this.camera.position, { ...this.defaultCam.pos, duration: 1.1, ease: 'power3.inOut' })
    gsap.to(this.controls.target, {
      x: this.defaultCam.target.x, y: this.defaultCam.target.y, z: this.defaultCam.target.z,
      duration: 1.1, ease: 'power3.inOut',
    })
  }

  // ------------------------------------------------------------ slots / stats
  _paintSlot(i, status, instant = false) {
    const slot = this.slots[i]
    slot.status = status
    const hex = status === 'OCCUPIED' ? COLORS.occupied : COLORS.free
    if (instant) {
      for (const m of slot.mats) { gsap.killTweensOf(m.color); m.color.setHex(hex) }
      gsap.killTweensOf(slot.light.color)
      slot.light.color.setHex(hex)
    } else {
      for (const m of slot.mats) tweenColor(m.color, hex, 0.5)
      tweenColor(slot.light.color, hex, 0.5)
    }
    gsap.to(slot.light, { intensity: status === 'OCCUPIED' ? 26 : 14, duration: instant ? 0 : 0.5, overwrite: 'auto' })
    this._emitStats()
  }

  _emitStats() {
    const slots = this.slots.map((s) => ({ status: s.status, plate: s.status === 'OCCUPIED' ? s.owner : null }))
    const free = slots.filter((s) => s.status === 'FREE').length
    this.onStats({ free, total: slots.length, slots })
    if (this.screens.entry) this._drawEntryScreen()
  }

  // ------------------------------------------------------------ badge
  _showBadge(car, slotNo) {
    this._hideBadge(car, true)
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makePlateTexture(car.plate, slotNo), transparent: true, depthTest: false, depthWrite: false,
    }))
    sprite.renderOrder = 20
    sprite.position.set(0, 2.9, 0)
    sprite.scale.set(0.001, 0.001, 1)
    car.group.add(sprite)
    car.badge = sprite
    gsap.to(sprite.scale, { x: 3.9, y: 1.12, duration: 0.55, ease: 'back.out(1.8)' })
    car.bob = gsap.to(sprite.position, { y: 3.15, duration: 1.3, ease: 'sine.inOut', yoyo: true, repeat: -1 })
  }

  _hideBadge(car, instant = false) {
    if (!car.badge) return
    const sprite = car.badge
    car.badge = null
    car.bob && car.bob.kill()
    const dispose = () => {
      car.group.remove(sprite)
      sprite.material.map.dispose()
      sprite.material.dispose()
    }
    if (instant) { dispose(); return }
    gsap.to(sprite.scale, { x: 0.001, y: 0.001, duration: 0.3, ease: 'back.in(2)', onComplete: dispose })
  }

  // ------------------------------------------------------------ cars
  _newCar(plate) {
    const c = createCar(this.colorCursor++)
    const car = {
      plate, ...c, phase: 'NEW', slotIndex: -1, chain: Promise.resolve(), lastX: 0, lastZ: 0,
      arrived: false, exitRequested: false, departing: false, info: null, badge: null, bob: null,
    }
    this._placeCar(car, SPAWN_X.entry, LANE_Z, HEADING_E) // far end of the entry road, hidden in the fog
    this.scene.add(c.group)
    this.cars.set(plate, car)
    return car
  }

  _placeCar(car, x, z, heading) {
    car.group.position.set(x, 0, z)
    car.group.rotation.y = heading
    car.lastX = x
    car.lastZ = z
  }

  _moveCar(car, x, z, heading) {
    const dx = x - car.lastX, dz = z - car.lastZ
    const dist = Math.hypot(dx, dz)
    if (dist > 0) {
      const dir = Math.sign(dx * Math.cos(heading) - dz * Math.sin(heading)) || 1
      for (const w of car.wheels) w.rotation.z -= (dir * dist) / 0.36
    }
    this._placeCar(car, x, z, heading)
  }

  _removeCar(car) {
    this._hideBadge(car, true)
    this.scene.remove(car.group)
    car.bodyMat.dispose()
    this.cars.delete(car.plate)
    const qi = this.exitQueue.indexOf(car)
    if (qi >= 0) this.exitQueue.splice(qi, 1)
    if (this.waitCar === car) this._releaseWait(car)
  }

  _queue(car, task) {
    const epoch = this.epoch
    car.chain = car.chain
      .then(() => (epoch === this.epoch && !this.disposed ? task() : null))
      .catch((err) => console.error('[ParkingTwin]', err))
    return car.chain
  }

  _track(anim) {
    this.timelines.add(anim)
    return anim
  }

  _timeline(resolve) {
    const tl = this._track(gsap.timeline({
      onComplete: () => { this.timelines.delete(tl); resolve() },
    }))
    return tl
  }

  /** Straight drive along the lane between two x positions. */
  _straight(tl, car, from, to, speed, ease, onProgress) {
    const heading = to >= from ? HEADING_E : Math.PI
    const p = { x: from }
    tl.to(p, {
      x: to,
      duration: Math.max(Math.abs(to - from) / speed, 0.05),
      ease,
      onUpdate: () => {
        this._moveCar(car, p.x, LANE_Z, heading)
        onProgress && onProgress(p.x)
      },
    })
  }

  // ------------------------------------------------------------ gates
  _setGateState(name, state) {
    this.gateState = { ...this.gateState, [name]: state }
    this.onGateChange(this.gateState)
  }

  _gateTween(name, open, onDone) {
    const g = this.gates[name]
    g.tween && g.tween.kill()
    this._setGateState(name, open ? 'OPENING' : 'CLOSING')
    tweenColor(g.indMat.color, open ? COLORS.free : COLORS.occupied, 0.35)
    g.tween = gsap.to(g.pivot.rotation, {
      x: open ? Math.PI / 2 : 0, // 90 degrees
      duration: GATE_TIME,
      ease: open ? 'power2.out' : 'bounce.out',
      onComplete: () => {
        this._setGateState(name, open ? 'OPEN' : 'CLOSED')
        onDone && onDone()
      },
    })
    return g.tween
  }

  // ------------------------------------------------------------ lane waiting spot
  _acquireWait(car) {
    return new Promise((resolve) => {
      const attempt = () => {
        if (!this.waitCar) { this.waitCar = car; resolve() } else this.waitQueue.push(attempt)
      }
      attempt()
    })
  }

  _releaseWait(car) {
    if (this.waitCar !== car) return
    this.waitCar = null
    const next = this.waitQueue.shift()
    next && next()
  }

  // ------------------------------------------------------------ exit queue
  _queueX(i) {
    return GATE_X.exit - STOP_GAP - i * QUEUE_GAP
  }

  _awaitHead(car) {
    return new Promise((resolve) => {
      const check = () => (this.exitQueue[0] === car ? resolve() : this.headWaiters.push(check))
      check()
    })
  }

  _notifyHead() {
    const waiting = this.headWaiters.splice(0)
    waiting.forEach((fn) => fn())
  }

  _settleQueuePos(car) {
    const i = this.exitQueue.indexOf(car)
    if (i < 0 || !car.arrived) return
    const x = this._queueX(i)
    if (car.lastX >= x - 0.05) return
    const p = { x: car.lastX }
    const tw = this._track(gsap.to(p, {
      x, duration: (x - p.x) / 5 + 0.3, ease: 'power1.inOut',
      onUpdate: () => this._moveCar(car, p.x, LANE_Z, HEADING_E),
      onComplete: () => this.timelines.delete(tw),
    }))
  }

  _leaveQueue(car) {
    const i = this.exitQueue.indexOf(car)
    if (i >= 0) this.exitQueue.splice(i, 1)
    this.exitQueue.forEach((c) => this._settleQueuePos(c))
    this._notifyHead()
  }

  // ------------------------------------------------------------ PUBLIC: events from the backend
  handleEvent(msg, slotIndex = -1) {
    if (this.disposed) return
    switch (msg.event) {
      case 'ENTRY_OCR': this._onEntry(msg.plate); break
      case 'SLOT_OCCUPIED': this._onSlotOccupied(msg.plate, slotIndex); break
      case 'EXIT_OCR': this._onExitOcr(msg.plate, slotIndex, msg.duration, msg.fee); break
      case 'PAYMENT_CONFIRMED': this._onPayment(msg.plate); break
      case 'SLOT_RELEASED': this._onSlotReleased(slotIndex); break
      default: break
    }
  }

  // Event 1 - ENTRY_OCR: car spawns off-screen, drives to the entrance gate, gate opens, car enters the lane and waits
  _onEntry(plate) {
    if (!plate || this.cars.has(plate)) return
    const car = this._newCar(plate)
    car.phase = 'APPROACH'
    this._queue(car, () => this.entryMutex.run(() => this._animEntry(car)))
  }

  _animEntry(car) {
    return new Promise((resolve) => {
      const tl = this._timeline(resolve)
      const gx = GATE_X.entry
      const stopX = gx - STOP_GAP

      this._straight(tl, car, SPAWN_X.entry, stopX, APPROACH_SPEED, 'power2.out')
      tl.add(() => { car.phase = 'AT_ENTRY'; this._flash(this.cams.entry) })
      tl.add(() => {}, '+=0.8')

      // if the lane spot is still taken by the previous car, hold at the closed gate until it frees up
      tl.add(() => {
        tl.pause()
        this._acquireWait(car).then(() => tl.resume())
      })

      tl.add(() => this._gateTween('entry', true))
      tl.add(() => {}, `+=${GATE_TIME + 0.2}`)

      let closing = false
      this._straight(tl, car, stopX, WAIT_X, 4.2, 'power1.inOut', (x) => {
        if (!closing && x > gx + 3.4) { // entrance gate closes behind the car
          closing = true
          this._gateTween('entry', false)
        }
      })
      tl.add(() => { car.phase = 'WAITING' })
    })
  }

  // Event 2 - SLOT_OCCUPIED: reverse into the slot, slot -> RED, plate badge, entrance screen count
  _onSlotOccupied(plate, idx) {
    if (!plate || idx < 0 || idx >= SLOT_COUNT) return
    const slot = this.slots[idx]
    if (slot.owner && slot.owner !== plate) {
      console.warn(`[ParkingTwin] slot ${idx + 1} already reserved by ${slot.owner}`)
      return
    }
    let car = this.cars.get(plate)
    // sticky lock: a car that is already parked / parking / leaving never re-runs its arrival
    if (car && (car.slotIndex >= 0 || car.exitRequested || car.departing ||
        ['PARKING', 'PARKED', 'EXITING', 'AT_EXIT', 'PAYING'].includes(car.phase))) return
    if (!car) { // sensor event without a preceding ENTRY_OCR: take the car from the waiting spot
      car = this._newCar(plate)
      this._placeCar(car, WAIT_X, LANE_Z, HEADING_E)
      car.phase = 'WAITING'
      if (!this.waitCar) this.waitCar = car
    }
    if (car.slotIndex === idx) return // duplicate event
    slot.owner = plate
    car.slotIndex = idx
    this._queue(car, () => this.laneMutex.run(() => this._animPark(car, idx)))
  }

  _animPark(car, idx) {
    return new Promise((resolve) => {
      this._releaseWait(car)
      car.phase = 'PARKING'
      const sx = SLOT_X[idx]
      const stopX = sx + 3.3
      const tl = this._timeline(resolve)

      // roll forward past the slot, then swing the rear into it
      if (stopX - car.lastX > 0.05) this._straight(tl, car, car.lastX, stopX, LANE_SPEED, 'power1.inOut')
      tl.add(() => {}, '+=0.25')

      const P0 = [stopX, LANE_Z], P1 = [sx - 1.1, LANE_Z], P2 = [sx, 0.9], P3 = [sx, SLOT_Z - 0.4]
      const path = { t: 0 }
      tl.to(path, {
        t: 1,
        duration: 2.9,
        ease: 'power2.inOut',
        onUpdate: () => {
          const p = bezier(P0, P1, P2, P3, path.t)
          const tg = bezierTangent(P0, P1, P2, P3, Math.max(path.t, 0.001))
          this._moveCar(car, p.x, p.z, headingOf(-tg.x, -tg.z)) // reversing: nose opposes travel direction
        },
      })
      tl.add(() => {
        this._paintSlot(idx, 'OCCUPIED') // GREEN -> RED (also refreshes the entrance screen)
        this._showBadge(car, idx + 1)
        car.phase = 'PARKED'
      })
      tl.add(() => {}, '+=0.6')
    })
  }

  // Events 3 + 4 - EXIT_OCR: car leaves the slot, slot -> GREEN, stops at the exit gate, exit screen lights up
  _onExitOcr(plate, idx, duration, fee) {
    let car = plate ? this.cars.get(plate) : null
    if (!car && idx >= 0 && this.slots[idx].owner) car = this.cars.get(this.slots[idx].owner)
    if (!car) {
      if (!plate || idx < 0 || idx >= SLOT_COUNT) return
      car = this._spawnParked(plate, idx) // exit for a car this view never saw arrive
    }
    car.info = { duration, fee }
    if (car.exitRequested) { // repeated read of the same bill
      if (car.arrived) this._refreshExitScreen()
      return
    }
    car.exitRequested = true
    this._queue(car, () => this.laneMutex.run(() => this._animExit(car)))
  }

  _animExit(car) {
    return new Promise((resolve) => {
      this._releaseWait(car)
      const idx = car.slotIndex
      this.exitQueue.push(car)
      const targetX = this._queueX(this.exitQueue.length - 1)
      car.phase = 'EXITING'
      this._hideBadge(car)
      const tl = this._timeline(resolve)

      let startX = car.lastX
      if (idx >= 0) {
        const sx = SLOT_X[idx]
        const p3x = Math.min(sx + 3.6, targetX - 0.3)
        const P0 = [sx, SLOT_Z - 0.4], P1 = [sx, 0.7], P2 = [sx + (p3x - sx) * 0.2, LANE_Z], P3 = [p3x, LANE_Z]
        const path = { t: 0 }
        let freed = false
        tl.to(path, {
          t: 1,
          duration: 2.5,
          ease: 'power2.inOut',
          onUpdate: () => {
            const p = bezier(P0, P1, P2, P3, path.t)
            const tg = bezierTangent(P0, P1, P2, P3, Math.max(path.t, 0.001))
            this._moveCar(car, p.x, p.z, headingOf(tg.x, tg.z))
            if (!freed && p.z > SLOT_Z + SLOT_D / 2) { // clear of the slot: boundary back to GREEN
              freed = true
              const slot = this.slots[idx]
              if (slot.owner === car.plate) slot.owner = null
              car.slotIndex = -1
              this._paintSlot(idx, 'FREE')
            }
          },
        })
        startX = p3x
      }
      if (targetX - startX > 0.05) this._straight(tl, car, startX, targetX, LANE_SPEED, 'power2.out')
      tl.add(() => {
        car.arrived = true
        if (car.phase !== 'PAYING') car.phase = 'AT_EXIT'
        this._flash(this.cams.exit)
        this._refreshExitScreen() // exit display lights up with plate / duration / fee / QR
      })
      tl.add(() => {}, '+=0.4')
    })
  }

  // Event 5 - PAYMENT_CONFIRMED: success message, gate opens, car drives far away and despawns, gate closes, screen idles
  _onPayment(plate) {
    const car = plate ? this.cars.get(plate) : null
    if (!car || car.departing) return
    if (!car.exitRequested) { // exit animation is triggered strictly by EXIT_OCR
      console.warn(`[ParkingTwin] PAYMENT_CONFIRMED for ${plate} without EXIT_OCR ignored`)
      return
    }
    car.departing = true
    const epoch = this.epoch
    this._queue(car, () => this._animDepart(car, epoch))
  }

  _animDepart(car, epoch) {
    return this._awaitHead(car).then(() => {
      if (epoch !== this.epoch || this.disposed) return null
      return new Promise((resolve) => {
        car.phase = 'PAYING'
        this._refreshExitScreen() // PAYMENT SUCCESS / GATE OPENING
        const gx = GATE_X.exit
        const tl = this._timeline(resolve)
        tl.add(() => {}, '+=1.6')
        tl.add(() => this._gateTween('exit', true))
        tl.add(() => {}, `+=${GATE_TIME + 0.2}`)

        let closing = false
        this._straight(tl, car, car.lastX, SPAWN_X.exit, 10, 'power2.in', (x) => {
          if (!closing && x > gx + 3.4) {
            closing = true
            this._leaveQueue(car) // next car in line may advance
            this._gateTween('exit', false, () => this._refreshExitScreen()) // gate shut -> screen back to idle
          }
        })
        tl.add(() => this._removeCar(car)) // despawn once it is far beyond the fog line
      })
    })
  }

  // SLOT_RELEASED is sensor-level noise for the 3D scene: a car that holds a slot is only ever moved by
  // EXIT_OCR. The slot colour is also owned by the car, so a release for an owned slot is ignored.
  _onSlotReleased(idx) {
    if (idx < 0 || idx >= SLOT_COUNT) return
    const slot = this.slots[idx]
    if (slot.owner && this.cars.has(slot.owner)) return // locked: ignore transient FREE
    if (slot.status !== 'FREE') this._paintSlot(idx, 'FREE') // orphan marker with no car
    slot.owner = null
  }

  // ------------------------------------------------------------ PUBLIC: full-state sync (INITIAL_STATE)
  /** state: { slots: [{status, plate}], sessions: [{plate, phase, slotIndex, duration, fee}] } */
  applyState(state) {
    if (this.disposed) return
    // sticky cars: parked cars that the snapshot confirms in the same slot stay untouched (no flicker on resync)
    const keep = new Set()
    ;(state.slots || []).slice(0, SLOT_COUNT).forEach((s, i) => {
      const car = s.plate ? this.cars.get(s.plate) : null
      if (s.status === 'OCCUPIED' && car && car.phase === 'PARKED' && car.slotIndex === i &&
          !car.exitRequested && !car.departing) keep.add(car)
    })
    this.reset(keep)
    ;(state.slots || []).slice(0, SLOT_COUNT).forEach((s, i) => {
      if (s.status === 'OCCUPIED' && s.plate && !this.cars.has(s.plate)) this._spawnParked(s.plate, i)
    })
    let waiting = 0
    for (const sess of state.sessions || []) {
      if (this.cars.has(sess.plate)) continue
      if (sess.phase === 'ENTERING' && waiting < 2) {
        const car = this._newCar(sess.plate)
        this._placeCar(car, WAIT_X - waiting * QUEUE_GAP, LANE_Z, HEADING_E)
        car.phase = 'WAITING'
        if (!this.waitCar) this.waitCar = car
        waiting += 1
      } else if (sess.phase === 'EXITING') {
        const car = this._newCar(sess.plate)
        car.exitRequested = true
        car.arrived = true
        car.phase = 'AT_EXIT'
        car.info = { duration: sess.duration, fee: sess.fee }
        this.exitQueue.push(car)
        this._placeCar(car, this._queueX(this.exitQueue.length - 1), LANE_Z, HEADING_E)
      }
    }
    this._emitStats()
    this._refreshExitScreen()
  }

  _spawnParked(plate, idx) {
    const car = this._newCar(plate)
    this._placeCar(car, SLOT_X[idx], SLOT_Z - 0.4, HEADING_SLOT)
    car.slotIndex = idx
    car.phase = 'PARKED'
    this.slots[idx].owner = plate
    this._paintSlot(idx, 'OCCUPIED', true)
    this._showBadge(car, idx + 1)
    return car
  }

  /** Clean slate: kill animations, remove cars, close gates, all slots free. */
  reset(keep = new Set()) {
    this.epoch++
    for (const tl of this.timelines) tl.kill()
    this.timelines.clear()
    for (const car of [...this.cars.values()]) if (!keep.has(car)) this._removeCar(car)
    this._resetLogic()
    for (const car of keep) { this.cars.set(car.plate, car); car.chain = Promise.resolve() }
    for (const name of ['entry', 'exit']) {
      const g = this.gates[name]
      g.tween && g.tween.kill()
      g.pivot.rotation.x = 0
      gsap.killTweensOf(g.indMat.color)
      g.indMat.color.setHex(COLORS.occupied)
    }
    this.gateState = { entry: 'CLOSED', exit: 'CLOSED' }
    this.onGateChange(this.gateState)
    this.slots.forEach((slot, i) => {
      const kept = [...keep].find((c) => c.slotIndex === i)
      slot.owner = kept ? kept.plate : null
      this._paintSlot(i, kept ? 'OCCUPIED' : 'FREE', true)
    })
    this._emitStats()
    this._refreshExitScreen()
  }

  // ------------------------------------------------------------ teardown
  dispose() {
    this.disposed = true
    cancelAnimationFrame(this._raf)
    this._ro.disconnect()
    for (const tl of this.timelines) tl.kill()
    this.timelines.clear()
    gsap.killTweensOf(this.camera.position)
    gsap.killTweensOf(this.controls.target)
    this.controls.dispose()
    this.scene.traverse((o) => {
      if (o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material]
        mats.forEach((m) => { gsap.killTweensOf(m.color); gsap.killTweensOf(m); m.map && m.map.dispose(); m.dispose() })
      }
      if (o.geometry) o.geometry.dispose()
    })
    this.composer.dispose && this.composer.dispose()
    this.renderer.dispose()
    this.renderer.forceContextLoss()
    this.renderer.domElement.remove()
  }
}
