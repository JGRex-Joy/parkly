import * as THREE from 'three'

// Geometries are built once and shared by every car (low-poly, flat shaded).
const BODY_W = 1.8
const CABIN_W = 1.5

function extrudeProfile(points, depth) {
  const shape = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)))
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false })
  geo.translate(0, 0, -depth / 2)
  return geo
}

let shared = null
function getShared() {
  if (shared) return shared
  const bodyGeo = extrudeProfile(
    [[-1.75, 0.28], [1.75, 0.28], [1.82, 0.62], [1.0, 0.76], [-1.1, 0.82], [-1.75, 0.78]],
    BODY_W,
  )
  const cabinGeo = extrudeProfile([[1.0, 0.76], [0.28, 1.22], [-0.86, 1.22], [-1.3, 0.82]], CABIN_W)
  const wheelGeo = new THREE.CylinderGeometry(0.36, 0.36, 0.3, 10)
  wheelGeo.rotateX(Math.PI / 2)
  const rimGeo = new THREE.CylinderGeometry(0.2, 0.2, 0.34, 6)
  rimGeo.rotateX(Math.PI / 2)
  const lightGeo = new THREE.BoxGeometry(0.06, 0.1, 0.42)
  const tailGeo = new THREE.BoxGeometry(0.05, 0.08, 1.55)
  const glowGeo = new THREE.PlaneGeometry(4.4, 2.5)
  glowGeo.rotateX(-Math.PI / 2)

  const glowCanvas = document.createElement('canvas')
  glowCanvas.width = glowCanvas.height = 128
  const g = glowCanvas.getContext('2d')
  const grad = g.createRadialGradient(64, 64, 4, 64, 64, 62)
  grad.addColorStop(0, 'rgba(6,182,212,0.85)')
  grad.addColorStop(0.5, 'rgba(6,182,212,0.25)')
  grad.addColorStop(1, 'rgba(6,182,212,0)')
  g.fillStyle = grad
  g.fillRect(0, 0, 128, 128)
  const glowTex = new THREE.CanvasTexture(glowCanvas)
  glowTex.colorSpace = THREE.SRGBColorSpace

  shared = {
    bodyGeo,
    cabinGeo,
    wheelGeo,
    rimGeo,
    lightGeo,
    tailGeo,
    glowGeo,
    bodyEdges: new THREE.EdgesGeometry(bodyGeo, 20),
    cabinEdges: new THREE.EdgesGeometry(cabinGeo, 20),
    wheelMat: new THREE.MeshStandardMaterial({ color: 0x07090d, roughness: 0.9, flatShading: true }),
    rimMat: new THREE.MeshBasicMaterial({ color: 0x22d3ee }),
    glassMat: new THREE.MeshStandardMaterial({
      color: 0x06141c, metalness: 0.9, roughness: 0.12, flatShading: true,
      emissive: 0x0891b2, emissiveIntensity: 0.35,
    }),
    headMat: new THREE.MeshBasicMaterial({ color: 0xe0f7ff }),
    tailMat: new THREE.MeshBasicMaterial({ color: 0xff2e3d }),
    edgeMat: new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.6 }),
    glowMat: new THREE.MeshBasicMaterial({
      map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    }),
  }
  return shared
}

const BODY_COLORS = [0x1b2432, 0x2a3342, 0x3a4658, 0xcfd8e3, 0x14202b, 0x0f3b45]

/**
 * Futuristic low-poly wedge car. Local +X is the nose, +Y up.
 * Returns { group, wheels, bodyMat } where `wheels` are pivots that spin around local Z.
 */
export function createCar(colorIndex = 0) {
  const s = getShared()
  const group = new THREE.Group()

  const bodyMat = new THREE.MeshStandardMaterial({
    color: BODY_COLORS[colorIndex % BODY_COLORS.length],
    metalness: 0.75, roughness: 0.32, flatShading: true,
  })
  const body = new THREE.Mesh(s.bodyGeo, bodyMat)
  const cabin = new THREE.Mesh(s.cabinGeo, s.glassMat)
  body.castShadow = cabin.castShadow = true
  group.add(body, cabin)
  group.add(new THREE.LineSegments(s.bodyEdges, s.edgeMat), new THREE.LineSegments(s.cabinEdges, s.edgeMat))

  for (const z of [-0.55, 0.55]) {
    const head = new THREE.Mesh(s.lightGeo, s.headMat)
    head.position.set(1.8, 0.55, z)
    group.add(head)
  }
  const tail = new THREE.Mesh(s.tailGeo, s.tailMat)
  tail.position.set(-1.76, 0.7, 0)
  group.add(tail)

  const wheels = []
  for (const x of [-1.05, 1.1]) {
    for (const z of [-0.88, 0.88]) {
      const pivot = new THREE.Group()
      pivot.position.set(x, 0.36, z)
      const tire = new THREE.Mesh(s.wheelGeo, s.wheelMat)
      const rim = new THREE.Mesh(s.rimGeo, s.rimMat)
      tire.castShadow = true
      pivot.add(tire, rim)
      group.add(pivot)
      wheels.push(pivot)
    }
  }

  const glow = new THREE.Mesh(s.glowGeo, s.glowMat)
  glow.position.y = 0.04
  group.add(glow)

  return { group, wheels, bodyMat }
}
