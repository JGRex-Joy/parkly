# Prototype v03

Prototype v03 introduces distance measurement using an **HC-SR04 ultrasonic sensor**, transitioning the smart parking system from a static indicator model to a dynamic, sensor-driven setup. 

---

## Components
* **1x Arduino Uno** microcontroller
* **1x Breadboard**
* **1x HC-SR04 Ultrasonic Distance Sensor**
* **1x Red LED** (representing a single monitored parking spot)
* **1x Current-limiting resistor**
* Jumper wires

---

## Circuit Connections

| Component / Pin | Arduino Pin / Rail | Description |
| :--- | :--- | :--- |
| **HC-SR04 VCC** | 5V Power Pin | Powered via the Arduino 5V output |
| **HC-SR04 TRIG** | Digital Pin 9 | Sends out the ultrasonic trigger pulse |
| **HC-SR04 ECHO** | Digital Pin 8 | Receives the returning echo pulse |
| **HC-SR04 GND** | Ground Rail | Connected to the common ground |
| **RED LED** | Pin 7 | Controlled via `ledPin` |

---

## Purpose
This iteration adds proximity detection to simulate a single parking bay monitor. The ultrasonic sensor calculates the distance of an object (such as a car) in real-time. If an object is detected within a threshold of 150 cm, the LED turns on to indicate that the parking space is occupied; otherwise, it remains off to show that the spot is available.