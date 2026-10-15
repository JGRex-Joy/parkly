# Prototype v04

Prototype v0.4 scales up the sensor-driven concept into a **fully automated 4-slot smart parking system**[cite: 6, 7]. This version combines multiple ultrasonic distance sensors with individual status LEDs to monitor multiple parking bays simultaneously[cite: 6, 7].

---

## Components
* **1x Arduino Uno** microcontroller[cite: 7]
* **1x Breadboard**[cite: 7]
* **4x HC-SR04 Ultrasonic Distance Sensors** (one per parking bay)[cite: 6, 7]
* **4x Red LEDs** (occupancy indicators for spots 1 to 4)[cite: 6, 7]
* **4x Current-limiting resistors**[cite: 7]
* Jumper wires[cite: 7]

---

## Circuit Connections

| Parking Slot | Trigger Pin | Echo Pin | LED Control Pin | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Slot 1** | Pin 2[cite: 6, 7] | Pin 3[cite: 6, 7] | Pin 4[cite: 6, 7] | Monitored by Sensor 1 and indicated by LED 1[cite: 6, 7] |
| **Slot 2** | Pin 5[cite: 6, 7] | Pin 6[cite: 6, 7] | Pin 7[cite: 6, 7] | Monitored by Sensor 2 and indicated by LED 2[cite: 6, 7] |
| **Slot 3** | Pin 8[cite: 6, 7] | Pin 9[cite: 6, 7] | Pin 10[cite: 6, 7] | Monitored by Sensor 3 and indicated by LED 3[cite: 6, 7] |
| **Slot 4** | Pin 11[cite: 6, 7] | Pin 12[cite: 6, 7] | Pin 13[cite: 6, 7] | Monitored by Sensor 4 and indicated by LED 4[cite: 6, 7] |

---

## Purpose
This iteration achieves a complete multi-bay prototype of the smart parking system[cite: 6, 7]. A reusable function polls each HC-SR04 sensor sequentially[cite: 6]. If an object (such as a vehicle) is detected within 150 cm of a specific sensor, that slot's corresponding LED lights up to signal occupancy; otherwise, the LED stays off to show that the space is free[cite: 6].