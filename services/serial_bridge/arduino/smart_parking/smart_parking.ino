#include <Servo.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define FW_VERSION "1.1.0"
#define SERIAL_BAUD 115200UL

const uint8_t NUM_SLOTS = 4;
const uint8_t SLOT_TRIG[NUM_SLOTS] = {13, 10, 6, 3};
const uint8_t SLOT_ECHO[NUM_SLOTS] = {12, 9, 5, 2};
const uint8_t SLOT_LED[NUM_SLOTS]  = {11, 8, 7, 4};

const uint8_t ENTRY_ECHO = A0, ENTRY_TRIG = A1, ENTRY_SERVO = A2;
const uint8_t EXIT_ECHO  = A3, EXIT_TRIG  = A4, EXIT_SERVO  = A5;

const uint8_t NUM_SENSORS = 6;
const uint8_t S_ENTRY = 4;
const uint8_t S_EXIT  = 5;
uint8_t trigPin[NUM_SENSORS];
uint8_t echoPin[NUM_SENSORS];

const unsigned long ECHO_TIMEOUT_US = 8000UL;

const uint8_t SCHEDULE[] = {S_ENTRY, 0, S_EXIT, 1, S_ENTRY, 2, S_EXIT, 3};
const uint8_t SCHEDULE_LEN = sizeof(SCHEDULE);
uint8_t scheduleIdx = 0;

// ---------------------------------------------------------------------------------------------
// HC-SR04 noise handling for tiny, curved targets (Hot Wheels, ~7x4 cm)
//
// A small curved body reflects most of the 40 kHz burst AWAY from the sensor, so single readings
// are unreliable: random echo losses (pulseIn timeout -> "no echo") and the occasional 0-1 cm ringing
// glitch. The v1.0 firmware treated every single reading as a vote, so ONE lost echo reset the
// "occupied" streak (a parked car was never detected when >=1 reading in 3 was lost) and a burst of
// losses flipped the slot to FREE (measured: 15 false transitions in 12 s). v1.1 filters in 3 stages:
//
//   1. GLITCH REJECT  reading < MIN_VALID_CM (HC-SR04 cannot measure < 2 cm)  -> discarded entirely,
//                     it neither enters the window nor votes.
//   2. MEDIAN FILTER  the last `median` (default 5) valid readings are kept in a sliding window and
//                     the MEDIAN is used. Up to 2 of 5 samples can be garbage (outliers, echo loss =
//                     DIST_NO_ECHO = 65535 cm) and the result is still a good reading. The window
//                     must be full before the sensor may vote (no decisions on 1-2 samples).
//   3. HYSTERESIS +   the median is compared with a dead band (see updateSensor) and a state change
//      ASYMMETRIC     needs N consecutive agreeing medians: `debounce` (default 3) to become
//      DEBOUNCE       OCCUPIED, the larger `debounce_free` (default 6) to become FREE. Rationale:
//                     a false FREE (barrier closes on a car / slot is resold) is worse than a late
//                     FREE, and echo loss pushes readings towards "far", i.e. towards FREE.
// ---------------------------------------------------------------------------------------------
const uint8_t  MEDIAN_MAX    = 5;        // compile-time window capacity (RAM: 6 sensors x 10 B)
const uint16_t DIST_NO_ECHO  = 0xFFFF;   // pulseIn timeout: nothing came back (empty slot OR scattered)
const uint16_t MIN_VALID_CM  = 2;        // below this the HC-SR04 reading is an electrical glitch
const uint8_t  DBG_EVERY     = 4;        // with dbg=1: one DIST event per sensor per 4 medians

struct Sensor {
  bool state;                 // debounced, published state (true = occupied / vehicle present)
  uint8_t streak;             // consecutive medians that disagree with `state`
  uint16_t win[MEDIAN_MAX];   // sliding window of valid readings (cm, DIST_NO_ECHO = lost echo)
  uint8_t winCount;           // valid readings currently held (0..cfg.median)
  uint8_t winHead;            // next window cell to overwrite
  uint8_t dbgTick;            // DIST event rate limiter
};
Sensor sensors[NUM_SENSORS];

