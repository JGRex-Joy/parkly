# Smart Parking System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hardware: Arduino UNO](https://img.shields.io/badge/Hardware-Arduino%20UNO-00979D?logo=arduino&logoColor=white)](hardware/)
[![Mobile: React Native](https://img.shields.io/badge/Mobile-React%20Native-61DAFB?logo=react&logoColor=black)](services/mobile_app/)
[![Bridge & OCR: Python](https://img.shields.io/badge/Services-Python%203.10+-3776AB?logo=python&logoColor=white)](services/)
[![Docs: Architecture PDF](https://img.shields.io/badge/Docs-PDF%20Report-red?logo=adobeacrobatreader&logoColor=white)](docs/documentation.pdf)

An end-to-end automated parking management prototype integrating microcontrollers, computer vision (OCR), a PySerial hardware bridge, and mobile interfaces.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Hardware ["Hardware Layer (Arduino UNO)"]
        US[6x Ultrasonic Sensors] -->|Distance Tracking| MCU[Arduino UNO]
        MCU -->|Status LEDs| LED[4x LEDs]
        MCU -->|Gate Barrier 1| Servo1[SG90 Entrance Servo]
        MCU -->|Gate Barrier 2| Servo2[SG90 Exit Servo]
    end

    subgraph Edge ["Cameras & Hardware Bridge"]
        Cam1[Entrance Cam] & Cam2[Exit Cam] -->|RTSP Video Stream| OCR[OCR Service]
        MCU <-->|UART / Serial Data| Bridge[PySerial Bridge]
    end

    subgraph Cloud ["Software Layer"]
        OCR -->|Plate Number| Backend[Backend Service]
        Bridge <-->|REST / WebSockets| Backend
        Backend <-->|Live Slots & QR Payment UI| RN[React Native App]
    end
```

---

## Key Features

* **Automated Entry & Exit:** Camera-based OCR plate recognition triggers entrance and exit servo barriers.
* **Real-time Slot Occupancy:** 6 ultrasonic sensors continuously track parking space availability and update visual LED indicators.
* **Hardware-to-Cloud Bridge:** A lightweight Python `pyserial` gateway translating Arduino UART signals into REST/WebSocket backend events.
* **Dual-Display Mobile Interface:** React Native screens serving as real-time available slot counters at entry and dynamic mock QR code payment points at exit.

---

## Hardware Components

| Component | Qty | Description |
| :--- | :---: | :--- |
| **Arduino UNO R3** | 1 | Primary hardware controller unit |
| **HC-SR04 Ultrasonic Sensors** | 6 | Parking space occupancy detection |
| **SG90 Micro Servos** | 2 | Entrance and exit barrier gate control |
| **Status LEDs** | 4 | Local visual indicators for slot availability |
| **Solderless Breadboard** | 1 | Power distribution and signal routing |
| **Smartphones** | 2 | IP camera streaming sources & React Native displays |

> *TinkerCAD 3D models, schematics, and iterative build steps are stored in [`hardware/steps/`](./hardware/steps/).*

---

## License

Distributed under the [MIT License](LICENSE).