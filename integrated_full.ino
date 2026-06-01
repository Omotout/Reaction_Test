/*
 * Integrated Sketch: EMS (L298N H-Bridge) + LED (Red/YG) + Touch Sensors (Right/Left)
 *
 * Hardware: Arduino Micro (production), UNO compatible. 5V logic.
 *
 * ================== FastestBaseline protocol (Unity conductor) ==================
 * Unity (PC) is the conductor; this firmware executes the time-critical path
 * (LED on -> optional scheduled EMS -> touch -> micros() RT) and returns results.
 * Each TRIAL/EMSLAT carries a sequence <id>; this firmware ECHOES the same <id>
 * in its result line so Unity can discard stale results from a timed-out prior
 * trial (prevents off-by-one RT misalignment). Exactly ONE result line is
 * returned per TRIAL/EMSLAT.
 *
 * Unity -> Arduino:
 *   TRIAL,<id>,<led>,<resp>,<emsSide>,<emsDelayUs>
 *       led in {R,G}; resp in {R,L} (informational; detection is BILATERAL);
 *       emsSide in {R,L,N}; emsDelayUs = us after LED onset to fire EMS.
 *       Lights LED, t0=micros(), polls BOTH electrodes, optionally fires EMS at
 *       t0+emsDelayUs. Reports the side actually touched first (or NONE).
 *   EMSLAT,<id>,<side>      side in {R,L}. No LED. Fires EMS (t0=EMS onset),
 *                           waits for <side> touch, measures latency.
 *   THR,<side>,<value>      Set per-side touch detection threshold.
 *   EMSCFG,<width>,<count>,<burst>,<interval>   Set EMS waveform params (us / counts).
 *   EMS:R / EMS:L           Manual single biphasic burst (bench / intensity tuning).
 *   LED:R / LED:G / LED:BOTH / LED:OFF
 *   TOUCH:LIVE / TOUCH:STOP / BASELINE / DET:R / DET:L / DET:STOP / TRIAL:R / TRIAL:L
 *   STATUS / HELP / RESET
 *
 * Arduino -> Unity:
 *   TRIAL_RESULT,<id>,<touchedSide>,<rtUs>,<peak>,<emsFired>   (touchedSide R/L)
 *   TRIAL_RESULT,<id>,NONE,-1,0,<emsFired>                     (response timeout)
 *   EMSLAT_RESULT,<id>,<side>,<latencyUs>                      (or ...,-1 on timeout)
 *   OK:THR:<side>:<value> / OK:EMSCFG:<...> / OK:EMS:<side> / OK:LED:<...> / OK:RESET
 *
 * ================== EMS waveform (default; configurable via EMSCFG) ==================
 *   One stimulation = burstCount biphasic cycles, pulseWidth us per phase.
 *   Default: 3 cycles x (50us +phase, 50us rest, 50us -phase, 50us rest) ~= 600us.
 *   +V and -V are NEVER simultaneous; they alternate in time.
 *   L298N: +V => pinA=HIGH,pinB=LOW ; 0V => both LOW ; -V => pinA=LOW,pinB=HIGH
 *
 * --- Pin map ---
 *   D3  : EMS Left A  (L298N IN1, 撓屈)      D4  : EMS Left B  (IN2)
 *   D5  : EMS Right A (L298N IN3, 尺屈)      D6  : EMS Right B (IN4)
 *   D8  : Touch SEND (shared)
 *   D9  : Touch RECV Right (330kΩ to D8)     D10 : Touch RECV Left (330kΩ to D8)
 *   D11 : LED Red (330Ω)   D12 : LED YG (147Ω)   D13 : built-in LED (feedback)
 *
 * Baud: 115200
 *
 * NOTE (unverified on hardware): RT/touch timing depends on the capacitive sense
 * loop. SETTLE_US and per-side thresholds are bench-tuning knobs (see B5).
 * EMS amplitude/current is set by the L298N supply (hardware), NOT by these params.
 */

// ---------------- Pin definitions ----------------
const int PIN_EMS_LEFT_A   = 3;
const int PIN_EMS_LEFT_B   = 4;
const int PIN_EMS_RIGHT_A  = 5;
const int PIN_EMS_RIGHT_B  = 6;
const int PIN_SEND         = 8;
const int PIN_RECV_RIGHT   = 9;
const int PIN_RECV_LEFT    = 10;
const int PIN_LED_RED      = 11;
const int PIN_LED_GREEN    = 12;
const int PIN_LED_FB       = 13;

