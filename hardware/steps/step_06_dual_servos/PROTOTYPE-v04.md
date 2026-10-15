# Prototype v06

Prototype v06 introduces **two servo motors** to the Smart Parking System. Both servos are controlled by the Arduino Uno and positioned at 90 degrees when the system starts. This prototype establishes the foundation for controlling two separate parking barriers.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Breadboard**
- **2x Servo Motors**
- Jumper wires

---

## Circuit Connections

| Servo Motor | Signal Pin | Power | Ground | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Servo 1** | Pin 9 | 5V | GND | Controlled by the Arduino to set its position |
| **Servo 2** | Pin 10 | 5V | GND | Controlled by the Arduino to set its position |

---

## Purpose

This iteration demonstrates the simultaneous control of two servo motors using the Arduino Servo library. When the Arduino starts, both servos move to **90 degrees** and remain at that position. The breadboard provides a convenient way to distribute power and ground connections to both servos. 
This prototype prepares the system for future integration, where the two servos can operate as separate parking barriers controlled by ultrasonic sensors.