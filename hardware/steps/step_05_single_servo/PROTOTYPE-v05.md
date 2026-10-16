# Prototype v05

Prototype v05 introduces a **servo motor to the Smart Parking System**. This prototype focuses on controlling the servo's position using an Arduino Uno, establishing the foundation for an automated parking barrier.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Servo Motor**
- Jumper wires

---

## Circuit Connections

| Servo Wire | Arduino Pin | Description |
| :--- | :--- | :--- |
| **Signal (orange)** | Pin 8 | Receives control signals from the Arduino |
| **Power (red)** | 5V | Supplies power to the servo motor |
| **Ground (black)** | GND | Completes the electrical circuit |

---

## Purpose

This iteration demonstrates basic servo motor control using the Arduino Servo library. When the Arduino starts, the servo moves to **90 degrees** and remains at that position for 2 seconds than returns to **0 degrees**.
This prototype verifies the servo's wiring and establishes the foundation for future iterations in which the servo will act as a parking barrier, opening and closing automatically based on sensor readings or button input.