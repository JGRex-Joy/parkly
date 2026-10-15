# Prototype v07

Prototype v07 integrates **two ultrasonic distance sensors with two servo motors** to create an automated dual-barrier parking system. Each sensor controls its corresponding servo motor independently, allowing each barrier to respond to objects detected nearby.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Breadboard**
- **2x HC-SR04 Ultrasonic Distance Sensors**
- **2x Servo Motors**
- Jumper wires

---

## Circuit Connections

| Component | Trigger / Signal Pin | Echo Pin | Power | Ground | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Ultrasonic Sensor 1** | Pin 6 (Trigger) | Pin 5 | 5V | GND | Detects objects for Barrier 1 |
| **Ultrasonic Sensor 2** | Pin 8 (Trigger) | Pin 7 | 5V | GND | Detects objects for Barrier 2 |
| **Servo Motor 1** | Pin 4 (Signal) | N/A | 5V | GND | Controls Barrier 1 |
| **Servo Motor 2** | Pin 9 (Signal) | N/A | 5V | GND | Controls Barrier 2 |

---

## Purpose

This iteration combines ultrasonic distance measurement with servo motor control to automate two parking barriers independently.
This prototype demonstrates sensor-based automation and establishes the foundation for a more advanced smart parking system with independently controlled barriers.