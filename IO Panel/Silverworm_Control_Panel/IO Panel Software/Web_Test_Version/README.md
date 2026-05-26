# Silverworm Control Panel - Web Serial Test Version

This is a web-based testing interface for the Silverworm ESP32-H2 control panel using **Web Serial API**. It allows you to test the control panel functionality via USB serial connection with a beautiful graphical interface running in your browser.

## Features

- **USB Serial Connection**: Connect ESP32-H2 to laptop via USB cable
- **Web Interface**: Graphical control panel running in Chrome/Edge browser
- **Web Serial API**: Browser communicates with ESP32 over USB serial
- **Round Dials**: Swipe up/down to control dials with ±1/±2/±3 increments
- **RGB LED Control**: Tap colored circles to cycle through detent modes (Large/Medium/Small)
- **Real I2C Communication**: All commands sent to Raspberry Pi via I2C
- **Power LED Status**: Receives ON/OFF status from Raspberry Pi and displays in real-time

## Setup Instructions

### 1. Install Required Libraries

**For Arduino IDE:**
- Sketch → Include Library → Manage Libraries
- Search "ArduinoJson" and install latest version

**For PlatformIO:**
- Libraries auto-download from platformio.ini

### 2. Load the Firmware

**Arduino IDE:**
1. Open `Control_panel_web_version.ino`
2. Select Board: **ESP32-H2** (Tools → Board → ESP32 → ESP32-H2)
3. Select Port: (your ESP32 COM port)
4. Upload (Ctrl+U)

**PlatformIO:**
1. Open the `Web_Test_Version` folder in VS Code
2. Click Build (Ctrl+Alt+B)
3. Connect ESP32 and click Upload (Ctrl+Alt+U)

### 3. Connect and Use

1. **Connect via USB**: Plug ESP32-H2 into your Windows/Mac/Linux laptop via USB cable
2. **Open Browser**: Open the `index.html` file in Chrome, Edge, or Opera browser
3. **Click Connect**: Press the "Connect to ESP32" button
4. **Select Port**: Browser will show available serial ports - select the ESP32
5. **Use Interface**: Control the panel with swipes and taps

## Usage

### Dials (Dial 1 & Dial 2)

- **Swipe Up**: Rotates dial clockwise, sends positive increment command
- **Swipe Down**: Rotates dial counter-clockwise, sends negative increment command
- **Tap LED Circle**: Cycles through detent modes:
  - 🟢 **Green (Large)**: Each swipe = ±3 increment
  - 🟡 **Yellow (Medium)**: Each swipe = ±2 increment
  - 🔴 **Red (Small)**: Each swipe = ±1 increment

### Toggle Switch

- **Manual**: Sends `AS0` command to Raspberry Pi
- **Auto**: Sends `AS1` command to Raspberry Pi

### Power Button

- **Tap**: Sends `TP` (toggle power) command to Raspberry Pi
- **LED Indicator**: Shows ON/OFF status received from Raspberry Pi

## I2C Communication

The web interface sends the same I2C commands as the physical hardware:

| Command | Format | Example | Function |
|---------|--------|---------|----------|
| Dial Change | `D[1-2][+/-][1-3]` | `D1+3`, `D2-1` | Dial control |
| Mode Switch | `AS[0-1]` | `AS0`, `AS1` | 0=Manual, 1=Automatic |
| Power Toggle | `TP` | `TP` | Toggle power ON/OFF |
| Power Status | `ON` or `OFF` | `ON` | Received from RPi |

## Serial Communication Protocol

**Browser → ESP32 (JSON over serial):**
```json
{"type": "dial_swipe", "dial": 1, "direction": "up"}
{"type": "led_tap", "dial": 1}
{"type": "button", "button": "power"}
{"type": "toggle", "mode": "auto"}
```

**ESP32 → Browser (JSON over serial):**
```json
{"type": "power_led_status", "state": "on"}
{"type": "power_led_status", "state": "off"}
```

## Browser Compatibility

- ✅ **Windows**: Chrome, Edge, Opera
- ✅ **Mac**: Chrome, Edge, Opera
- ✅ **Linux**: Chrome, Edge, Opera
- ❌ **Safari**: Does not support Web Serial API
- ❌ **Firefox**: Does not support Web Serial API (yet)

**Recommended: Chrome or Edge on Windows**

## Troubleshooting

### "Serial port not found"
- Ensure USB cable is connected
- Check Device Manager (Windows) or System Report (Mac) for COM port
- Restart the ESP32 (press EN button)

### "Connect button doesn't work"
- Verify you're using Chrome, Edge, or Opera
- Try a different USB cable
- Check that browser is running on localhost or HTTPS

### No response when clicking buttons
- Check serial monitor (115200 baud) for debug messages
- Verify I2C connection to Raspberry Pi
- Check that Raspberry Pi is configured as I2C master at address 0x55

### HTML file won't open
- Make sure you're using Web Serial API supported browser
- For offline use, save the HTML file locally and open it with `file://` protocol (most browsers support this)

## Serial Monitor Debugging

Open the serial monitor at **115200 baud** to see:
- Connection messages from ESP32
- I2C commands being sent to Raspberry Pi
- Status updates received from Raspberry Pi

Example output:
```
=== Silverworm Web Serial Control Panel ===
Waiting for serial connection...
Open the HTML interface in Chrome/Edge and click 'Connect to ESP32'
I2C Command: D1+3
I2C Command: TP
```

## File Structure

```
Web_Test_Version/
├── Control_panel_web_version.ino      # Arduino IDE version
├── src/main.cpp                       # PlatformIO version
├── platformio.ini                     # PlatformIO config
├── index.html                         # Web interface (save this locally)
├── README.md                          # This file
└── PLATFORMIO_SETUP.md               # PlatformIO setup guide
```

## Creating a Standalone HTML File

To use the interface offline, extract the HTML from the .ino or .cpp file and save as `index.html`:

1. Open `Control_panel_web_version.ino`
2. Copy everything between `R"rawliteral(` and `)rawliteral"`
3. Save to a file named `index.html`
4. Open in Chrome/Edge browser

Or use this command:
```bash
sed -n '/R"rawliteral(/,/)rawliteral"/p' Control_panel_web_version.ino | head -n -1 | tail -n +2 > index.html
```

## Performance

- Communication: Serial at 115200 baud
- Latency: ~10-50ms per command
- I2C commands are queued and sent when Raspberry Pi requests them

## Original Hardware Version

The original hardware-based version (with physical encoders and buttons) is at:
```
IO Panel/Silverworm_Control_Panel/IO Panel Software/Control_panel.ino
```

## License

Same as parent Silverworm project.

