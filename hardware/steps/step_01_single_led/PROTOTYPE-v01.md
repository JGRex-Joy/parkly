# Prototype v01

Prototype v01 is a basic starter circuit demonstrating digital output control using an **Arduino Uno** and a breadboard.

---

## Components
* **1x Arduino Uno** microcontroller
* **1x Breadboard**
* **1x Red LED**
* **1x Current-limiting resistors**
* Jumper wires

---

| Component | Arduino Pin | Description |
| :--- | :--- | :--- |
| **Red LED** | Pin 8 | Controlled via `ledPin` |
| **Ground Rail** | GND Pin | Connected via black wire to the negative rail |

---

## Purpose
This circuit serves as a foundational "Blink" setup. The Arduino program toggles **Pin 8** `HIGH` state to turn the red LED on, while the resistor safely limits the current to prevent component damage[cite: 1].