struct Config {
  uint16_t gateThrCm;     // occupied when median < this
  uint16_t slotThrCm;
  uint16_t hystCm;        // dead band: occupied sensors only free up above thr + hyst
  uint16_t debounce;      // consecutive medians needed to become OCCUPIED / vehicle present
  uint16_t debounceFree;  // consecutive medians needed to become FREE (should be > debounce)
  uint16_t median;        // window length 1..5 (1 = filter off, for A/B comparison)
  uint16_t sampleMs;
  uint16_t holdMs;
  uint16_t clearMs;
  uint16_t openDeg;
  uint16_t closedDeg;
  uint16_t hbMs;
  uint16_t dbg;           // 1 = stream DIST diagnostics (filtered distance) for threshold tuning
};
Config cfg = {40, 25, 5, 3, 6, 5, 25, 8000, 1500, 90, 0, 2000, 0};

struct CfgKey {
  const char *name;
  uint16_t *ptr;
  uint16_t minV;
  uint16_t maxV;
};
const CfgKey CFG_KEYS[] = {
  {"gate_thr",  &cfg.gateThrCm, 5, 400},
  {"slot_thr",  &cfg.slotThrCm, 5, 400},
  {"hyst",      &cfg.hystCm,    0, 50},
  {"debounce",  &cfg.debounce,  1, 20},
  {"debounce_free", &cfg.debounceFree, 1, 40},
  {"median",    &cfg.median,    1, MEDIAN_MAX},
  {"sample_ms", &cfg.sampleMs,  10, 500},
  {"hold_ms",   &cfg.holdMs,    500, 60000},
  {"clear_ms",  &cfg.clearMs,   0, 60000},
  {"open_deg",  &cfg.openDeg,   0, 180},
  {"closed_deg",&cfg.closedDeg, 0, 180},
  {"hb_ms",     &cfg.hbMs,      500, 60000},
  {"dbg",       &cfg.dbg,       0, 1},
};
const uint8_t NUM_CFG_KEYS = sizeof(CFG_KEYS) / sizeof(CFG_KEYS[0]);

const uint8_t SERVO_STEP_DEG = 3;
const uint8_t SERVO_STEP_MS = 15;

struct Barrier {
  Servo servo;
  uint8_t pin;
  uint8_t sensor;          
  const char *name;        
  uint8_t angle;           
  uint8_t target;          
  bool wantOpen;           
  bool settled;            
  bool clearing;           
  unsigned long holdUntil;
  unsigned long clearSince;
  unsigned long lastStep;
};
Barrier barriers[2];  

const uint8_t LINE_MAX = 72;
char rx[LINE_MAX];
uint8_t rxLen = 0;
bool rxOverflow = false;

uint16_t evtSeq = 0;
unsigned long lastSample = 0;
unsigned long lastHb = 0;

// Retransmission cache. A repeat is recognised by (seq AND frame checksum): a retransmit is
// byte-identical, whereas a NEW command that merely reuses an old seq number (bridge restarted while
// the board was NOT reset - port re-open does not always toggle DTR) differs and must be executed.
// v1.0 matched on seq alone and answered "ACK,OK,DUP" without moving the servo.
struct Done {
  uint16_t seq;
  uint8_t cs;
  bool ok;
  const char *detail;
};
const uint8_t DONE_N = 4;
Done done[DONE_N];
uint8_t doneHead = 0;
uint8_t curCs = 0;   // checksum of the frame being executed (stored with its result)

static void emitFrame(const char *payload) {
  uint8_t cs = 0;
  for (const char *p = payload; *p; ++p) cs ^= (uint8_t)*p;
  char tail[8];
  snprintf(tail, sizeof(tail), "*%02X", cs);
  Serial.print('$');
  Serial.print(payload);
  Serial.print(tail);
  Serial.print('\n');
}

