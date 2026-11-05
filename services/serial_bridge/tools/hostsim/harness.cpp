#include "Arduino.h"
#include "Servo.h"
#include "../../arduino/smart_parking/smart_parking.ino"
#include <iostream>
#include <sstream>

int main() {
  for (int i = 0; i < 64; i++) g_dist_cm[i] = 999;
  setup();
  std::string cmd;
  while (std::getline(std::cin, cmd)) {
    std::istringstream is(cmd);
    std::string op;
    is >> op;
    if (op == "T") {
      unsigned long n; is >> n;
      for (unsigned long i = 0; i < n; i++) { g_now++; loop(); }
    } else if (op == "D") {
      int idx, cm; is >> idx >> cm;
      g_dist_cm[echoPin[idx]] = cm;
    } else if (op == "Q") {   // Q <sensor idx> v1 v2 ... : next readings of that sensor, then fall back to D
      int idx, v; is >> idx;
      while (is >> v) g_q[echoPin[idx]].push_back(v);
    } else if (op == "L") {
      std::string frame; is >> frame;
      for (char c : frame) Serial.in.push_back(c);
      Serial.in.push_back('\n');
    } else if (op == "R") {  
      int n; is >> n;
      for (int i = 0; i < n; i++) Serial.in.push_back('x');
      Serial.in.push_back('\n');
    } else if (op == "P") {
      printf("[%lu] STAT entry_servo=%d exit_servo=%d leds=%d%d%d%d\n", g_now,
             g_servo[ENTRY_SERVO], g_servo[EXIT_SERVO],
             g_pin[SLOT_LED[0]], g_pin[SLOT_LED[1]], g_pin[SLOT_LED[2]], g_pin[SLOT_LED[3]]);
    }
  }
  return 0;
}
