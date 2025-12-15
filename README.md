🩺 Smart Health Monitor

Portable IoT-based vital signs monitoring system using the Seeed XIAO ESP32-C3. It measures Heart Rate, SpO₂, Temperature, and detects falls in real time. Features include on-device alerts, OLED UI, Wi-Fi connectivity, and a Flask dashboard for remote monitoring.
⚡ Features
Real-time HR & SpO₂ monitoring (MAX30102)
Fall detection using MPU-6050
(Optional) Non-contact temperature measurement (MLX90614)
OLED display for live vitals
Buzzer-based emergency alerts
Wi-Fi–enabled data upload (HTTP/MQTT)
Flask dashboard for graphs, logs & remote monitoring
Local CSV logging for offline analysis

🧠 System Architecture
On-device processing includes:
Band-pass filtering & peak detection for HR
Ratio-of-ratios method for SpO₂
Acceleration + orientation threshold logic for falls
Rule-based decision system with hysteresis for alert stabilit

🔧 Hardware Used
Seeed Studio XIAO ESP32-C3
MAX30102 Pulse Oximeter
MPU-6050 Accelerometer + Gyroscope
MLX90614 (optional)
SSD1306 OLED (128×64)
Buzzer
Li-ion battery pack

🛠️ Software Stack
Firmware: C/C++ (Arduino IDE)
Sensor drivers
Signal processing & validation
Event detection
Wi-Fi handling
OLED UI
CSV logging
Backend: Flask + SQLite
REST API for uploads
Real-time vitals display
Historical graphs (Chart.js)
Alert logs
