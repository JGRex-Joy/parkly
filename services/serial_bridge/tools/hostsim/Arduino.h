#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <deque>
#include <string>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
enum { A0 = 14, A1, A2, A3, A4, A5 };

static unsigned long g_now = 0;          
static int g_pin[64];                    
static int g_dist_cm[64];                
static int g_servo[64];                  
static std::deque<int> g_q[64];          // scripted per-echo-pin readings (consumed first; 999 = lost echo)

inline unsigned long millis() { return g_now; }
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t pin, uint8_t v) { g_pin[pin] = v; }
inline void delayMicroseconds(unsigned int) {}
inline unsigned long pulseIn(uint8_t echo, uint8_t, unsigned long timeoutUs) {
  int cm = g_dist_cm[echo];
  if (!g_q[echo].empty()) { cm = g_q[echo].front(); g_q[echo].pop_front(); }
  if (cm >= 999) return 0;
  unsigned long us = (unsigned long)cm * 58UL;   // cm 0 => us 0 => 'no echo' (same as hardware timeout)
  return us > timeoutUs ? 0 : us;
}

struct SerialStub {
  std::deque<char> in;
  std::string line;
  void begin(unsigned long) {}
  int available() { return (int)in.size(); }
  int read() { char c = in.front(); in.pop_front(); return (unsigned char)c; }
  void print(char c) {
    if (c == '\n') { printf("[%lu] %s\n", g_now, line.c_str()); line.clear(); }
    else line.push_back(c);
  }
  void print(const char *s) { for (; *s; ++s) print(*s); }
};
static SerialStub Serial;
