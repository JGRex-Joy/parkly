# Parkly Smart Parking System: Hardware and Embedded Architecture Reference

| Attribute | Value |
| :--- | :--- |
| Document scope | Physical system, embedded firmware, and the hardware-to-software gateway |
| Firmware version covered | `smart_parking.ino` 1.1.0 (`FW_VERSION`) |
| Bridge version covered | `serial_bridge` 0.1.0 |
| Hardware revision covered | Prototype v08 (`hardware/steps/step_08_full_assembly/`) |
| Companion document | [`api_spec.md`](api_spec.md) (protocol payloads and REST interfaces) |

## Table of Contents

1. [Source Material and Conventions](#1-source-material-and-conventions)
2. [Hardware System Overview](#2-hardware-system-overview)
3. [Microcontroller and Component Specifications](#3-microcontroller-and-component-specifications)
4. [Circuit Schematics and Pin Mapping](#4-circuit-schematics-and-pin-mapping)
5. [Hardware Prototype and Physical Layout](#5-hardware-prototype-and-physical-layout)
6. [Embedded State Machine and Logic Flow](#6-embedded-state-machine-and-logic-flow)
7. [Hardware-to-Software Communication Gateway](#7-hardware-to-software-communication-gateway)
8. [Documented Discrepancies and Open Items](#8-documented-discrepancies-and-open-items)

---

## 1. Source Material and Conventions

### 1.1 Source files

Every value in this document is taken from one of the following repository artifacts. No value is derived from outside the repository except where explicitly labelled as a nominal manufacturer figure.

| Artifact | Path | Used for |
| :--- | :--- | :--- |
| Prototype descriptions | `hardware/README.md`, `hardware/steps/step_0N_*/PROTOTYPE-v0N.md` | Component lists, per-prototype pin tables |
| Prototype sketches | `hardware/steps/step_0N_*/prototype_v0N.ino` | Pin constants, threshold logic of the prototypes |
| Tinkercad schematics | `hardware/steps/step_0N_*/schematics-v0N.pdf`, `circuits-v0N.png` | Net labels, resistor values, component identifiers |
| Physical build photographs | `hardware/steps/step_03_*` and later `physical_build/` directories | Physical layout (Section 5) |
| Production firmware | `services/serial_bridge/arduino/smart_parking/smart_parking.ino` | Final pin map, timing, filters, serial protocol |
| Serial protocol | `services/serial_bridge/docs/PROTOCOL.md` | Frame grammar, reliability rules |
| Bridge sources | `services/serial_bridge/app/*.py` | Gateway behaviour, gate flow, configuration |
| Audit report | `services/serial_bridge/docs/AUDIT.md` | Measured behaviour of the sensor filter and failure analysis |

### 1.2 Conventions

- `D<n>` denotes Arduino digital pin `n`. `A<n>` denotes analog pin `n`, used here as a digital I/O pin.
- Slot indices are one-based in the serial protocol (`1..4`) and map to backend slot numbers `P1..P4` through the bridge setting `BRIDGE_SLOT_MAP`.
- "Firmware" without qualification refers to the production firmware `smart_parking.ino` 1.1.0. The sketches under `hardware/steps/` are referred to as "prototype sketches".

---

## 2. Hardware System Overview

### 2.1 Architectural pattern

The physical system follows a single-controller, polled sensor-node architecture with a host-side gateway:

1. **Edge controller.** One Arduino UNO R3 executes a cooperative, non-interrupt main loop. It owns all sensing, filtering, actuation and local indication.
2. **Sensor nodes.** Six HC-SR04 ultrasonic ranging modules. Four monitor parking slots; two monitor the vehicle presence zone at the entry and exit barriers.
3. **Actuators.** Two SG90-class hobby servos, each carrying a barrier arm (servo horn), and four red indicator LEDs, one per slot.
4. **Gateway.** The controller has no network interface. It communicates through its USB serial interface (UART, 115200 baud, 8N1) with a host process, `serial_bridge`, which is the sole owner of the serial port.
5. **Host services.** The bridge translates device events into REST calls to the OCR service and the backend, and translates backend barrier authorizations into device commands. No parking, tariff, or payment rule exists in the embedded layer.

### 2.2 Block diagram

```
                        +----------------------------------------------+
                        |            Arduino UNO R3 (ATmega328P)       |
  4 x HC-SR04 (slots) ->|  D2,D3,D5,D6,D9,D10,D12,D13  (TRIG / ECHO)   |
  2 x HC-SR04 (gates) ->|  A0,A1,A3,A4                 (TRIG / ECHO)   |
                        |                                              |-> D4,D7,D8,D11  -> 4 x LED (via 1 kOhm)
                        |  Main loop: sample -> filter -> debounce ->  |
                        |  barrier state machine -> serial framing     |-> A2, A5 (PWM)  -> 2 x servo (barriers)
                        +---------------------+------------------------+
                                              | USB (5 V power + UART TX/RX, 115200 8N1)
                                              v
                        +----------------------------------------------+
                        |  Host PC: serial_bridge (FastAPI, :8100)     |
                        |  checksummed ASCII frames <-> HTTP / WS      |
                        +--------+-----------------+-------------------+
                                 |                 |
                    POST /gate-event/signal        |  /api/sim/sensor/{id}, /api/hardware/*,
                                 |                 |  WS /ws/entry-display, /ws/exit-display
                                 v                 v
                        +----------------+  +---------------------------+
                        |  OCR service   |->|  Backend (FastAPI, :8000) |-> SQLite
                        |  (:8001)       |  +---------------------------+
                        +----------------+         |  WS displays
                          ^   ^                    v
                 camera   |   |  camera    React Native display screens
                 (entry)--+   +--(exit)    (entry display / exit display)
```

### 2.3 Functional partitioning

| Concern | Embedded firmware | Host services |
| :--- | :--- | :--- |
| Distance measurement, filtering, debouncing | Yes | No (raw distances never leave the device unless `dbg=1`) |
| Slot LED indication | Yes (driven directly from the debounced state) | No |
| Barrier motion and auto-close | Yes (non-blocking servo ramp, hold timer, clear timer) | Issues `OPEN` / `CLOSE` only |
| Decision to admit or release a vehicle | No | Backend (state machine, billing, payment) |
| Licence plate recognition | No | OCR service |
| Duplicate suppression, retries, reconnection | Retransmission cache (4 entries) | Bridge (sequence numbers, ACK retry, event de-duplication) |

---

## 3. Microcontroller and Component Specifications

The production bill of materials is defined by `hardware/README.md` and `hardware/steps/step_08_full_assembly/PROTOTYPE-v08.md`. Figures marked "nominal" are generic manufacturer values for the named part class and are not contained in the repository.

### 3.1 Controller: Arduino UNO R3

| Property | Value | Source |
| :--- | :--- | :--- |
| Board | Arduino UNO R3 (as photographed, an UNO R3 compatible board with a DC barrel jack and USB-B connector) | `README.md`, build photographs |
| Role | Single edge controller | Section 2 |
| Serial interface | Hardware UART through USB, 115200 baud, 8 data bits, no parity, 1 stop bit | `SERIAL_BAUD 115200UL`, `PROTOCOL.md` |
| Firmware library | `Servo.h` (bundled with the Arduino IDE) | `smart_parking.ino` |
| Digital I/O used | D2 to D13 and A0 to A5 (18 lines) | Section 4 |
| Free lines | D0 and D1 (UART, reserved by the USB serial interface) | Section 4 |
| Reset behaviour | Opening the USB serial port toggles DTR and resets the board; the bridge waits `BRIDGE_SERIAL_BOOT_DELAY` (2.0 s) after opening | `PROTOCOL.md`, `config.py` |

Nominal controller figures (ATmega328P): 16 MHz clock, 32 KB flash, 2 KB SRAM, 5 V logic. The firmware sizes its buffers accordingly (receive line buffer of 72 bytes, `MEDIAN_MAX` 5 samples per sensor, comment in source: "6 sensors x 10 B").

### 3.2 Sensors: HC-SR04 ultrasonic ranging module (6 units)

| Property | Value | Source |
| :--- | :--- | :--- |
| Quantity | 6 (4 slot sensors, 2 gate sensors) | `PROTOTYPE-v08.md` |
| Pins | `VCC`, `TRIG`, `ECHO`, `GND` | `schematics-v08.pdf` (component labels `DISTU11`, `DISTU2`, `DISTU3`, `DISTU4`, `DISTUG1`, `DISTUG2`) |
| Supply | 5 V from the Arduino 5 V rail (net `U2_5V`) | `schematics-v08.pdf` |
| Trigger pulse | 2 microsecond LOW, then 10 microsecond HIGH | `readCm()` |
| Echo timeout | `ECHO_TIMEOUT_US = 8000` microseconds, equivalent to about 137 cm at 58 microseconds per centimetre | `readCm()` |
| Distance conversion | `distance_cm = echo_us / 58` | `readCm()` |
| Minimum valid reading | `MIN_VALID_CM = 2`; smaller values are discarded as electrical glitches | `smart_parking.ino` |
| No-echo marker | `DIST_NO_ECHO = 0xFFFF` (65535) | `smart_parking.ino` |
| Nominal operating principle | 40 kHz burst, time-of-flight measurement | generic part characteristic |

The prototype sketches use a different time-out and conversion (`pulseIn(..., 30000)` and `duration * 0.0343 / 2`) with a fixed detection limit of 150 cm; see Section 6.6.

### 3.3 Actuators

| Component | Quantity | Function | Control line | Source |
| :--- | :---: | :--- | :--- | :--- |
| SG90 micro servo (blue body, "Tower Pro" marking visible in photograph) | 2 | Entry and exit barrier arms | PWM through `Servo.h`, signal on `A2` / `A5` (firmware) | `README.md`, `photo-v07.jpg` |
| Red LED | 4 | Slot occupancy indicator (lit when occupied) | `D11`, `D8`, `D7`, `D4` (firmware) | `PROTOTYPE-v08.md`, `schematics-v08.pdf` (`DL1` to `DL4`, `RED`) |
| Resistor, 1 kOhm | 4 | LED current limiting (`RR1` to `RR4`) | In series with each LED to GND | `schematics-v08.pdf` |

Servo motion parameters (firmware defaults): closed angle 0 degrees, open angle 90 degrees, ramp of 3 degrees every 15 ms (`SERVO_STEP_DEG`, `SERVO_STEP_MS`). A full 90 degree travel therefore takes 30 steps, about 450 ms. The servo signal wire is the only high-rate output; servo supply is shared with the controller 5 V rail (Section 4.5).

### 3.4 Displays

No display device is attached to the microcontroller. Slot status is shown locally by the four LEDs. The entry display (free slots, tariff) and the exit display (bill, QR code) are software displays rendered by the React Native application in `services/mobile/` and by the backend pages `GET /display/entry` and `GET /display/exit`. The `hardware/README.md` lists "an LCD displaying available spaces" as a possible future improvement; it is not part of the current build.

### 3.5 Power management

| Item | Implementation | Source |
| :--- | :--- | :--- |
| Primary supply | USB cable from the host PC (visible in all photographs), 5 V | `photo-v04.jpg`, `photo-v07.jpg` |
| Sensor supply | Arduino 5 V pin to breadboard `+` rail to each HC-SR04 `VCC` | `schematics-v08.pdf` |
| Servo supply | Arduino 5 V pin, shared with sensors (`SERVOS1/2 PWR` connected to `U2_5V`) | `schematics-v08.pdf` |
| Ground | Single common ground net `U2_GND` | `schematics-v08.pdf` |
| Dedicated regulator or external servo supply | Not present | repository |
| Brown-out risk | Documented as an unproven hypothesis: SG90 stall or inrush current on the Arduino 5 V pin may reset the board. The bridge logs `Arduino RESET while the USB link was up` and increments `unexpected_resets` in `GET /status` to expose this. | `AUDIT.md` section 2e |

---

## 4. Circuit Schematics and Pin Mapping

### 4.1 Schematic files

Each prototype step contains a Tinkercad schematic (`schematics-v0N.pdf`) and a circuit rendering (`circuits-v0N.png`). The authoritative schematic for the complete system is `hardware/steps/step_08_full_assembly/schematics-v08.pdf` (title "Prototype v08", two sheets).

The v08 schematic contains the following elements:

| Schematic identifier | Component | Notes |
| :--- | :--- | :--- |
| `U2` | Arduino UNO | Net labels `U2_D2`, `U2_D3`, `U2_D5`, `U2_D6`, `U2_D9`, `U2_D10`, `U2_D11`, `U2_D12`, `U2_D13`, `U2_A5`, `U2_5V`, `U2_GND` |
| `DISTU11`, `DISTU2`, `DISTU3`, `DISTU4` | HC-SR04 | Four slot sensors, pins `VCC`, `TRIG`, `ECHO`, `GND` |
| `DISTUG1`, `DISTUG2` | HC-SR04 | Two gate sensors |
| `SERVOS1`, `SERVOS2` | Servo | Pins `PWR`, `SIG`, `GND` |
| `DL1` to `DL4` | LED, colour `RED` | Cathode nets `DL1_C`, `DL2_C`, `DL3_C` run between the two sheets; `DL4` is wired directly to `RR4` on sheet 1 |
| `RR1` to `RR4` | Resistor, `1k` | Each in series with one LED cathode to `U2_GND` (`RR1` and `RR2` on sheet 2, `RR3` and `RR4` on sheet 1) |

### 4.2 Pin map of the production firmware (authoritative for the bridge)

Source: constants at the top of `smart_parking.ino` (`SLOT_TRIG`, `SLOT_ECHO`, `SLOT_LED`, `ENTRY_*`, `EXIT_*`).

| Function | Arduino pin | Component pin | Direction | Signal type | Voltage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Slot 1 trigger | D13 | HC-SR04 `TRIG` | Output | Digital pulse, 10 microseconds | 5 V logic |
| Slot 1 echo | D12 | HC-SR04 `ECHO` | Input | Digital pulse, width proportional to distance | 5 V logic |
| Slot 1 LED | D11 | LED anode through 1 kOhm | Output | Digital level | 5 V logic |
| Slot 2 trigger | D10 | HC-SR04 `TRIG` | Output | Digital pulse | 5 V logic |
| Slot 2 echo | D9 | HC-SR04 `ECHO` | Input | Digital pulse | 5 V logic |
| Slot 2 LED | D8 | LED via 1 kOhm | Output | Digital level | 5 V logic |
| Slot 3 trigger | D6 | HC-SR04 `TRIG` | Output | Digital pulse | 5 V logic |
| Slot 3 echo | D5 | HC-SR04 `ECHO` | Input | Digital pulse | 5 V logic |
| Slot 3 LED | D7 | LED via 1 kOhm | Output | Digital level | 5 V logic |
| Slot 4 trigger | D3 | HC-SR04 `TRIG` | Output | Digital pulse | 5 V logic |
| Slot 4 echo | D2 | HC-SR04 `ECHO` | Input | Digital pulse | 5 V logic |
| Slot 4 LED | D4 | LED via 1 kOhm | Output | Digital level | 5 V logic |
| Entry gate sensor echo | A0 | HC-SR04 `ECHO` | Input | Digital pulse | 5 V logic |
| Entry gate sensor trigger | A1 | HC-SR04 `TRIG` | Output | Digital pulse | 5 V logic |
| Entry barrier servo | A2 | Servo `SIG` (orange) | Output | Servo PWM (`Servo.h`) | 5 V logic |
| Exit gate sensor echo | A3 | HC-SR04 `ECHO` | Input | Digital pulse | 5 V logic |
| Exit gate sensor trigger | A4 | HC-SR04 `TRIG` | Output | Digital pulse | 5 V logic |
| Exit barrier servo | A5 | Servo `SIG` (orange) | Output | Servo PWM | 5 V logic |
| Serial TX / RX | D1 / D0 | USB-UART bridge | Output / Input | UART, 115200 8N1 | 5 V logic |
| Sensor and servo supply | 5V | `VCC` / servo `PWR` (red) | Supply | DC | 5 V |
| Common ground | GND | `GND` of all modules, LED resistors | Return | DC | 0 V |

Internal sensor indices: slots use indices 0 to 3; the entry sensor is index 4 (`S_ENTRY`); the exit sensor is index 5 (`S_EXIT`).

### 4.3 Pin map of the prototype v08 sketch and description

Source: `PROTOTYPE-v08.md` (table "Circuit Connections") and `prototype_v08.ino`. The two sources agree with each other.

| Function | Trigger | Echo | LED / servo |
| :--- | :--- | :--- | :--- |
| Parking Sensor 1 | D3 | D2 | LED D4 |
| Parking Sensor 2 | D6 | D5 | LED D7 |
| Parking Sensor 3 | D10 | D9 | LED D8 |
| Parking Sensor 4 | D13 | D12 | LED D11 |
| Entrance Sensor | A4 | A3 | Entrance servo A5 |
| Exit Sensor | A1 | A0 | Exit servo A2 |

### 4.4 Reconciliation between the prototype v08 and the production firmware

The set of electrically used pins is identical in both sources. The logical assignment differs in two respects:

| Aspect | Prototype v08 (sketch and description) | Production firmware 1.1.0 | Consequence if the board is wired per v08 |
| :--- | :--- | :--- | :--- |
| Slot order | Slot 1 = (D3, D2, LED D4), Slot 2 = (D6, D5, D7), Slot 3 = (D10, D9, D8), Slot 4 = (D13, D12, D11) | Slot 1 = (D13, D12, D11), Slot 2 = (D10, D9, D8), Slot 3 = (D6, D5, D7), Slot 4 = (D3, D2, D4) | Slot numbering is reversed: firmware slot `n` corresponds to v08 sensor `5 - n` |
| Gate roles | Entrance = (trig A4, echo A3, servo A5); Exit = (trig A1, echo A0, servo A2) | Entry = (trig A1, echo A0, servo A2); Exit = (trig A4, echo A3, servo A5) | Entry and exit are interchanged |

The physical wiring must follow the production firmware pin map in Section 4.2 for the bridge and backend to associate events with the correct slot and gate, or the constants at the top of `smart_parking.ino` must be changed to match the existing wiring. `docs/TEST_PLAN.md` (section C) prescribes verifying the mapping in Tinkercad by presenting an object to each sensor and observing the resulting `SLOT` or `GATE` event. This item is repeated in Section 8.

### 4.5 Power and ground topology

```
USB 5 V ──> Arduino 5V pin ──┬─> breadboard "+" rail ──┬─> HC-SR04 VCC  (x6)
                             │                         └─> Servo PWR    (x2)
                             │
Arduino GND ─────────────────┴─> breadboard "-" rail ──┬─> HC-SR04 GND  (x6)
                                                       ├─> Servo GND    (x2)
                                                       └─> 1 kOhm resistor ──> LED cathode (x4)
```

The schematic shows the LED anodes driven from the digital outputs and the cathodes returned to ground through the 1 kOhm resistors. All 18 signal lines are 5 V logic referenced to the common ground.

### 4.6 Wiring history of the prototypes

The incremental prototypes use different pin assignments. They are retained for reference and are not compatible with the production firmware.

| Prototype | Function | Pins (source: `PROTOTYPE-v0N.md`) |
| :--- | :--- | :--- |
| v01 | Single LED | Described in `PROTOTYPE-v01.md` (no connection table) |
| v02 | Four LEDs | D7, D8, D9, D10 |
| v03 | One HC-SR04 and one LED | TRIG D9, ECHO D8, LED D7 |
| v04 | Four sensors, four LEDs | Slot 1: TRIG 3, ECHO 2, LED 4. Slot 2: TRIG 6, ECHO 5, LED 7. Slot 3: TRIG 10, ECHO 9, LED 8. Slot 4: TRIG 13, ECHO 12, LED 11. |
| v05 | Single servo | Signal D8 |
| v06 | Two servos | Signals D9, D10 |
| v07 | Two sensors, two servos | Sensor 1: TRIG 6, ECHO 5, servo D4. Sensor 2: TRIG 8, ECHO 7, servo D9. |
| v08 | Full assembly | Section 4.3 |

---

## 5. Hardware Prototype and Physical Layout

This section is limited to what the repository photographs and files show.

### 5.1 Construction

- **Platform.** A single solderless breadboard carries the sensors and passive components. The Arduino UNO R3 compatible board sits beside the breadboard and is connected to it by jumper wires (red for supply, black for ground, green and yellow for signals, as shown in `photo-v04.jpg` and `photo-v07.jpg`).
- **Host link.** A blue USB cable connects the board to a laptop, which supplies power and the serial link (`photo-v07.jpg`).
- **Enclosure and chassis.** The repository contains no enclosure, chassis, or 3D model files. The prototype is an open breadboard build. The root `README.md` refers to Tinkercad models, which in the repository take the form of the `schematics-v0N.pdf` and `circuits-v0N.png` renderings.

### 5.2 Sensor placement

- **Slot sensors.** One HC-SR04 per parking space, monitoring the space it faces. In the v04 photograph the modules are mounted on the breadboard with the transducers facing outward.
- **Gate sensors.** One HC-SR04 at each barrier, monitoring the vehicle approach zone in front of the barrier arm. `AUDIT.md` recommends, for the 7 by 4 cm toy vehicles used in the demonstration, aiming the sensor at the flattest face of the vehicle (side or rear), mounting at body height of approximately 1.5 to 2 cm, keeping the beam (approximately 15 degree cone) away from the floor and from neighbouring slots, and keeping a minimum distance of 5 cm.
- **Test targets.** The demonstration uses small toy vehicles. The audit reports that specular reflection from small curved bodies causes echo loss, which motivated the median filter in firmware 1.1.0.

### 5.3 Barrier mechanics

Each barrier consists of an SG90 servo with its white plastic servo horn acting as the barrier arm (`photo-v07.jpg` shows both servos with horns fitted, held by hand during the test). The arm moves between 0 degrees (closed) and 90 degrees (open). The 3 degree per 15 ms ramp limits mechanical shock and supply current peaks.

### 5.4 Camera and display devices

Two smartphones are used as camera sources for the OCR service (each camera is configured as a local video device index or as an `rtsp://` / `http://` stream URL through `ENTRY_CAMERA_SOURCE` and `EXIT_CAMERA_SOURCE`) and as display terminals for the React Native entry and exit screens (`README.md`, `services/ocr_service/README.md`). They are not connected to the microcontroller.

---

## 6. Embedded State Machine and Logic Flow

All behaviour in this section is implemented in `smart_parking.ino` 1.1.0 and is exercised without hardware by the host-compiled firmware tests in `services/serial_bridge/tests/test_firmware_host.py` (they require `g++`).

### 6.1 Execution model

The firmware is a cooperative super-loop. It uses no hardware interrupts and no timer interrupts. The only blocking call is `pulseIn()` with an 8000 microsecond timeout, so a single sensor read blocks the loop for at most 8 ms.

```
loop():
    pollSerial()                              # non-blocking line assembly
    if now - lastSample >= sampleMs (25):     # one sensor per tick
        sampleNext()
    updateBarrier(entry); updateBarrier(exit) # non-blocking servo ramp and timers
    if now - lastHb >= hbMs (2000):
        emit HB
```

### 6.2 Sensor scheduling

One sensor is sampled per `sample_ms` tick (default 25 ms), following a fixed eight-entry schedule that samples the gate sensors more often than the slot sensors:

```
SCHEDULE = { ENTRY, slot1, EXIT, slot2, ENTRY, slot3, EXIT, slot4 }
```

At the default tick, each gate sensor is sampled every 100 ms (every 4th tick) and each slot sensor every 200 ms (every 8th tick). Only one sensor is triggered at a time, which prevents acoustic crosstalk between modules.

### 6.3 Per-sensor filtering and debouncing pipeline

Each sensor has a `Sensor` record holding the published state, a streak counter and a sliding window of up to 5 readings. A reading passes through three stages (`updateSensor()`):

| Stage | Rule | Effect |
| :--- | :--- | :--- |
| 1. Glitch rejection | Reading below `MIN_VALID_CM` (2 cm) is discarded | No window entry, no vote, streak unchanged |
| 2. Median filter | Valid readings (including `DIST_NO_ECHO`, treated as very far) enter a sliding window of `median` entries (default 5). The sensor abstains until the window is full. The median of the window is evaluated | Up to 2 of 5 samples may be outliers without affecting the result |
| 3. Hysteresis and asymmetric debounce | Threshold `thr` is `slot_thr` (25 cm) for slots and `gate_thr` (40 cm) for gates. FREE to OCCUPIED when `median < thr`. OCCUPIED to FREE when `median > thr + hyst` (`hyst` 5 cm). Readings in the dead band vote for no change. A state change requires N consecutive disagreeing medians: `debounce` (3) to become OCCUPIED, `debounce_free` (6) to become FREE | Resists flicker; false FREE (barrier closing on a vehicle, or a slot being resold) is made harder than a late FREE |

Per-sensor state machine:

```
                 median < thr, 3 consecutive medians
          +-------------------------------------------------+
          |                                                 v
     +----------+                                     +------------+
     |   FREE   |                                     |  OCCUPIED  |
     | (state=0)|                                     |  (state=1) |
     +----------+                                     +------------+
          ^                                                 |
          +-------------------------------------------------+
            median > thr + hyst, 6 consecutive medians
   Any median that agrees with the current state resets the streak to 0.
   On every transition: slot LED updated (slots only), SLOT or GATE event emitted.
```

Measured behaviour reported in `AUDIT.md`: with the original v1.0 logic a parked vehicle produced 15 false transitions in 12 seconds under bursts of lost echoes; with v1.1 the same input produced one detection and one transition. Latency cost is approximately 0.85 s to become occupied and 1.5 s to become free for slot sensors.

### 6.4 Slot indicator logic

Slot LED `i` is written in `onSensorChange()` only when the debounced state of slot `i` changes: `HIGH` when occupied, `LOW` when free. The LEDs are all `LOW` at power-up. LED state is therefore always consistent with the published `SLOT` event for the same slot, and it does not flicker with raw readings.

### 6.5 Barrier (gate) state machine

Each barrier has fields `angle`, `target`, `wantOpen`, `settled`, `clearing`, `holdUntil`, `clearSince`. Gate 0 is entry (servo `A2`, sensor index 4); gate 1 is exit (servo `A5`, sensor index 5).

```
                  OPEN cmd                         ramp reaches openDeg
   +----------+ ------------> +-----------+ ----------------------------> +--------------+
   |  CLOSED  |               |  OPENING  |    emit BARRIER,<gate>,OPENED |  OPEN (hold) |
   | (0 deg)  | <------------ |           |                               | until        |
   +----------+   ramp done   +-----------+                               | holdUntil    |
        ^         emit BARRIER,<gate>,CLOSED                               +------+-------+
        |                                                                         | hold elapsed
        |                                                                         v
   +----+-----+   clearMs elapsed with sensor FREE   +-----------------------------------+
   | CLOSING  | <----------------------------------- | WAIT CLEAR: sensor OCCUPIED resets |
   +----------+                                      | the clear timer; FREE for clearMs  |
                                                     +-----------------------------------+
```

| Rule | Implementation |
| :--- | :--- |
| Open | `OPEN,<gate>[,<holdMs>]` sets `wantOpen`, target `openDeg` (90), `holdUntil = now + holdMs` (default 8000, accepted range 500 to 60000). If already open, the reply is `ACK,<seq>,OK,REFRESHED` and the hold is extended |
| Auto-close | After `holdUntil`, the barrier closes only when the gate sensor reports FREE continuously for `clear_ms` (default 1500). A vehicle detected during the wait restarts the clear timer |
| Explicit close | `CLOSE,<gate>` is refused with `NAK,<seq>,VEHICLE_PRESENT` if the gate sensor is OCCUPIED; otherwise the target becomes `closedDeg` (0) |
| Motion | Non-blocking ramp of 3 degrees each 15 ms toward the target; the main loop is never stalled by servo motion |
| Completion event | When `angle == target` and the barrier was not yet settled, `EVT,...,BARRIER,<gate>,OPENED` or `CLOSED` is emitted exactly once |
| Local admission policy | None. The firmware does not decide whether a vehicle may enter; the entrance remains closed unless the backend authorizes it and the bridge sends `OPEN` |

Safety properties: a barrier cannot be closed by command onto a vehicle that the gate sensor reports; a closed gate stays closed without a command; the auto-close timer cannot expire while the gate sensor reports a vehicle.

### 6.6 Prototype v08 sketch logic (superseded)

`prototype_v08.ino` is a stand-alone demonstration with different logic. It performs no filtering or serial communication:

- Single-sample threshold: an object is detected when `0 < distance < 150` cm (`detectionLimit`). `getDistance()` uses `pulseIn(echoPin, HIGH, 30000)` and `duration * 0.0343 / 2`.
- Slot LED follows the raw reading on every pass.
- Entrance servo opens to 90 degrees when the entrance sensor detects an object and fewer than four slots are occupied (`parkingAvailable = occupiedSlots < 4`); otherwise 0 degrees.
- Exit servo opens whenever the exit sensor detects an object, regardless of occupancy.
- Loop pacing: `delay(50)` between sensors.

Admission in the full system is decided in the backend (Section 7.6), and the production firmware has no local "lot full" rule.

### 6.7 Runtime configuration

All thresholds and timings are runtime-configurable through `CFG,<key>,<value>`. Values are range-checked and a violation returns `NAK,<seq>,BAD_VALUE`.

| Key | Default | Range | Meaning |
| :--- | ---: | :--- | :--- |
| `gate_thr` | 40 | 5 to 400 | Gate sensor: occupied below this median (cm) |
| `slot_thr` | 25 | 5 to 400 | Slot sensor: occupied below this median (cm) |
| `hyst` | 5 | 0 to 50 | Dead band above the threshold (cm) |
| `debounce` | 3 | 1 to 20 | Consecutive medians to become OCCUPIED |
| `debounce_free` | 6 | 1 to 40 | Consecutive medians to become FREE |
| `median` | 5 | 1 to 5 | Window length; 1 disables the filter; changing it clears all windows |
| `sample_ms` | 25 | 10 to 500 | Sampling tick |
| `hold_ms` | 8000 | 500 to 60000 | Default barrier open hold |
| `clear_ms` | 1500 | 0 to 60000 | Gate clear time before auto-close |
| `open_deg` | 90 | 0 to 180 | Servo open angle |
| `closed_deg` | 0 | 0 to 180 | Servo closed angle |
| `hb_ms` | 2000 | 500 to 60000 | Heartbeat period |
| `dbg` | 0 | 0 to 1 | `1` streams `DIST` events (median and last raw distance) for threshold tuning |

The bridge can push a configuration at every (re)connection through `BRIDGE_DEVICE_CFG`, for example `slot_thr=20,hyst=6,debounce_free=8`.

---

## 7. Hardware-to-Software Communication Gateway

### 7.1 Physical interface and framing

| Layer | Specification |
| :--- | :--- |
| Physical | USB-B cable between the Arduino and the host; the board enumerates as a serial port (`COM<n>`, `/dev/ttyACM0`, or detected by `BRIDGE_SERIAL_PORT=auto`) |
| Link | UART 115200 baud, 8N1, no flow control |
| Encoding | ASCII, one frame per line terminated by `\n` (`\r` is ignored on receive) |
| Frame | `$<field>,<field>,...*<CS>\n` where `CS` is the XOR of all characters between `$` and `*`, written as two upper-case hexadecimal digits |
| Field content | Fields never contain `$`, `*`, `,`, CR or LF |
| Size limits | Host-to-device line buffer 72 bytes (`LINE_MAX`); overlong lines produce `NAK,0,TOO_LONG`; maximum frame 96 bytes |
| Port ownership | The bridge is the only process that may open the port. The Arduino IDE serial monitor must be closed while the bridge runs |

Frame types: `CMD` (host to device), `ACK` and `NAK` (device replies), `EVT` (device events). The complete command, reply and event tables, with example frames, are in [`api_spec.md`](api_spec.md), Section 2.

### 7.2 Command execution and reliability on the device

- A command carries a sequence number `seq` in `1..65535` chosen by the bridge. The bridge starts each connection at a random sequence number.
- The device keeps the last four executed commands as `(seq, frame checksum)` pairs. A byte-identical retransmission is answered `ACK,<seq>,OK,DUP` and is not executed again. A different command that reuses an old `seq` is executed. (Version 1.0 matched on `seq` alone, which caused an unexecuted `OPEN` after a bridge restart; see `AUDIT.md` section 2a.)
- Events carry a counter that starts at 1 after boot and wraps from 65535 to 1.
- On boot the firmware emits `BOOT,<version>` followed by a full `STATE` event. Heartbeats (`HB`, every `hb_ms`) repeat the complete state with uptime, so a lost `SLOT` or `GATE` event is repaired within one heartbeat period.

State vector used by `STATE` and `HB`: `<s1s2s3s4>,<entry>,<exit>,<entryOpen>,<exitOpen>`, for example `0100,1,0,0,0` (slot 2 occupied, vehicle present at the entry gate, no barrier open).

### 7.3 Bridge architecture

`services/serial_bridge/app/` contains the host-side gateway. It exposes a local HTTP API (default port 8100) and contains no parking rules.

| Module | Responsibility |
| :--- | :--- |
| `serial_manager.py` | Single reader thread, dedicated transmit thread, ACK matching, retransmission, reconnect with backoff |
| `protocol.py` | Frame encoding, decoding and validation |
| `transports.py` | `PySerialTransport` (real port), flushes input after the boot delay |
| `event_router.py` | Gate state machine to OCR trigger; slot events to backend; reconciliation of `STATE` and `HB` against known state |
| `commands.py` | Idempotent barrier commands with deduplication and deadline |
| `backend_ws.py` | Subscribes to backend WebSocket channels and receives `barrier_open` authorizations |
| `authorizations.py` | Executes authorizations (WebSocket and polling fallback) and acknowledges them to the backend |
| `clients.py` | HTTP clients for the backend and the OCR service |
| `mock_arduino.py` | Software Arduino for `BRIDGE_SERIAL_PORT=mock://` |
| `config.py` | `BRIDGE_*` environment variables |

### 7.4 Connection lifecycle

1. The bridge opens the serial port and waits `BRIDGE_SERIAL_BOOT_DELAY` seconds, because opening the port resets the UNO.
2. Stale input is flushed. The event epoch is incremented on every link-up so that event de-duplication keyed on `(epoch, n)` does not discard events from a restarted device counter.
3. Bring-up: the bridge loads the slot state from the backend (`GET /api/sim/slots`), sends each configured `CFG`, then `SYNC`. The device answers `ACK` and emits a full `STATE`.
4. Steady state: events are dispatched; `HB` arrives every 2 s. A link with no byte for `BRIDGE_LINK_TIMEOUT` (8 s) is declared dead.
5. On disconnect, pending commands fail with `SerialDisconnected` and the reader reconnects with backoff from 1 s doubling to 10 s. A `BOOT` that arrives more than `BRIDGE_UNEXPECTED_BOOT_WINDOW_S` (6 s) after link-up is counted as an unexpected board reset (for example brown-out).
6. If a `BOOT` occurs inside an authorized hold window, the open command is re-sent with the remaining time (`reassert_open`).

### 7.5 Event flows

**Slot occupancy**

```
HC-SR04 -> firmware filter -> EVT SLOT,<n>,<0|1> -> bridge EventRouter
        -> per-slot sender (value must be stable slot_settle_s = 0.3 s, at most one POST per
           slot_min_interval_s = 1 s, only if different from the backend's known value)
        -> POST /api/sim/sensor/{slot_id}  {"occupied": bool}
```

The slot index maps to a backend slot number through `BRIDGE_SLOT_MAP` (default `1:P1,2:P2,3:P3,4:P4`) and then to a backend slot id from `GET /api/sim/slots`.

**Entry**

```
vehicle in front of entry sensor -> EVT GATE,entry,1
  -> gate phase IDLE -> PROCESSING: POST OCR /gate-event/signal?gate=entry   (up to BRIDGE_OCR_MAX_ATTEMPTS = 3, 2 s apart, only on retryable outcomes)
  -> OCR captures a frame, reads the plate, POST backend /api/sim/entry
  -> backend admits the vehicle (or returns 409 when full) and publishes {"event":"barrier_open","gate":"entry",...} on WS /ws/entry-display
  -> bridge BackendListener -> CMD OPEN,entry,<hold> -> device opens, EVT BARRIER,entry,OPENED
  -> bridge POST /api/hardware/authorizations/entry/{session_id}/opened
  -> vehicle leaves the sensor: EVT GATE,entry,0 -> gate phase returns to IDLE
```

**Exit and payment**

```
EVT GATE,exit,1 -> OCR /gate-event/signal?gate=exit -> backend /api/sim/exit issues a bill and QR
  -> barrier remains closed (OCR alone never opens a barrier)
  -> customer pays: POST /api/pay/{session_id}
  -> backend publishes barrier_open (gate "exit") on WS /ws/exit-display
  -> CMD OPEN,exit -> EVT BARRIER,exit,OPENED
  -> EVT GATE,exit,0 -> bridge POST /api/hardware/barrier-events  event VEHICLE_CLEARED -> session COMPLETED
```

The bridge also polls `GET /api/hardware/authorizations?gate=` every `BRIDGE_AUTH_POLL_INTERVAL` (3.0 s) as a fallback when the WebSocket is unavailable.

### 7.6 Sequence diagram: authorized entry

```
Arduino          Bridge                 OCR service         Backend            Display app
   |  EVT GATE,entry,1  |                     |                  |                  |
   |------------------->| POST /gate-event/signal?gate=entry     |                  |
   |                    |-------------------->| capture + read   |                  |
   |                    |                     | POST /api/sim/entry                 |
   |                    |                     |----------------->| create session   |
   |                    |                     |                  | WS entry_display_update
   |                    |                     |                  |----------------->|
   |                    |<---------------------------------------| WS barrier_open  |
   |  CMD OPEN,entry    |                     |                  |                  |
   |<-------------------|                     |                  |                  |
   |  ACK ...OK         |                     |                  |                  |
   |------------------->| POST /api/hardware/authorizations/entry/{id}/opened        |
   |  EVT BARRIER,entry,OPENED                |                  |                  |
   |------------------->|                     |                  |                  |
   |  EVT GATE,entry,0  |                     |                  |                  |
   |------------------->| gate phase -> IDLE  |                  |                  |
```

### 7.7 Barrier command safety on the host

| Mechanism | Setting | Purpose |
| :--- | :--- | :--- |
| ACK timeout and retransmit | `BRIDGE_ACK_TIMEOUT` 0.6 s, `BRIDGE_ACK_RETRIES` 3, same `seq` | Recover from corrupted or lost frames without double execution |
| Idempotency key | `request_id` or backend `authorization_id`; otherwise `gate:plate` heuristic key | A repeated authorization never opens the barrier twice |
| Deduplication window | `BRIDGE_OPEN_DEDUPE_SECONDS` 15; heuristic keys are dropped on `BARRIER CLOSED` | Allows a legitimate second visit by the same plate |
| Deadline | `BRIDGE_OPEN_DEADLINE` 10 s | Bounded wait while the link is down; a pending open executes once after reconnect |
| Hold | `BRIDGE_OPEN_HOLD_MS` 8000 | Minimum open time sent with `OPEN` |
| Authentication | `BRIDGE_API_TOKEN` enables `X-Bridge-Token` on `POST /v1/*` | The HTTP open endpoint can lift a barrier; it must be bound to localhost and tokenised |

---

## 8. Documented Discrepancies and Open Items

| # | Item | Evidence | Recommended action |
| :---: | :--- | :--- | :--- |
| 1 | Slot order and gate roles differ between the prototype v08 description and sketch, and the production firmware (Section 4.4). | `PROTOTYPE-v08.md`, `prototype_v08.ino` versus `smart_parking.ino` | Verify wiring against Section 4.2 or edit the pin constants; confirm with the `SLOT` and `GATE` events as described in `TEST_PLAN.md` section C |
| 2 | `services/serial_bridge/README.md` and `INTEGRATION_PLAN.md` reference `docs/HARDWARE.md` ("confirmed pin map"), which is not present in the repository. | File list of the repository | Treat Section 4 of this document as the pin reference |
| 3 | `TEST_PLAN.md` section C expects `$EVT,1,BOOT,1.0.0*7D`; firmware 1.1.0 emits `$EVT,1,BOOT,1.1.0*7C`. | `FW_VERSION "1.1.0"`; checksum computed with `protocol.encode` | Update the test plan expectation |
| 4 | The bridge README lists the default of `BRIDGE_SLOT_VACANT_POLICY` as `skip_staff`; `config.py` defines the default as `forward`. | `services/serial_bridge/app/config.py` | Set the variable explicitly in deployments |
| 5 | The root `README.md` refers to `docs/documentation.pdf`, which is not present, and to `services/mobile_app/`, while the directory is `services/mobile/`. | File list of the repository | Addressed by the updated root `README.md` |
| 6 | Servo power is drawn from the Arduino 5 V pin with no dedicated supply. Brown-out is a documented, unproven hypothesis. | `AUDIT.md` section 2e | Provide an external 5 V supply with common ground for the servos; monitor `unexpected_resets` |
| 7 | HC-SR04 returns poor echoes from small curved targets. The 8 ms timeout limits range to about 137 cm. | `AUDIT.md`, `readCm()` | Tune `slot_thr`, `hyst`, `debounce_free` on the rig (`AUDIT.md`, tuning procedure); consider time-of-flight sensors as noted in the audit |