static uint16_t nextEvtSeq() {
  evtSeq++;
  if (evtSeq == 0) evtSeq = 1;
  return evtSeq;
}

static void emitEvt(const char *name, const char *args) {
  char buf[60];
  snprintf(buf, sizeof(buf), "EVT,%u,%s%s%s", (unsigned)nextEvtSeq(), name,
           args[0] ? "," : "", args);
  emitFrame(buf);
}

static void reply(uint16_t seq, bool ok, const char *detail, bool dup) {
  char buf[48];
  if (ok) {
    if (dup) snprintf(buf, sizeof(buf), "ACK,%u,OK,DUP", (unsigned)seq);
    else if (detail && detail[0])
      snprintf(buf, sizeof(buf), "ACK,%u,OK,%s", (unsigned)seq, detail);
    else snprintf(buf, sizeof(buf), "ACK,%u,OK", (unsigned)seq);
  } else {
    snprintf(buf, sizeof(buf), "NAK,%u,%s", (unsigned)seq, detail);
  }
  emitFrame(buf);
}

static void buildState(char *out, size_t n) {
  char slots[NUM_SLOTS + 1];
  for (uint8_t i = 0; i < NUM_SLOTS; i++) slots[i] = sensors[i].state ? '1' : '0';
  slots[NUM_SLOTS] = 0;
  snprintf(out, n, "%s,%c,%c,%c,%c", slots,
           sensors[S_ENTRY].state ? '1' : '0', sensors[S_EXIT].state ? '1' : '0',
           barriers[0].wantOpen ? '1' : '0', barriers[1].wantOpen ? '1' : '0');
}

static void emitState() {
  char args[24];
  buildState(args, sizeof(args));
  emitEvt("STATE", args);
}

static void emitHeartbeat() {
  char st[24], args[48];
  buildState(st, sizeof(st));
  snprintf(args, sizeof(args), "%lu,%s", millis() / 1000UL, st);
  emitEvt("HB", args);
}

static uint16_t readCm(uint8_t i) {
  digitalWrite(trigPin[i], LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin[i], HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin[i], LOW);
  unsigned long us = pulseIn(echoPin[i], HIGH, ECHO_TIMEOUT_US);
  if (us == 0) return DIST_NO_ECHO;   // timeout: no usable echo within ~137 cm
  return (uint16_t)(us / 58UL);       // 58 us per cm round trip
}

static void onSensorChange(uint8_t i) {
  char args[16];
  if (i < NUM_SLOTS) {
    digitalWrite(SLOT_LED[i], sensors[i].state ? HIGH : LOW);
    snprintf(args, sizeof(args), "%u,%c", (unsigned)(i + 1), sensors[i].state ? '1' : '0');
    emitEvt("SLOT", args);
  } else {
    snprintf(args, sizeof(args), "%s,%c", i == S_ENTRY ? "entry" : "exit",
             sensors[i].state ? '1' : '0');
    emitEvt("GATE", args);
  }
}

static void pushSample(Sensor &s, uint16_t cm) {
  s.win[s.winHead] = cm;
  s.winHead = (uint8_t)((s.winHead + 1) % cfg.median);
  if (s.winCount < cfg.median) s.winCount++;
}

static uint16_t medianOf(const Sensor &s) {
  uint16_t tmp[MEDIAN_MAX];
  uint8_t n = s.winCount;
  for (uint8_t k = 0; k < n; k++) tmp[k] = s.win[k];      // window order is irrelevant
  for (uint8_t a = 1; a < n; a++) {                        // insertion sort, n <= 5
    uint16_t v = tmp[a];
    int8_t b = (int8_t)a - 1;
    while (b >= 0 && tmp[b] > v) { tmp[b + 1] = tmp[b]; b--; }
    tmp[b + 1] = v;
  }
  return tmp[n / 2];
}

