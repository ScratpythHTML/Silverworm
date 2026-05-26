# PlatformIO Setup for Silverworm Web Serial Control Panel

This guide explains how to set up and use this project with PlatformIO in VS Code.

## Project Structure

```
Web_Test_Version/
├── src/
│   └── main.cpp                 # Main firmware code
├── platformio.ini               # PlatformIO configuration
├── README.md                    # Usage guide
└── PLATFORMIO_SETUP.md         # This file
```

## Installation & Setup

### Step 1: Install PlatformIO in VS Code

1. Open VS Code
2. Go to Extensions (Ctrl+Shift+X)
3. Search for "PlatformIO IDE"
4. Click Install (by PlatformIO)
5. Wait for installation to complete and VS Code to reload

### Step 2: Open the Project

1. Open VS Code
2. File → Open Folder
3. Navigate to: `IO Panel/Silverworm_Control_Panel/IO Panel Software/Web_Test_Version/`
4. Click Select Folder

### Step 3: PlatformIO Will Auto-Configure

- PlatformIO reads `platformio.ini` automatically
- ArduinoJson library will auto-download
- This may take a few moments on first load

## Building & Uploading

### Build the Project

- Click the **✓ (Checkmark)** icon in the bottom toolbar, OR
- Use keyboard shortcut: `Ctrl+Alt+B`

### Upload to ESP32

1. Connect ESP32-H2 via USB cable
2. Click the **→ (Arrow)** icon in the bottom toolbar, OR
3. Use keyboard shortcut: `Ctrl+Alt+U`

### Serial Monitor

1. Click the **🔌 (Plug)** icon in the bottom toolbar, OR
2. Use keyboard shortcut: `Ctrl+Alt+S`
3. Baud rate should be **115200** (pre-configured)

## Troubleshooting

### "Board not found" or upload fails

1. Check USB cable connection
2. Verify ESP32 port is detected:
   - Windows: Device Manager → Ports (COM and LPT)
   - Linux/Mac: `ls /dev/tty*`
3. In VS Code, look for the port name
4. In `platformio.ini`, uncomment and set the correct port:
   ```ini
   monitor_port = COM3  ; Change to your port
   ```

### ArduinoJson not found

This means libraries aren't downloaded yet. Try:

1. Delete `.pio/` folder in the project
2. Click Build (Ctrl+Alt+B) to re-download dependencies
3. Wait for completion

### Upload hangs or fails

Try:

1. Press ESP32's **BOOT** button and hold while uploading
2. Or: Use Arduino IDE to verify the board works, then return to PlatformIO

### "Unknown board: esp32-h2-devkitm-1"

Update PlatformIO platform:

1. Open PlatformIO terminal (View → Terminal)
2. Run: `pio platform update espressif32`
3. Try building again

## PlatformIO Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Build | `Ctrl+Alt+B` |
| Upload | `Ctrl+Alt+U` |
| Serial Monitor | `Ctrl+Alt+S` |
| Build & Upload | `Ctrl+Alt+V` |
| Clean Build | `Ctrl+Alt+C` |
| PlatformIO Home | `Ctrl+Alt+H` |

## Using the Project

After successful upload:

1. Open Serial Monitor (Ctrl+Alt+S)
2. Wait for startup message: `"Waiting for serial connection..."`
3. Open the web interface HTML file in Chrome or Edge
4. Click "Connect to ESP32" button
5. Select the USB serial port when prompted
6. Control panel should become active!

## Modifying Code

- All firmware code is in `src/main.cpp`
- HTML/CSS/JavaScript is embedded in that file as a raw string
- After any changes, Build (Ctrl+Alt+B) and Upload (Ctrl+Alt+U)

## Extracting the HTML Interface

To create a standalone `index.html` file for quick access:

**From command line (Linux/Mac/Windows Git Bash):**
```bash
sed -n '/R"rawliteral(/,/)rawliteral"/p' src/main.cpp | head -n -1 | tail -n +2 > index.html
```

**Manual method:**
1. Open `src/main.cpp`
2. Find `const char INDEX_HTML[] PROGMEM = R"rawliteral(`
3. Copy everything until `);`
4. Remove the first and last lines
5. Save to `index.html`
6. Open in Chrome/Edge

## PlatformIO vs Arduino IDE

| Feature | PlatformIO | Arduino IDE |
|---------|-----------|-----------|
| Dependency Management | ✅ Automatic | ❌ Manual |
| Multiple Boards | ✅ Excellent | ❌ Limited |
| Editor | VS Code | Basic |
| Build System | Scons | Make |
| Serial Monitor | ✅ Built-in | ✅ Built-in |

## Still Having Issues?

Try these diagnostic steps:

1. **In PlatformIO terminal:**
   ```bash
   pio device list          # See connected devices
   pio run -t monitor       # Start serial monitor
   pio run -t clean         # Clean build
   ```

2. **Check board detection:**
   - Plug/unplug USB while terminal is open
   - You should see COM port appear/disappear

3. **Verify environment:**
   - Open PlatformIO Home (Ctrl+Alt+H)
   - Check "Platforms" section for "Espressif 32"

## Web Serial API Browser Support

For the web interface to work, you need a browser that supports Web Serial API:

- ✅ Chrome/Chromium (all platforms)
- ✅ Edge (all platforms)
- ✅ Opera (all platforms)
- ❌ Safari (not supported)
- ❌ Firefox (not supported - under development)

## For More Help

- PlatformIO Docs: https://docs.platformio.org
- ESP32-H2 Board: https://docs.platformio.org/en/latest/boards/espressif32/esp32-h2-devkitm-1.html
- VS Code Help: https://code.visualstudio.com/docs
- Web Serial API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Serial_API
