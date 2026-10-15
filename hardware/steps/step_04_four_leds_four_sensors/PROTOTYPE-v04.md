# Prototype v04

Prototype v04 expands the Smart Parking System into a **fully automated 4-slot parking system**. Each parking space is monitored by an ultrasonic distance sensor, while an individual LED indicates whether the space is occupied.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Breadboard**
- **4x HC-SR04 Ultrasonic Distance Sensors** (one per parking space)
- **4x Red LEDs** (indicating occupied parking spaces)
- **4x Current-limiting resistors**
- Jumper wires

---

## Circuit Connections

| Parking Slot | Trigger Pin | Echo Pin | LED Control Pin | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Parking Slot 1** | Pin 3 | Pin 2 | Pin 4 | Monitored by Sensor 1 and indicated by LED 1 |
| **Parking Slot 2** | Pin 6 | Pin 5 | Pin 7 | Monitored by Sensor 2 and indicated by LED 2 |
| **Parking Slot 3** | Pin 10 | Pin 9 | Pin 8 | Monitored by Sensor 3 and indicated by LED 3 |
| **Parking Slot 4** | Pin 13 | Pin 12 | Pin 11 | Monitored by Sensor 4 and indicated by LED 4 |

---

## Purpose

This iteration introduces automated parking space detection using ultrasonic distance sensors. The Arduino measures the distance detected by each sensor and controls the corresponding LED based on the result. 
This prototype demonstrates the integration of multiple sensors, digital outputs, and a reusable function to manage all four parking spaces within a single system.