static void resetWindows() {   // called when `median` is reconfigured
  for (uint8_t k = 0; k < NUM_SENSORS; k++) { sensors[k].winCount = 0; sensors[k].winHead = 0; sensors[k].streak = 0; }
}

static void emitDist(uint8_t i, uint16_t med, uint16_t raw) {
  char args[28];
  if (i < NUM_SLOTS) snprintf(args, sizeof(args), "%u,%u,%u", (unsigned)(i + 1), (unsigned)med, (unsigned)raw);
  else snprintf(args, sizeof(args), "%s,%u,%u", i == S_ENTRY ? "entry" : "exit", (unsigned)med, (unsigned)raw);
  emitEvt("DIST", args);
}

static void updateSensor(uint8_t i, uint16_t cm) {
  Sensor &s = sensors[i];

  // Stage 1: glitch reject (0..1 cm). Not a measurement: no vote, no window entry, no streak change.
  if (cm < MIN_VALID_CM) return;

  // Stage 2: median of the last `median` valid readings. DIST_NO_ECHO counts as "very far".
  pushSample(s, cm);
  if (s.winCount < cfg.median) return;       // window still filling after boot/reconfig: abstain
  uint16_t med = medianOf(s);
  if (cfg.dbg && ++s.dbgTick >= DBG_EVERY) { s.dbgTick = 0; emitDist(i, med, cm); }

  // Stage 3: hysteresis. Two thresholds with a dead band between them:
  //   FREE     -> OCCUPIED  when med <  thr            (clearly close)
  //   OCCUPIED -> FREE      when med >  thr + hyst     (clearly far)
  //   thr <= med <= thr+hyst: both states are "stable" -> the reading votes for NO change.
  uint16_t thr = (i < NUM_SLOTS) ? cfg.slotThrCm : cfg.gateThrCm;
  bool want = s.state ? (med <= (uint16_t)(thr + cfg.hystCm)) : (med < thr);
  if (want == s.state) { s.streak = 0; return; }   // agrees with current state: restart the count

  // Debounce, asymmetric: N CONSECUTIVE disagreeing medians are required; any agreeing median
  // resets the streak. Becoming FREE needs more evidence than becoming OCCUPIED.
  uint16_t need = want ? cfg.debounce : cfg.debounceFree;
  if (++s.streak >= need) {
    s.state = want;
    s.streak = 0;
    onSensorChange(i);
  }
}

static void sampleNext() {
  uint8_t i = SCHEDULE[scheduleIdx];
  scheduleIdx = (scheduleIdx + 1) % SCHEDULE_LEN;
  updateSensor(i, readCm(i));
}

static void openBarrier(uint8_t g, unsigned long holdMs) {
  Barrier &b = barriers[g];
  b.wantOpen = true;
  b.target = (uint8_t)cfg.openDeg;
  b.holdUntil = millis() + holdMs;
  b.clearing = false;
  b.settled = (b.angle == b.target);
}

static void closeBarrier(uint8_t g) {
  Barrier &b = barriers[g];
  b.wantOpen = false;
  b.target = (uint8_t)cfg.closedDeg;
  b.clearing = false;
  b.settled = (b.angle == b.target);
}

static void updateBarrier(uint8_t g, unsigned long now) {
  Barrier &b = barriers[g];

  if (b.wantOpen && (long)(now - b.holdUntil) >= 0) {
    if (sensors[b.sensor].state) {
      b.clearing = false;  
    } else if (!b.clearing) {
      b.clearing = true;
      b.clearSince = now;
    } else if (now - b.clearSince >= cfg.clearMs) {
      closeBarrier(g);
    }
  }

  if (b.angle != b.target && now - b.lastStep >= SERVO_STEP_MS) {
    b.lastStep = now;
    if (b.angle < b.target) {
      b.angle = (b.target - b.angle > SERVO_STEP_DEG) ? b.angle + SERVO_STEP_DEG : b.target;
    } else {
      b.angle = (b.angle - b.target > SERVO_STEP_DEG) ? b.angle - SERVO_STEP_DEG : b.target;
    }
    b.servo.write(b.angle);
  }

  if (!b.settled && b.angle == b.target) {
    b.settled = true;
    char args[16];
    snprintf(args, sizeof(args), "%s,%s", b.name, b.wantOpen ? "OPENED" : "CLOSED");
    emitEvt("BARRIER", args);
  }
}

