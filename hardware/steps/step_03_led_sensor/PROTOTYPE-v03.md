# Prototype v03

Prototype v03 introduces distance measurement using an **HC-SR04 ultrasonic sensor**, transitioning the smart parking system from a static indicator model to a dynamic, sensor-driven setup[cite: 4, 5]. 

---

## Components
* **1x Arduino Uno** microcontroller[cite: 5]
* **1x Half-size Breadboard**[cite: 5]
* **1x HC-SR04 Ultrasonic Distance Sensor**[cite: 5]
* **1x Red LED** (representing a single monitored parking spot)[cite: 4, 5]
* **1x Current-limiting resistor**[cite: 5]
* Jumper wires[cite: 5]

---

## Circuit Connections

| Component / Pin | Arduino Pin / Rail | Description |
| :--- | :--- | :--- |
| **HC-SR04 VCC** | 5V Power Pin | Powered via the Arduino 5V output[cite: 5] |
| **HC-SR04 TRIG** | Digital Pin 8 | Sends out the ultrasonic trigger pulse[cite: 4, 5] |
| **HC-SR04 ECHO** | Digital Pin 9 | Receives the returning echo pulse[cite: 4, 5] |
| **HC-SR04 GND** | Ground Rail (`-`) | Connected to the common ground[cite: 5] |
| **LED Anode** | Digital Pin 10 | Controlled via a current-limiting resistor[cite: 4, 5] |
| **LED Cathode** | Ground Rail (`-`) | Connected to the shared ground[cite: 5] |

---

## Purpose
This iteration adds proximity detection to simulate a single parking bay monitor[cite: 4, 5]. The ultrasonic sensor calculates the distance of an object (such as a car) in real-time[cite: 4, 5]. If an object is detected within a threshold of 150 cm, the LED turns on to indicate that the parking space is occupied; otherwise, it remains off to show that the spot is available[cite: 4, 5].