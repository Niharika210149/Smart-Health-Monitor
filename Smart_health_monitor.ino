// ============================================================================
//  MERGED CODE
//  (1) MPU6050 Fall Detection  + 
//  (2) FreeRTOS MAX30102 HR Task +
//  (3) WiFi + REST API UPLOAD on BUTTON PRESS +
//  (4) OLED Display
//  Works on Seeed XIAO ESP32-C3
// ============================================================================

#include <Wire.h>
#include <math.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DFRobot_MAX30102.h>
#include <WiFi.h>
#include <HTTPClient.h>

// ---------------------------------------------------------------------------
// USER CONFIGURATION
// ---------------------------------------------------------------------------
const char* WIFI_SSID   = "Niharika";
const char* WIFI_PASS   = "niharika";

const char* SERVER_BASE = "http://10.62.88.6:5000";
const char* ENDPOINT    = "/api/sensor-data";
const char* API_KEY     = "";

const char* DEVICE_ID   = "xiao-esp32c3-001";
const char* USER_ID     = "P0001";

const uint8_t BUTTON_PIN = 3;  // one leg → pin, other → GND

// Timing
const unsigned long WIFI_RETRY_MS = 10000UL;
const unsigned long BUTTON_DEBOUNCE_MS = 200UL;

// ---------------------------------------------------------------------------
// OLED
// ---------------------------------------------------------------------------
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
bool displayFound = false;

// ---------------------------------------------------------------------------
// MAX30102 SENSOR
// ---------------------------------------------------------------------------
DFRobot_MAX30102 particleSensor;

// Shared HR state updated by FreeRTOS HR task
volatile int32_t hr_value = 0;
volatile int32_t spo2_value = 0;
volatile bool hr_valid = false;
volatile bool spo2_valid = false;

// Mutex for I2C access
SemaphoreHandle_t i2cMutex = NULL;

// Protect shared state
portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;

// ---------------------------------------------------------------------------
// MPU6050 FALL DETECTION
// ---------------------------------------------------------------------------
#define PWR_MGMT_1   0x6B
#define ACCEL_XOUT_H 0x3B

uint8_t mpuAddr = 0;

float IMPACT_THRESHOLD = 1.6f;
float DELTA_THRESHOLD  = 0.6f;

const int buzzerPin = D6;
bool beeping = false;
unsigned long beepStart = 0;
unsigned long lastBeepTime = 0;
const unsigned long BEEP_MS = 3000;
const unsigned long BEEP_COOLDOWN = 2000;

float ema_total = 1.0f;
float prev_total = 1.0f;
const float EMA_ALPHA = 0.30f;

volatile bool fallActive = false;
volatile bool pauseHRTask = false;

// ---------------------------------------------------------------------------
// BUTTON HANDLING
// ---------------------------------------------------------------------------
volatile bool buttonFlag = false;
unsigned long lastButtonAction = 0;

void IRAM_ATTR buttonISR() {
  buttonFlag = true;
}

// ---------------------------------------------------------------------------
// WIFI CONNECT FUNCTION
// ---------------------------------------------------------------------------
unsigned long lastWiFiTry = 0;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("Connecting to WiFi '%s'...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000UL) {
    delay(200);
    Serial.print(".");
  }
  Serial.println("");

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi connected: " + WiFi.localIP().toString());
  } else {
    Serial.println("WiFi connect failed.");
  }
}

// ---------------------------------------------------------------------------
// REST API POST Telemetry
// ---------------------------------------------------------------------------
bool sendTelemetry(int32_t hr, bool hrValid, int32_t spo2, bool spo2Valid) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("No WiFi → Upload skipped.");
      return false;
    }
  }

  HTTPClient http;
  String url = String(SERVER_BASE) + ENDPOINT;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (strlen(API_KEY) > 0) http.addHeader("X-API-KEY", API_KEY);

  String payload = "{";
  payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"user_id\":\"" + String(USER_ID) + "\",";
  payload += "\"heart_rate\":";
  payload += hrValid ? String(hr) : "null";
  payload += ",";
  payload += "\"spo2\":";
  payload += spo2Valid ? String(spo2) : "null";
  payload += ",";
  payload += "\"heart_rate_valid\":" + String(hrValid ? "true" : "false") + ",";
  payload += "\"spo2_valid\":" + String(spo2Valid ? "true" : "false");
  payload += "}";

  Serial.println("POST → " + url);
  Serial.println(payload);

  int code = http.POST(payload);

  if (code > 0) {
    Serial.printf("Response Code: %d\n", code);
    Serial.println(http.getString());
  } else {
    Serial.printf("POST FAILED: %s\n", http.errorToString(code).c_str());
  }

  http.end();
  return code > 0 && code < 300;
}

