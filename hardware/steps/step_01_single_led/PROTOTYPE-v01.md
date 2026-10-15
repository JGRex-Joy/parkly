# Prototype v01

A basic starter circuit demonstrating digital output control using an **Arduino Uno** and a breadboard (simulated in Tinkercad Circuits)[cite: 1].

## Components
* **Arduino Uno** development board[cite: 1]
* Breadboard[cite: 1]
* Red LED[cite: 1]
* Current-limiting resistor[cite: 1]
* Jumper wires[cite: 1]

## Circuit Connectionsn
* **Ground (GND):** The Arduino `GND` pin connects to the breadboard's negative power rail (`-`) via a black jumper wire[cite: 1].
* **Control Pin:** Digital **Pin 8** connects to the resistor and the LED's anode via a green jumper wire[cite: 1].
* **LED Grounding:** The LED cathode ties back into the shared ground rail[cite: 1].

## Purpose
This circuit serves as a foundational "Blink" setup[cite: 1]. The Arduino program toggles **Pin 8** between `HIGH` and `LOW` states to turn the red LED on and off, while the resistor safely limits the current to prevent component damage[cite: 1].