// ---------------- Touch settings ----------------
const int           TOUCH_THRESHOLD   = 3;     // legacy default (LIVE/BASELINE/DET)
const unsigned long TOUCH_COOLDOWN_MS = 1000;
const unsigned long RT_TIMEOUT_MS     = 5000;  // legacy TRIAL:R/L

// Per-side detection thresholds for the FastestBaseline protocol (settable via THR).
int thresholdRight = TOUCH_THRESHOLD;
int thresholdLeft  = TOUCH_THRESHOLD;

// Settle time after each fast capacitive read (us). Lets the line discharge
// between samples. Bounds RT sampling resolution. TUNE IN B5.
const unsigned int SETTLE_US = 200;

// Response window for TRIAL/EMSLAT (ms). Must stay BELOW Unity's resultTimeoutSec
// (default 3000ms) so Unity's safety-net never trips before this returns.
const unsigned long RESP_WINDOW_MS = 2000;

// ---------------- EMS settings (defaults; configurable via EMSCFG) ----------------
int pulseWidth    = 50;     // us per phase
int pulseCount    = 1;      // number of bursts (1 = single stimulation)
int burstCount    = 3;      // biphasic cycles per burst
int pulseInterval = 40000;  // us between bursts (unused when pulseCount=1)

// EMS safety cooldown (firmware-side refractory)
unsigned long lastEmsTriggerMs         = 0;
const unsigned int MIN_EMS_INTERVAL_MS = 500;

// ---------------- Modes (legacy bench tools) ----------------
enum Mode { MODE_IDLE, MODE_LIVE, MODE_BASELINE, MODE_DETECT_RIGHT, MODE_DETECT_LEFT };
Mode currentMode = MODE_IDLE;

int           detectionCount   = 0;
unsigned long lastDetectionMs  = 0;
unsigned long testStartMs      = 0;
bool          inTouchEvent     = false;
long          currentPeak      = 0;

long   bMin, bMax;
double bMean, bM2;
long   bN;
unsigned long baselineStartMs = 0;

// ---------------- Touch read ----------------
// Legacy read with 1ms settle (used by LIVE/BASELINE/DET monitor modes).
int readPin(int recvPin) {
  int t = 0;
  digitalWrite(PIN_SEND, HIGH);
  while (digitalRead(recvPin) != HIGH) {
    t++;
    if (t > 10000) break;
  }
  digitalWrite(PIN_SEND, LOW);
  delay(1);
  return t;
}

// Fast read for RT loops: short microsecond settle instead of delay(1).
int readPinFast(int recvPin) {
  int t = 0;
  digitalWrite(PIN_SEND, HIGH);
  while (digitalRead(recvPin) != HIGH) {
    t++;
    if (t > 10000) break;
  }
  digitalWrite(PIN_SEND, LOW);
  delayMicroseconds(SETTLE_US);
  return t;
}

// ---------------- Stats helpers ----------------
void statsReset() { bMin = 2147483647L; bMax = -2147483648L; bN = 0; bMean = 0; bM2 = 0; }
void statsUpdate(long x) {
  bN++;
  if (x < bMin) bMin = x;
  if (x > bMax) bMax = x;
  double delta = x - bMean;
  bMean += delta / bN;
  bM2 += delta * (x - bMean);
}
double statsStdev() { if (bN < 2) return 0; return sqrt(bM2 / (bN - 1)); }

// ---------------- LED helpers ----------------
void allLedsOff() {
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_FB, LOW);
}

// ---------------- EMS helpers ----------------
void stopEMS() {
  digitalWrite(PIN_EMS_LEFT_A, LOW);
  digitalWrite(PIN_EMS_LEFT_B, LOW);
  digitalWrite(PIN_EMS_RIGHT_A, LOW);
  digitalWrite(PIN_EMS_RIGHT_B, LOW);
}

void safeDelayMicroseconds(unsigned long us) {
  if (us >= 1000) { delay(us / 1000); delayMicroseconds(us % 1000); }
  else            { delayMicroseconds(us); }
}

// Blocking biphasic burst (~pulseWidth*4*burstCount us). Polarity reversed via H-bridge.
void triggerBiphasicEMS(int pinA, int pinB) {
  for (int i = 0; i < pulseCount; i++) {
    for (int j = 0; j < burstCount; j++) {
      digitalWrite(pinA, HIGH); digitalWrite(pinB, LOW);  safeDelayMicroseconds(pulseWidth); // +
      digitalWrite(pinA, LOW);  digitalWrite(pinB, LOW);  safeDelayMicroseconds(pulseWidth); // 0
      digitalWrite(pinA, LOW);  digitalWrite(pinB, HIGH); safeDelayMicroseconds(pulseWidth); // -
      digitalWrite(pinA, LOW);  digitalWrite(pinB, LOW);  safeDelayMicroseconds(pulseWidth); // 0
    }
    if (i < pulseCount - 1) safeDelayMicroseconds(pulseInterval);
  }
  stopEMS();
}

