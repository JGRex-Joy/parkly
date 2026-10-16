# Prototype v08

Prototype v08 combines **four ultrasonic parking sensors, four LED indicators, and two automated servo-controlled gates** into a unified Smart Parking System. The entrance gate opens only when a vehicle is detected and at least one parking space is available, while the exit gate remains operational even when the parking lot is full.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Breadboard**
- **6x HC-SR04 Ultrasonic Distance Sensors**
- **4x Red LEDs**
- **4x Current-limiting resistors**
- **2x Servo Motors** (e.g., SG90)
- Jumper wires

---

## Circuit Connections

| Component | Trigger / Signal Pin | Echo Pin | LED Pin |
| :--- | :--- | :--- | :--- |
| Parking Sensor 1 | Pin 3 | Pin 2 | Pin 4 |
| Parking Sensor 2 | Pin 6 | Pin 5 | Pin 7 |
| Parking Sensor 3 | Pin 10 | Pin 9 | Pin 8 |
| Parking Sensor 4 | Pin 13 | Pin 12 | Pin 11 |
| Entrance Sensor | A4 | A3 | — |
| Exit Sensor | A1 | A0 | — |
| Entrance Servo | A5 | — | — |
| Exit Servo | A2 | — | — |

---

## Purpose

This prototype integrates parking occupancy detection with automated gate control. Four ultrasonic sensors monitor individual parking spaces, with LEDs indicating occupancy. Two additional sensors control the entrance and exit gates through servo motors.

If all four parking spaces are occupied, the entrance gate remains closed. The exit gate can still open when a vehicle is detected, allowing vehicles to leave regardless of parking availability.