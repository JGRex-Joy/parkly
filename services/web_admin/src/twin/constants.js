export const COLORS = {
  base: 0x0a0e14,
  free: 0x10b981,
  occupied: 0xef4444,
  cyan: 0x06b6d4,
}

// World layout (x = along the lane, z = depth). Slots sit on the back row, the lane runs in front.
export const SLOT_COUNT = 4
export const SLOT_X = [-7.5, -2.5, 2.5, 7.5]
export const SLOT_Z = -4
export const SLOT_W = 4.2
export const SLOT_D = 6.2
export const LANE_Z = 1.8
export const LANE_W = 4.6

export const PLATFORM_HALF = 24 // parking platform spans x = -24..24
export const GATE_X = { entry: -17.5, exit: 17.5 }
export const GATE_ARM_LEN = 4.9
export const STOP_GAP = 2.7 // car centre stops this far before the gate arm
export const WAIT_X = -11 // where an admitted car waits in the driving lane for its slot event
export const QUEUE_GAP = 4.6 // spacing of cars queueing for the exit gate

// Roads run far past the camera/fog so cars appear and vanish off-screen.
export const ROAD_END = 105
export const SPAWN_X = { entry: -96, exit: 96 }