bool tryFireEms(int pinA, int pinB, const char *label) {
  unsigned long now = millis();
  if (now - lastEmsTriggerMs < MIN_EMS_INTERVAL_MS) {
    Serial.print(F("COOLDOWN:")); Serial.println(label);
    return false;
  }
  triggerBiphasicEMS(pinA, pinB);
  lastEmsTriggerMs = millis();
  Serial.print(F("OK:EMS:")); Serial.println(label);
  return true;
}

// ---------------- CSV tokenizer ----------------
// Splits s into out[] by commas. Returns token count (<= maxTok).
int splitCsv(const String &s, String out[], int maxTok) {
  int n = 0, start = 0;
  while (n < maxTok) {
    int comma = s.indexOf(',', start);
    if (comma < 0) { out[n++] = s.substring(start); break; }
    out[n++] = s.substring(start, comma);
    start = comma + 1;
  }
  return n;
}

// ---------------- FastestBaseline trial ----------------
// TRIAL,<id>,<led>,<resp>,<emsSide>,<emsDelayUs>
void runTrialCmd(const String &cmd) {
  String tok[6];
  int n = splitCsv(cmd, tok, 6);
  if (n < 6) { Serial.println(F("ERR:TRIAL:ARGS")); return; }

  long id          = tok[1].toInt();
  char led         = tok[2].length() ? tok[2][0] : 'R';
  // tok[3] = resp (informational; detection is bilateral)
  char emsSide     = tok[4].length() ? tok[4][0] : 'N';
  unsigned long emsDelayUs = (unsigned long) tok[5].toInt();

  int ledPin = (led == 'G') ? PIN_LED_GREEN : PIN_LED_RED;

  bool emsEnabled = (emsSide == 'R' || emsSide == 'L');
  int emsA = -1, emsB = -1;
  if (emsSide == 'R') { emsA = PIN_EMS_RIGHT_A; emsB = PIN_EMS_RIGHT_B; }
  else if (emsSide == 'L') { emsA = PIN_EMS_LEFT_A; emsB = PIN_EMS_LEFT_B; }

  allLedsOff();
  unsigned long t0 = micros();
  digitalWrite(ledPin, HIGH);

  bool emsFired = false;
  char touched = 'N';
  unsigned long rtUs = 0;
  long peak = 0;
  unsigned long t0ms = millis();

  while (millis() - t0ms < RESP_WINDOW_MS) {
    // Scheduled EMS (blocking ~hundreds of us; touch not sampled during the burst).
    if (emsEnabled && !emsFired && (micros() - t0) >= emsDelayUs) {
      triggerBiphasicEMS(emsA, emsB);
      lastEmsTriggerMs = millis();
      emsFired = true;
    }
    int vR = readPinFast(PIN_RECV_RIGHT);
    if (vR > thresholdRight) { rtUs = micros() - t0; peak = vR; touched = 'R'; break; }
    int vL = readPinFast(PIN_RECV_LEFT);
    if (vL > thresholdLeft)  { rtUs = micros() - t0; peak = vL; touched = 'L'; break; }
  }
  digitalWrite(ledPin, LOW);

  Serial.print(F("TRIAL_RESULT,")); Serial.print(id); Serial.print(',');
  if (touched == 'N') {
    Serial.print(F("NONE,-1,0,"));
    Serial.println(emsFired ? 1 : 0);
  } else {
    Serial.print(touched); Serial.print(',');
    Serial.print(rtUs);    Serial.print(',');
    Serial.print(peak);    Serial.print(',');
    Serial.println(emsFired ? 1 : 0);
  }
}

