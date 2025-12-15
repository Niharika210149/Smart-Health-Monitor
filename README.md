# 🩺 Smart Health Analyzer – Portable AI-Enabled Health Monitoring System 🤖❤️

## 🔍 Project Overview

Smart Health Analyzer is a **portable, IoT-enabled vital signs monitoring system** designed to measure **heart rate, SpO₂, temperature*, and detect falls** in real time.  
Powered by the **Seeed Studio XIAO ESP32-C3**, it integrates biomedical sensors with on-device signal processing, emergency alerts, and Wi-Fi-based remote monitoring.

\*Temperature optional based on sensor setup.

---

## 🧠 Core Functionalities

### ❤️ Real-Time Vital Monitoring
- Measures **Heart Rate** and **SpO₂** using MAX30102.
- Optional **non-contact temperature sensing** using MLX90614.
- Signal filtering reduces noise and motion artifacts for stable readings.

### 🛡️ Fall & Motion Detection
- Uses **MPU6050 accelerometer + gyroscope** to detect:
  - Falls
  - Sudden impacts
  - Abnormal inactivity
- Threshold- and orientation-based logic for reliable alerts.

### 📟 On-Device Alerts & Display
- **OLED display** shows live vitals.
- **Buzzer alerts** for abnormal HR/SpO₂ levels or fall detection.
- Fully functional even without internet.

### 🛰️ IoT Connectivity & Dashboard
- Built-in **Wi-Fi** uploads data to a Flask dashboard.
- Dashboard features:
  - Real-time charts for HR, SpO₂, motion
  - Timestamped alert logs
  - Basic user interface for remote monitoring

### 📊 Data Logging
- Logs data in **CSV format** for long-term tracking or ML training.
- Useful for anomaly detection, predictive analysis, and research.

---

## ⚙️ Hardware Components

| Component                 | Purpose                                      |
|---------------------------|----------------------------------------------|
| Seeed XIAO ESP32-C3       | Main MCU, Wi-Fi communication                |
| MAX30102                  | Heart rate & SpO₂ measurement                |
| MPU-6050                  | Fall detection, motion tracking              |
| MLX90614 (optional)       | Temperature measurement                      |
| SSD1306 OLED (128×64)     | Real-time vitals display                     |
| Buzzer                    | Alerts for abnormal conditions               |
| Li-ion Battery Pack       | Portable power supply                        |
| I2C Bus (SDA/SCL)         | Sensor communication                         |
| Breadboard, wires         | Prototype assembly                           |

---

## 📁 Project Structure