// ---------------------------------------------------------------------------
// MPU6050 HELPERS
// ---------------------------------------------------------------------------
bool detectMPU() {
  uint8_t cands[2] = {0x68, 0x69};
  for (uint8_t addr: cands) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      mpuAddr = addr;
      return true;
    }
  }
  return false;
}

void writeMPU(uint8_t reg, uint8_t data) {
  if (xSemaphoreTake(i2cMutex, 200 / portTICK_PERIOD_MS)) {
    Wire.beginTransmission(mpuAddr);
    Wire.write(reg);
    Wire.write(data);
    Wire.endTransmission(true);
    xSemaphoreGive(i2cMutex);
  }
}

bool readAccel(float &ax, float &ay, float &az) {
  if (!xSemaphoreTake(i2cMutex, 200 / portTICK_PERIOD_MS)) return false;

  Wire.beginTransmission(mpuAddr);
  Wire.write(ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) {
    xSemaphoreGive(i2cMutex);
    return false;
  }

  if (Wire.requestFrom(mpuAddr, (uint8_t)6, true) != 6) {
    xSemaphoreGive(i2cMutex);
    return false;
  }

  int16_t rawAx = (Wire.read() << 8) | Wire.read();
  int16_t rawAy = (Wire.read() << 8) | Wire.read();
  int16_t rawAz = (Wire.read() << 8) | Wire.read();

  xSemaphoreGive(i2cMutex);

  ax = rawAx / 16384.0;
  ay = rawAy / 16384.0;
  az = rawAz / 16384.0;
  return true;
}

// ---------------------------------------------------------------------------
// OLED Helper
// ---------------------------------------------------------------------------
void showOLEDMessage(const char* l1, const char* l2, unsigned long hold) {
  if (!displayFound) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(0, 0);
  display.println(l1);
  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println(l2);
  display.display();
  if (hold > 0) delay(hold);
}

// ---------------------------------------------------------------------------
// HR BACKGROUND TASK
// ---------------------------------------------------------------------------
void hrTask(void *pv) {
  Serial.println("HR TASK STARTED");
  unsigned long lastMeasure = 0;

  for (;;) {
    if (pauseHRTask) {
      vTaskDelay(100 / portTICK_PERIOD_MS);
      continue;
    }

    unsigned long now = millis();
    if (now - lastMeasure < 6000) {
      vTaskDelay(200 / portTICK_PERIOD_MS);
      continue;
    }

    if (!xSemaphoreTake(i2cMutex, 200 / portTICK_PERIOD_MS)) {
      vTaskDelay(300 / portTICK_PERIOD_MS);
      continue;
    }

    int32_t SPO2, HR;
    int8_t SPO2v, HRv;
    particleSensor.heartrateAndOxygenSaturation(&SPO2, &SPO2v, &HR, &HRv);

    xSemaphoreGive(i2cMutex);

    portENTER_CRITICAL(&stateMux);
    if (HRv) {
      hr_value = HR;
      hr_valid = true;
    }
    if (SPO2v) {
      spo2_value = SPO2;
      spo2_valid = true;
    }
    portEXIT_CRITICAL(&stateMux);

    lastMeasure = millis();
    vTaskDelay(200 / portTICK_PERIOD_MS);
  }
}