// EMSLAT,<id>,<side>
void runEmsLatCmd(const String &cmd) {
  String tok[3];
  int n = splitCsv(cmd, tok, 3);
  if (n < 3) { Serial.println(F("ERR:EMSLAT:ARGS")); return; }

  long id  = tok[1].toInt();
  char side = tok[2].length() ? tok[2][0] : 'R';

  int emsA, emsB, recvPin, thr;
  if (side == 'L') { emsA = PIN_EMS_LEFT_A;  emsB = PIN_EMS_LEFT_B;  recvPin = PIN_RECV_LEFT;  thr = thresholdLeft; }
  else             { emsA = PIN_EMS_RIGHT_A; emsB = PIN_EMS_RIGHT_B; recvPin = PIN_RECV_RIGHT; thr = thresholdRight; side = 'R'; }

  allLedsOff();
  unsigned long t0 = micros();   // t0 = EMS onset
  triggerBiphasicEMS(emsA, emsB);
  lastEmsTriggerMs = millis();

  bool detected = false;
  unsigned long latUs = 0;
  unsigned long t0ms = millis();
  while (millis() - t0ms < RESP_WINDOW_MS) {
    int v = readPinFast(recvPin);
    if (v > thr) { latUs = micros() - t0; detected = true; break; }
  }

  Serial.print(F("EMSLAT_RESULT,")); Serial.print(id); Serial.print(','); Serial.print(side); Serial.print(',');
  if (detected) Serial.println(latUs);
  else          Serial.println(-1);
}

// THR,<side>,<value>
void runThrCmd(const String &cmd) {
  String tok[3];
  int n = splitCsv(cmd, tok, 3);
  if (n < 3) { Serial.println(F("ERR:THR:ARGS")); return; }
  char side = tok[1].length() ? tok[1][0] : 'R';
  int value = tok[2].toInt();
  if (side == 'L') thresholdLeft = value; else thresholdRight = value;
  Serial.print(F("OK:THR:")); Serial.print(side); Serial.print(':'); Serial.println(value);
}

// EMSCFG,<width>,<count>,<burst>,<interval>
void runEmsCfgCmd(const String &cmd) {
  String tok[5];
  int n = splitCsv(cmd, tok, 5);
  if (n < 5) { Serial.println(F("ERR:EMSCFG:ARGS")); return; }
  pulseWidth    = tok[1].toInt();
  pulseCount    = tok[2].toInt();
  burstCount    = tok[3].toInt();
  pulseInterval = tok[4].toInt();
  Serial.print(F("OK:EMSCFG:")); Serial.print(pulseWidth); Serial.print(',');
  Serial.print(pulseCount); Serial.print(','); Serial.print(burstCount); Serial.print(',');
  Serial.println(pulseInterval);
}

// ---------------- Info ----------------
void printStatus() {
  Serial.println(F("STATUS:"));
  Serial.print(F("  EMS W=")); Serial.print(pulseWidth);
  Serial.print(F(" C=")); Serial.print(pulseCount);
  Serial.print(F(" B=")); Serial.print(burstCount);
  Serial.print(F(" I=")); Serial.println(pulseInterval);
  Serial.print(F("  Total burst duration_us = "));
  Serial.println((long)pulseWidth * 4 * burstCount);
  Serial.print(F("  THR R=")); Serial.print(thresholdRight);
  Serial.print(F(" L=")); Serial.println(thresholdLeft);
  Serial.print(F("  RESP_WINDOW_MS=")); Serial.print(RESP_WINDOW_MS);
  Serial.print(F(" SETTLE_US=")); Serial.println(SETTLE_US);
  Serial.print(F("  Mode=")); Serial.println((int)currentMode);
}

void printHelp() {
  Serial.println(F("=== Commands (line-based, \\n terminated) ==="));
  Serial.println(F("TRIAL,<id>,<led>,<resp>,<emsSide>,<emsDelayUs>"));
  Serial.println(F("EMSLAT,<id>,<side>"));
  Serial.println(F("THR,<side>,<value>   EMSCFG,<w>,<c>,<b>,<i>"));
  Serial.println(F("EMS:R / EMS:L   LED:R / LED:G / LED:BOTH / LED:OFF"));
  Serial.println(F("TOUCH:LIVE / TOUCH:STOP   BASELINE   DET:R / DET:L / DET:STOP"));
  Serial.println(F("TRIAL:R / TRIAL:L (legacy)   STATUS / HELP / RESET"));
}

// ---------------- Legacy RT trial (bench) ----------------
void runRtTrial(int ledPin, int recvPin, const char *label) {
  Serial.print(F(">>> TRIAL: ")); Serial.println(label);
  delay(1000 + (millis() % 1500));
  unsigned long ledOnMs = millis();
  digitalWrite(ledPin, HIGH);
  bool detected = false; unsigned long rtMs = 0; long peak = 0;
  unsigned long deadline = ledOnMs + RT_TIMEOUT_MS;
  while (millis() < deadline) {
    int v = readPin(recvPin);
    if (v > TOUCH_THRESHOLD) { rtMs = millis() - ledOnMs; peak = v; detected = true; break; }
  }
  digitalWrite(ledPin, LOW);
  if (detected) { Serial.print(F("RT=")); Serial.print(rtMs); Serial.print(F("ms peak=")); Serial.println(peak); }
  else          { Serial.println(F("TIMEOUT")); }
}

