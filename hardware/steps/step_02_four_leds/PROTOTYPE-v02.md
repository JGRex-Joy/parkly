# Prototype v02

Prototype v02 expands the initial setup to represent **4 individual parking spaces** within the Smart Parking System. Each LED acts as a visual status indicator for a designated parking spot.

---

## Components
* **1x Arduino Uno** microcontroller
* **1x Breadboard**
* **4x Red LEDs** (representing Parking Spots 1 to 4)
* **4x Current-limiting resistors**
* Jumper wires

---

## Circuit Connections

| Component | Arduino Pin | Description |
| :--- | :--- | :--- |
| **Parking Spot 1 LED** | Pin 7 | Controlled via `ledPin1` |
| **Parking Spot 2 LED** | Pin 8 | Controlled via `ledPin2` |
| **Parking Spot 3 LED** | Pin 9 | Controlled via `ledPin3` |
| **Parking Spot 4 LED** | Pin 10 | Controlled via `ledPin4` |
| **Ground Rail** | GND Pin | Connected via black wire to the negative rail |

---

## Purpose
This iteration demonstrates multi-pin digital output management. In the context of the **Smart Parking System**, this phase verifies hardware connections and basic control for all 4 parking space indicators simultaneously. Future iterations can dynamicize these LEDs based on sensor inputs to indicate spot occupancy.