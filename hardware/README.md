# Smart Parking System — Arduino Project

## Project Overview

The Smart Parking System is an Arduino-based project designed to monitor parking space occupancy and automate vehicle barriers. The project was developed through **eight prototypes**, progressing from basic LED control to a complete system integrating ultrasonic distance sensors, LED indicators, and servo-controlled gates.

Each prototype introduces new functionality, allowing the system to be developed, tested, and improved step by step.

---

## Components

- **1x Arduino Uno** microcontroller
- **1x Breadboard**
- **6x HC-SR04 Ultrasonic Distance Sensors**
- **4x Red LEDs**
- **4x Current-limiting resistors**
- **2x Servo Motors** 
- Jumper wires

---

## Prototype Progression

### Prototype v01 — Basic LED Control

**Description:** Introduced basic digital output control using an Arduino and an LED.

**Components:**
- Arduino Uno
- 1x LED
- 1x Current-limiting resistor
- Jumper wires

**Purpose:** Learn basic Arduino programming, digital output pins, and LED control.

### Prototype v02 — Four Parking Indicators

**Description:** Expanded the circuit to control four LEDs, representing four individual parking spaces.

**Components:**
- Arduino Uno
- Breadboard
- 4x Red LEDs
- 4x Current-limiting resistors
- Jumper wires

**Purpose:** Test multiple digital outputs and establish a visual indicator for each parking space.

### Prototype v03 — Ultrasonic Detection

**Description:** Introduced ultrasonic distance measurement to detect nearby objects and connect sensor readings to parking status indicators.

**Components:**
- Arduino Uno
- HC-SR04 Ultrasonic Distance Sensor
- LEDs and current-limiting resistors
- Breadboard
- Jumper wires

**Purpose:** Learn distance measurement and sensor-based control, preparing the system for automatic parking detection.

### Prototype v04 — Four-Slot Parking Detection

**Description:** Integrated four ultrasonic sensors with four LEDs to monitor four parking spaces independently.

**Components:**
- Arduino Uno
- Breadboard
- 4x HC-SR04 Ultrasonic Distance Sensors
- 4x Red LEDs
- 4x Current-limiting resistors
- Jumper wires

**Purpose:** Detect occupied parking spaces using a 150 cm distance threshold. Each LED turns on when its corresponding space is detected as occupied.

### Prototype v05 — Single Servo Motor

**Description:** Introduced a servo motor controlled by the Arduino to simulate a parking barrier.

**Components:**
- Arduino Uno
- 1x Servo Motor
- Jumper wires

**Purpose:** Learn servo positioning and establish the foundation for an automated gate.

### Prototype v06 — Dual Servo Control

**Description:** Expanded servo control to operate two motors simultaneously.

**Components:**
- Arduino Uno
- Breadboard
- 2x Servo Motors
- Jumper wires

**Purpose:** Test independent servo connections and prepare for separate entrance and exit barriers.

### Prototype v07 — Automated Dual Gates

**Description:** Integrated two ultrasonic sensors with two servo motors to control entrance and exit barriers automatically.

**Components:**
- Arduino Uno
- Breadboard
- 2x HC-SR04 Ultrasonic Distance Sensors
- 2x Servo Motors
- Jumper wires

**Purpose:** Open each gate when its corresponding sensor detects an object within 150 cm and close it when no object is detected within that range.

### Prototype v08 — Complete Smart Parking System

**Description:** Combined the four-slot parking detection system with the automated dual-gate system into one integrated prototype.

**Components:**
- Arduino Uno
- Breadboard
- 6x HC-SR04 Ultrasonic Distance Sensors
- 4x Red LEDs
- 4x Current-limiting resistors
- 2x Servo Motors
- Jumper wires

**Purpose:** Monitor four parking spaces, indicate occupancy using LEDs, and automate entrance and exit barriers. The entrance remains closed when all four spaces are occupied, while the exit remains operational so vehicles can leave.

---

## System Workflow

1. **Detect parking occupancy:** Four ultrasonic sensors measure the distance to objects in their respective parking spaces.
2. **Update indicators:** Each LED turns on when its parking space is detected as occupied and turns off otherwise.
3. **Calculate availability:** The Arduino counts occupied spaces and determines whether any spaces remain available.
4. **Control the entrance:** The entrance barrier opens when a vehicle is detected and at least one parking space is available.
5. **Control the exit:** The exit barrier opens when its sensor detects a vehicle, regardless of parking availability.

---

## Final Result

The project demonstrates the step-by-step development of an automated parking system using Arduino, ultrasonic distance measurement, digital outputs, and servo motor control. The final prototype integrates occupancy monitoring and gate automation, providing a foundation for future improvements such as an LCD displaying available spaces, improved gate timing, and more advanced parking management.