static int gateIndex(const char *s) {
  if (strcmp(s, "entry") == 0) return 0;
  if (strcmp(s, "exit") == 0) return 1;
  return -1;
}

static bool parseUInt(const char *s, unsigned long maxV, unsigned long *out) {
  if (!s || !*s) return false;
  char *end;
  unsigned long v = strtoul(s, &end, 10);
  if (*end || v > maxV) return false;
  *out = v;
  return true;
}

static const Done *findDone(uint16_t seq, uint8_t cs) {
  for (uint8_t i = 0; i < DONE_N; i++)
    if (done[i].seq == seq && done[i].cs == cs) return &done[i];
  return NULL;
}

static void finish(uint16_t seq, bool ok, const char *detail) {
  done[doneHead].seq = seq;
  done[doneHead].cs = curCs;
  done[doneHead].ok = ok;
  done[doneHead].detail = detail;
  doneHead = (doneHead + 1) % DONE_N;
  reply(seq, ok, detail, false);
}

static uint8_t splitFields(char *s, char **tok, uint8_t maxTok) {
  uint8_t n = 0;
  tok[n++] = s;
  for (char *p = s; *p && n < maxTok; ++p) {
    if (*p == ',') {
      *p = 0;
      tok[n++] = p + 1;
    }
  }
  return n;
}

static void runCommand(uint16_t seq, char **tok, uint8_t n) {
  const char *name = tok[2];

  if (strcmp(name, "PING") == 0) {
    finish(seq, true, "");
  } else if (strcmp(name, "SYNC") == 0) {
    finish(seq, true, "");
    emitState();
  } else if (strcmp(name, "OPEN") == 0) {
    if (n < 4) { finish(seq, false, "BAD_ARGS"); return; }
    int g = gateIndex(tok[3]);
    if (g < 0) { finish(seq, false, "BAD_GATE"); return; }
    unsigned long hold = cfg.holdMs;
    if (n > 4 && !(parseUInt(tok[4], 60000UL, &hold) && hold >= 500)) {
      finish(seq, false, "BAD_VALUE");
      return;
    }
    bool already = barriers[g].wantOpen;
    openBarrier((uint8_t)g, hold);
    finish(seq, true, already ? "REFRESHED" : "");
  } else if (strcmp(name, "CLOSE") == 0) {
    if (n < 4) { finish(seq, false, "BAD_ARGS"); return; }
    int g = gateIndex(tok[3]);
    if (g < 0) { finish(seq, false, "BAD_GATE"); return; }
    if (sensors[barriers[g].sensor].state) { finish(seq, false, "VEHICLE_PRESENT"); return; }
    closeBarrier((uint8_t)g);
    finish(seq, true, "");
  } else if (strcmp(name, "CFG") == 0) {
    if (n < 5) { finish(seq, false, "BAD_ARGS"); return; }
    for (uint8_t i = 0; i < NUM_CFG_KEYS; i++) {
      if (strcmp(tok[3], CFG_KEYS[i].name) == 0) {
        unsigned long v;
        if (!parseUInt(tok[4], CFG_KEYS[i].maxV, &v) || v < CFG_KEYS[i].minV) {
          finish(seq, false, "BAD_VALUE");
          return;
        }
        *CFG_KEYS[i].ptr = (uint16_t)v;
        if (CFG_KEYS[i].ptr == &cfg.median) resetWindows();
        finish(seq, true, "");
        return;
      }
    }
    finish(seq, false, "BAD_KEY");
  } else {
    finish(seq, false, "UNKNOWN_CMD");
  }
}