// ---------------- Test starters (legacy bench) ----------------
void startBaseline() {
  Serial.println(F(">>> BASELINE 10s: hands OFF <<<"));
  currentMode = MODE_BASELINE; statsReset(); baselineStartMs = millis();
}
void startDetectionTest(bool right) {
  Serial.print(F(">>> DETECTION TEST: ")); Serial.println(right ? F("RIGHT") : F("LEFT"));
  currentMode = right ? MODE_DETECT_RIGHT : MODE_DETECT_LEFT;
  detectionCount = 0; lastDetectionMs = 0; testStartMs = millis(); inTouchEvent = false; currentPeak = 0;
}
void stopDetectionTest() {
  if (currentMode != MODE_DETECT_RIGHT && currentMode != MODE_DETECT_LEFT) return;
  unsigned long totalMs = millis() - testStartMs;
  Serial.println(F(">>> TEST FINISHED <<<"));
  Serial.print(F("Hand: ")); Serial.println(currentMode == MODE_DETECT_RIGHT ? F("RIGHT") : F("LEFT"));
  Serial.print(F("Detections: ")); Serial.println(detectionCount);
  Serial.print(F("Duration_ms: ")); Serial.println(totalMs);
  currentMode = MODE_IDLE; digitalWrite(PIN_LED_FB, LOW);
}

// ---------------- Mode handlers (legacy bench) ----------------
void handleBaselineMode() {
  int vR = readPin(PIN_RECV_RIGHT);
  int vL = readPin(PIN_RECV_LEFT);
  Serial.print(F("R=")); Serial.print(vR); Serial.print(F("\tL=")); Serial.println(vL);
  statsUpdate(vR); statsUpdate(vL);
  if (millis() - baselineStartMs >= 10000) {
    Serial.println(F("--- BASELINE RESULTS (pooled R+L) ---"));
    Serial.print(F("n=")); Serial.print(bN);
    Serial.print(F(" mean=")); Serial.print(bMean);
    Serial.print(F(" sd=")); Serial.print(statsStdev());
    Serial.print(F(" min=")); Serial.print(bMin);
    Serial.print(F(" max=")); Serial.println(bMax);
    Serial.print(F("Suggested threshold = ")); Serial.println(bMean + 5 * statsStdev());
    currentMode = MODE_IDLE;
  }
}
void handleLiveMode() {
  int vR = readPin(PIN_RECV_RIGHT);
  int vL = readPin(PIN_RECV_LEFT);
  Serial.print(F("R=")); Serial.print(vR); Serial.print(F("\tL=")); Serial.println(vL);
  digitalWrite(PIN_LED_FB, (vR > TOUCH_THRESHOLD || vL > TOUCH_THRESHOLD) ? HIGH : LOW);
}
void handleDetectionMode(bool right) {
  int v = readPin(right ? PIN_RECV_RIGHT : PIN_RECV_LEFT);
  unsigned long now = millis();
  bool inCooldown = (lastDetectionMs != 0) && (now - lastDetectionMs < TOUCH_COOLDOWN_MS);
  if (!inCooldown) {
    if (v > TOUCH_THRESHOLD) {
      if (!inTouchEvent) {
        inTouchEvent = true; currentPeak = v; detectionCount++; lastDetectionMs = now;
        digitalWrite(PIN_LED_FB, HIGH);
        Serial.print(F("[#")); Serial.print(detectionCount);
        Serial.print(F("] t=")); Serial.print(now - testStartMs);
        Serial.print(F("ms peak=")); Serial.println(v);
      } else if (v > currentPeak) { currentPeak = v; }
    } else {
      if (inTouchEvent) { inTouchEvent = false; Serial.print(F("    (released, final_peak=")); Serial.print(currentPeak); Serial.println(F(")")); }
      digitalWrite(PIN_LED_FB, LOW);
    }
  } else {
    if (v <= TOUCH_THRESHOLD) { inTouchEvent = false; digitalWrite(PIN_LED_FB, LOW); }
  }
}

