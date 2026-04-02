// Arduino Code: Biphasic EMS with Interval Control & Safety Cool-down
// Hardware: Arduino DUE + L298N (H-Bridge Mode)
// For Reaction Test Experiment

// 撓屈用ピン (Left channel)
const int PIN_LEFT_A = 3; // IN1
const int PIN_LEFT_B = 4; // IN2

// 尺屈用ピン (Right channel)
const int PIN_RIGHT_A = 5; // IN3
const int PIN_RIGHT_B = 6; // IN4

// デフォルトパラメータ
int pulseWidth = 50;       // パルス幅 (us)  [20 - 1000]
int pulseCount = 1;        // 繰り返し回数   [1 - 100]
int burstCount = 3;        // 1回の繰り返し内の2相性サイクル数 [1 - 20]  Default: 3
int pulseInterval = 40000; // 周期ごとの待機時間 (us) [0 - 100000]  Default: 40ms

// 安全装置: 連打防止用クールダウン
unsigned long lastTriggerTime = 0;          // 最後に発火した時刻 (ms)
const unsigned int MIN_TRIGGER_INTERVAL = 500; // 最低インターバル (ms)。これより早い連打は無視。

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(50); // readStringUntil のタイムアウトを短縮 (デフォルト1000ms)
  
  // ピン設定
  pinMode(PIN_LEFT_A, OUTPUT);
  pinMode(PIN_LEFT_B, OUTPUT);
  pinMode(PIN_RIGHT_A, OUTPUT);
  pinMode(PIN_RIGHT_B, OUTPUT);
  
  stopEMS();
  
  Serial.println("EMS Controller Ready");
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    // コマンド解析
    unsigned long currentTime = millis();

    // L/Rコマンドはクールダウン付き（安全装置）
    if (command == "L") {
      if (currentTime - lastTriggerTime > MIN_TRIGGER_INTERVAL) {
        triggerBiphasicEMS(PIN_LEFT_A, PIN_LEFT_B);
        lastTriggerTime = millis();
        Serial.println("OK:L");
      } else {
        Serial.println("COOLDOWN:L");
      }
    } 
    else if (command == "R") {
      if (currentTime - lastTriggerTime > MIN_TRIGGER_INTERVAL) {
        triggerBiphasicEMS(PIN_RIGHT_A, PIN_RIGHT_B);
        lastTriggerTime = millis();
        Serial.println("OK:R");
      } else {
        Serial.println("COOLDOWN:R");
      }
    }
    else if (command.startsWith("W")) { // Width
      pulseWidth = constrain(command.substring(1).toInt(), 20, 1000);
      Serial.print("OK:W=");
      Serial.println(pulseWidth);
    }
    else if (command.startsWith("C")) { // Count
      pulseCount = constrain(command.substring(1).toInt(), 1, 100);
      Serial.print("OK:C=");
      Serial.println(pulseCount);
    }
    else if (command.startsWith("B")) { // Burst (cycles per repetition)
      burstCount = constrain(command.substring(1).toInt(), 1, 20);
      Serial.print("OK:B=");
      Serial.println(burstCount);
    }
    else if (command.startsWith("I")) { // Interval
      pulseInterval = constrain(command.substring(1).toInt(), 0, 100000);
      Serial.print("OK:I=");
      Serial.println(pulseInterval);
    }
    else if (command == "?") { // Status query
      Serial.print("STATUS:W=");
      Serial.print(pulseWidth);
      Serial.print(",C=");
      Serial.print(pulseCount);
      Serial.print(",B=");
      Serial.print(burstCount);
      Serial.print(",I=");
      Serial.println(pulseInterval);
    }
  }
}

void stopEMS() {
  digitalWrite(PIN_LEFT_A, LOW);
  digitalWrite(PIN_LEFT_B, LOW);
  digitalWrite(PIN_RIGHT_A, LOW);
  digitalWrite(PIN_RIGHT_B, LOW);
}

// delayMicroseconds() は約16383µs までしか正確に動作しないため、
// 長い待機には delay() と delayMicroseconds() を併用する
void safeDelayMicroseconds(unsigned long us) {
  if (us >= 1000) {
    delay(us / 1000);              // ミリ秒部分
    delayMicroseconds(us % 1000);  // 残りのマイクロ秒部分
  } else {
    delayMicroseconds(us);
  }
}

/**
 * 2相性パルス刺激を発火
 * 
 * 波形パターン (1サイクル = 4 * pulseWidth):
 *   +V |  ████
 *    0 |      ████
 *   -V |          ████
 *    0 |              ████
 * 
 * burstCount: 連続するサイクル数
 * pulseCount: バーストの繰り返し回数
 * pulseInterval: バースト間の休止時間
 */
void triggerBiphasicEMS(int pinA, int pinB) {
  for (int i = 0; i < pulseCount; i++) {
    // --- burstCount回の2相性サイクルを連続実行 ---
    for (int j = 0; j < burstCount; j++) {
      // --- 1周期 (4 * pulseWidth) ---
      
      // 1. 正相 (+)
      digitalWrite(pinA, HIGH);
      digitalWrite(pinB, LOW);
      safeDelayMicroseconds(pulseWidth);

      // 2. 休止 (0)
      digitalWrite(pinA, LOW);
      digitalWrite(pinB, LOW);
      safeDelayMicroseconds(pulseWidth);

      // 3. 逆相 (-)
      digitalWrite(pinA, LOW);
      digitalWrite(pinB, HIGH);
      safeDelayMicroseconds(pulseWidth); 

      // 4. 休止 (0)
      digitalWrite(pinA, LOW);
      digitalWrite(pinB, LOW);
      safeDelayMicroseconds(pulseWidth);
    }
    
    // --- インターバル (pulseInterval) ---
    // 最後の1回以外は待機を入れる
    if (i < pulseCount - 1) {
      safeDelayMicroseconds(pulseInterval);
    }
  }
  
  stopEMS(); // 安全のため確実に停止
}