static void handleLine(char *line) {
  if (line[0] != '$') return;  
  char *star = strrchr(line, '*');
  if (!star || strlen(star) != 3) { reply(0, false, "BAD_FRAME", false); return; }
  *star = 0;
  uint8_t cs = 0;
  for (const char *p = line + 1; *p; ++p) cs ^= (uint8_t)*p;
  char *end;
  unsigned long got = strtoul(star + 1, &end, 16);
  if (*end || got != cs) { reply(0, false, "CHECKSUM", false); return; }

  char *tok[6];
  uint8_t n = splitFields(line + 1, tok, 6);
  if (n < 3 || strcmp(tok[0], "CMD") != 0) { reply(0, false, "BAD_FRAME", false); return; }
  unsigned long seq;
  if (!parseUInt(tok[1], 65535UL, &seq) || seq == 0) { reply(0, false, "BAD_SEQ", false); return; }

  curCs = cs;
  const Done *d = findDone((uint16_t)seq, cs);
  if (d) {  
    reply((uint16_t)seq, d->ok, d->detail, true);
    return;
  }
  runCommand((uint16_t)seq, tok, n);
}

static void pollSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (rxOverflow) reply(0, false, "TOO_LONG", false);
      else if (rxLen > 0) { rx[rxLen] = 0; handleLine(rx); }
      rxLen = 0;
      rxOverflow = false;
      continue;
    }
    if (rxLen < LINE_MAX - 1) rx[rxLen++] = c;
    else rxOverflow = true;
  }
}

void setup() {
  trigPin[S_ENTRY] = ENTRY_TRIG; echoPin[S_ENTRY] = ENTRY_ECHO;
  trigPin[S_EXIT]  = EXIT_TRIG;  echoPin[S_EXIT]  = EXIT_ECHO;
  for (uint8_t i = 0; i < NUM_SLOTS; i++) {
    trigPin[i] = SLOT_TRIG[i];
    echoPin[i] = SLOT_ECHO[i];
    pinMode(SLOT_LED[i], OUTPUT);
    digitalWrite(SLOT_LED[i], LOW);
  }
  for (uint8_t i = 0; i < NUM_SENSORS; i++) {
    pinMode(trigPin[i], OUTPUT);
    digitalWrite(trigPin[i], LOW);
    pinMode(echoPin[i], INPUT);
    sensors[i].state = false;
    sensors[i].streak = 0;
    sensors[i].winCount = 0;
    sensors[i].winHead = 0;
    sensors[i].dbgTick = 0;
  }

  barriers[0].pin = ENTRY_SERVO; barriers[0].sensor = S_ENTRY; barriers[0].name = "entry";
  barriers[1].pin = EXIT_SERVO;  barriers[1].sensor = S_EXIT;  barriers[1].name = "exit";
  for (uint8_t g = 0; g < 2; g++) {
    barriers[g].angle = barriers[g].target = (uint8_t)cfg.closedDeg;
    barriers[g].wantOpen = false;
    barriers[g].settled = true;
    barriers[g].clearing = false;
    barriers[g].lastStep = 0;
    barriers[g].servo.attach(barriers[g].pin);
    barriers[g].servo.write(barriers[g].angle);
  }

  Serial.begin(SERIAL_BAUD);
  emitEvt("BOOT", FW_VERSION);
  emitState();
}

void loop() {
  pollSerial();
  unsigned long now = millis();

  if (now - lastSample >= cfg.sampleMs) {
    lastSample = now;
    sampleNext();
  }
  updateBarrier(0, now);
  updateBarrier(1, now);

  if (now - lastHb >= cfg.hbMs) {
    lastHb = now;
    emitHeartbeat();
  }
}