// ---------------------------------------------------------------------------
// SETUP
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);

  // Button
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), buttonISR, FALLING);

  // Buzzer
  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, HIGH);

  // I2C Mutex
  i2cMutex = xSemaphoreCreateMutex();

  Wire.begin();

  // OLED
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    displayFound = true;
    showOLEDMessage("OLED Ready", "", 800);
  }

  // MPU
  if (detectMPU()) {
    writeMPU(PWR_MGMT_1, 0x00);
    showOLEDMessage("MPU6050 OK", "", 600);
  }

  // MAX30102
  if (xSemaphoreTake(i2cMutex, 1000 / portTICK_PERIOD_MS)) {
    if (particleSensor.begin()) {
      particleSensor.sensorConfiguration(50, SAMPLEAVG_4, MODE_MULTILED, SAMPLERATE_100, PULSEWIDTH_411, ADCRANGE_16384);
      showOLEDMessage("MAX30102 OK", "", 600);
    }
    xSemaphoreGive(i2cMutex);
  }

  // Start HR Task
  xTaskCreate(hrTask, "HR Task", 4096, NULL, 1, NULL);

  // WiFi
  connectWiFi();
}

// ---------------------------------------------------------------------------
// MAIN LOOP
// ---------------------------------------------------------------------------
void loop() {
  // --------------------------- MPU READ ------------------------
  float ax, ay, az;
  if (mpuAddr && readAccel(ax, ay, az)) {
    float total = sqrt(ax*ax + ay*ay + az*az);
    float delta = fabs(total - prev_total);
    prev_total = total;
    ema_total = EMA_ALPHA * total + (1 - EMA_ALPHA) * ema_total;

    bool impact = false;
    unsigned long now = millis();

    if ((ema_total > IMPACT_THRESHOLD) || (delta > DELTA_THRESHOLD)) {
      if (!beeping && (now - lastBeepTime > BEEP_COOLDOWN))
        impact = true;
    }

    if (impact && !beeping) {
      fallActive = true;
      pauseHRTask = true;

      beeping = true;
      beepStart = now;
      digitalWrite(buzzerPin, LOW);

      showOLEDMessage("FALL DETECTED", "Beeping...", 0);
    }

    if (beeping) {
      if (now - beepStart >= BEEP_MS) {
        digitalWrite(buzzerPin, HIGH);
        beeping = false;
        lastBeepTime = now;

        fallActive = false;
        pauseHRTask = false;
        showOLEDMessage("Standby", "", 500);
      }
    }

    // ---------------- OLED Normal Mode ------------------------
    if (!fallActive && !beeping && displayFound) {
      int32_t h, s;
      bool hv, sv;

      portENTER_CRITICAL(&stateMux);
      h = hr_value;
      s = spo2_value;
      hv = hr_valid;
      sv = spo2_valid;
      portEXIT_CRITICAL(&stateMux);

      display.clearDisplay();
      display.setTextColor(SSD1306_WHITE);
      display.setTextSize(2);
      display.setCursor(0, 0);
      display.print("HR: ");
      if (hv) display.print(h); else display.print("--");

      display.setTextSize(1);
      display.setCursor(0, 40);
      display.print("SpO2: ");
      if (sv) display.print(s); else display.print("--");
      display.display();
    }
  }

  // ---------------- BUTTON UPLOAD ------------------------
  if (buttonFlag) {
    unsigned long now = millis();
    if (now - lastButtonAction > BUTTON_DEBOUNCE_MS) {
      lastButtonAction = now;

      int32_t h, s;
      bool hv, sv;
      portENTER_CRITICAL(&stateMux);
      h = hr_value;
      s = spo2_value;
      hv = hr_valid;
      sv = spo2_valid;
      portEXIT_CRITICAL(&stateMux);

      Serial.println("Button pressed → Uploading data...");
      bool ok = sendTelemetry(h, hv, s, sv);

      if (ok && displayFound) {
        showOLEDMessage("UPLOAD SENT", "", 700);
      }
    }
    buttonFlag = false;
  }

  // ---------------- WIFI AUTO-RECONNECT ------------------------
  if (WiFi.status() != WL_CONNECTED && millis() - lastWiFiTry >= WIFI_RETRY_MS) {
    lastWiFiTry = millis();
    connectWiFi();
  }

  delay(50);
}