// ---------------- Command parser ----------------
void handleCommand(const String &cmd) {
  // FastestBaseline protocol (time-critical experiment path) — check first.
  if (cmd.startsWith("TRIAL,"))  { runTrialCmd(cmd);  return; }
  if (cmd.startsWith("EMSLAT,")) { runEmsLatCmd(cmd); return; }
  if (cmd.startsWith("THR,"))    { runThrCmd(cmd);    return; }
  if (cmd.startsWith("EMSCFG,")) { runEmsCfgCmd(cmd); return; }

  // Manual EMS (bench / intensity tuning)
  if (cmd == "EMS:R") { tryFireEms(PIN_EMS_RIGHT_A, PIN_EMS_RIGHT_B, "R"); return; }
  if (cmd == "EMS:L") { tryFireEms(PIN_EMS_LEFT_A,  PIN_EMS_LEFT_B,  "L"); return; }

  // LED
  if (cmd == "LED:R")    { allLedsOff(); digitalWrite(PIN_LED_RED, HIGH);   Serial.println(F("OK:LED:R")); return; }
  if (cmd == "LED:G")    { allLedsOff(); digitalWrite(PIN_LED_GREEN, HIGH); Serial.println(F("OK:LED:G")); return; }
  if (cmd == "LED:BOTH") { digitalWrite(PIN_LED_RED, HIGH); digitalWrite(PIN_LED_GREEN, HIGH); Serial.println(F("OK:LED:BOTH")); return; }
  if (cmd == "LED:OFF")  { allLedsOff(); Serial.println(F("OK:LED:OFF")); return; }

  // TOUCH monitor (legacy)
  if (cmd == "TOUCH:LIVE") { currentMode = MODE_LIVE; Serial.println(F("OK:TOUCH:LIVE")); return; }
  if (cmd == "TOUCH:STOP") {
    if (currentMode == MODE_LIVE) { currentMode = MODE_IDLE; digitalWrite(PIN_LED_FB, LOW); }
    Serial.println(F("OK:TOUCH:STOP")); return;
  }

  // Legacy bench tools
  if (cmd == "BASELINE") { startBaseline(); return; }
  if (cmd == "DET:R")    { startDetectionTest(true);  return; }
  if (cmd == "DET:L")    { startDetectionTest(false); return; }
  if (cmd == "DET:STOP") { stopDetectionTest();       return; }
  if (cmd == "TRIAL:R")  { runRtTrial(PIN_LED_RED,   PIN_RECV_RIGHT, "Red->Right"); return; }
  if (cmd == "TRIAL:L")  { runRtTrial(PIN_LED_GREEN, PIN_RECV_LEFT,  "YG->Left");   return; }

  // Misc
  if (cmd == "STATUS") { printStatus(); return; }
  if (cmd == "HELP")   { printHelp();   return; }
  if (cmd == "RESET") {
    currentMode = MODE_IDLE; allLedsOff(); stopEMS();
    detectionCount = 0; inTouchEvent = false;
    Serial.println(F("OK:RESET"));
    return;
  }

  if (cmd.length() > 0) { Serial.print(F("ERR:UNKNOWN:")); Serial.println(cmd); }
}

// ---------------- Setup / Loop ----------------
void setup() {
  pinMode(PIN_EMS_LEFT_A,  OUTPUT);
  pinMode(PIN_EMS_LEFT_B,  OUTPUT);
  pinMode(PIN_EMS_RIGHT_A, OUTPUT);
  pinMode(PIN_EMS_RIGHT_B, OUTPUT);
  pinMode(PIN_SEND,        OUTPUT);
  pinMode(PIN_RECV_RIGHT,  INPUT);
  pinMode(PIN_RECV_LEFT,   INPUT);
  pinMode(PIN_LED_RED,     OUTPUT);
  pinMode(PIN_LED_GREEN,   OUTPUT);
  pinMode(PIN_LED_FB,      OUTPUT);

  stopEMS();
  allLedsOff();

  Serial.begin(115200);
  Serial.setTimeout(50);
  while (!Serial) { ; }
  Serial.println(F("=== Integrated EMS + LED + Touch (FastestBaseline protocol) ==="));
  printHelp();
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    handleCommand(cmd);
  }
  switch (currentMode) {
    case MODE_LIVE:         handleLiveMode();           break;
    case MODE_BASELINE:     handleBaselineMode();       break;
    case MODE_DETECT_RIGHT: handleDetectionMode(true);  break;
    case MODE_DETECT_LEFT:  handleDetectionMode(false); break;
    case MODE_IDLE:
    default: break;
  }
}
