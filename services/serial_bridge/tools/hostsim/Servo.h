#pragma once
#include "Arduino.h"
class Servo {
  uint8_t pin_ = 0;
public:
  void attach(uint8_t pin) { pin_ = pin; }
  void write(int angle) { g_servo[pin_] = angle; }
};
