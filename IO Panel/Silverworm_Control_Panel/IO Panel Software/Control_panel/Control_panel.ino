#include <Wire.h>

// Pin Definitions
// RGB LED 1
const int LED1_R = 0;
const int LED1_G = 1;
const int LED1_B = 2;

// RGB LED 2
const int LED2_R = 9;
const int LED2_G = 27;
const int LED2_B = 26;

// Buttons and Switches
const int BTN1 = 5;
const int BTN1_LED = 14;
const int TOGGLE = 3;

// Encoders
const int DIAL1A = 24;
const int DIAL1B = 23;
const int DIAL1_BTN = 10;

const int DIAL2A = 11;
const int DIAL2B = 25;
const int DIAL2_BTN = 12;

// I2C Configuration
const uint8_t I2C_SLAVE_ADDR = 0x55;
const int I2C_SDA = 8;
const int I2C_SCL = 22;

// Debounce constants
const unsigned long DEBOUNCE_MS = 20;
const unsigned long RAINBOW_TIMEOUT_MS = 300; // Return to normal colour after 300ms of inactivity

// State variables
unsigned long lastBtnPress = 0;
bool lastBtnState = HIGH;

unsigned long lastToggleRead = 0;
bool lastToggleState = HIGH;

int encoderMode[2] = {0, 0}; // 0=large/green, 1=medium/yellow, 2=small/red
unsigned long lastEncoderBtnPress[2] = {0, 0};
bool lastEncoderBtnState[2] = {HIGH, HIGH};

unsigned long lastEncoderRotation[2] = {0, 0}; // Track last rotation time for rainbow effect
int rainbowIndex[2] = {0, 0}; // Current position in rainbow cycle

volatile int lastEncoderA[2] = {HIGH, HIGH};
volatile int lastEncoderB[2] = {HIGH, HIGH};

bool powerLEDStatus = false;

// I2C command queue
char commandBuffer[32] = "";
int commandBufferIndex = 0;

// Colour definitions (RGB values 0-255)
const uint8_t colourBig[3] = {0, 255, 0};       // Large detent
const uint8_t colourMedium[3] = {255, 200, 0};  // Medium detent
const uint8_t colourSmall[3] = {255, 0, 0};     // Small detent
const uint8_t colourOff[3] = {0, 0, 0};

// Rainbow colours for encoder rotation animation (24 colours = 1 per dial step for smooth animation)
const uint8_t rainbowColours[24][3] = {
  {255, 0, 0},      // Red
  {255, 32, 0},     // Red-Orange
  {255, 64, 0},     // Orange
  {255, 96, 0},     // Orange
  {255, 128, 0},    // Orange-Yellow
  {255, 160, 0},    // Yellow-Orange
  {255, 192, 0},    // Yellow
  {255, 224, 0},    // Yellow
  {224, 255, 0},    // Yellow-Green
  {160, 255, 0},    // Green-Yellow
  {96, 255, 0},     // Green
  {32, 255, 0},     // Green
  {0, 255, 32},     // Green-Cyan
  {0, 255, 96},     // Cyan-Green
  {0, 255, 160},    // Cyan
  {0, 255, 224},    // Cyan
  {0, 192, 255},    // Cyan-Blue
  {0, 128, 255},    // Blue-Cyan
  {0, 64, 255},     // Blue
  {0, 32, 255},     // Blue
  {64, 0, 255},     // Blue-Purple
  {128, 0, 255},    // Purple
  {192, 0, 255},    // Purple-Red
  {255, 0, 192}     // Red-Purple
};
const int RAINBOW_COLOURS_COUNT = 24;

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Initialize pins
  pinMode(BTN1, INPUT_PULLUP);
  pinMode(BTN1_LED, OUTPUT);
  digitalWrite(BTN1_LED, LOW);

  pinMode(TOGGLE, INPUT_PULLUP);

  pinMode(DIAL1A, INPUT);
  pinMode(DIAL1B, INPUT);
  pinMode(DIAL1_BTN, INPUT_PULLUP);

  pinMode(DIAL2A, INPUT);
  pinMode(DIAL2B, INPUT);
  pinMode(DIAL2_BTN, INPUT_PULLUP);

  // RGB LEDs
  pinMode(LED1_R, OUTPUT);
  pinMode(LED1_G, OUTPUT);
  pinMode(LED1_B, OUTPUT);

  pinMode(LED2_R, OUTPUT);
  pinMode(LED2_G, OUTPUT);
  pinMode(LED2_B, OUTPUT);

  // Set initial LED colours
  setRGBLED(1, colourBig);
  setRGBLED(2, colourBig);

  // Initialize I2C slave
  Wire.begin((uint8_t)I2C_SLAVE_ADDR, I2C_SDA, I2C_SCL, 400000);
  Wire.onReceive(onI2CReceive);
  Wire.onRequest(onI2CRequest);

  Serial.println("ESP32-H2 IO Panel initialized");
}

void loop() {
  unsigned long now = millis();

  handlePowerButton();
  handleToggleSwitch();
  handleEncoder(0, DIAL1A, DIAL1B, DIAL1_BTN);
  handleEncoder(1, DIAL2A, DIAL2B, DIAL2_BTN);

  // Check if encoders should return to normal colour mode
  for (int i = 0; i < 2; i++) {
    if ((now - lastEncoderRotation[i]) > RAINBOW_TIMEOUT_MS) {
      updateEncoderLED(i); // Return to normal colour
    }
  }

  delay(5);
}

// Handle power button press
void handlePowerButton() {
  bool currentState = digitalRead(BTN1);
  unsigned long now = millis();

  if (currentState == LOW && lastBtnState == HIGH) {
    if (now - lastBtnPress > DEBOUNCE_MS) {
      sendI2CCommand("TP");
      lastBtnPress = now;
    }
  }

  lastBtnState = currentState;
}

// Handle toggle switch
void handleToggleSwitch() {
  bool currentState = digitalRead(TOGGLE);
  unsigned long now = millis();

  if (currentState != lastToggleState) {
    if (now - lastToggleRead > DEBOUNCE_MS) {
      if (currentState == LOW) {
        sendI2CCommand("AS0"); // Manual mode
      } else {
        sendI2CCommand("AS1"); // Automatic mode
      }
      lastToggleState = currentState;
      lastToggleRead = now;
    }
  }
}

// Handle encoder rotation and button
void handleEncoder(int encoderIdx, int pinA, int pinB, int pinBtn) {
  // Handle encoder button press
  bool btnState = digitalRead(pinBtn);
  unsigned long now = millis();

  if (btnState == LOW && lastEncoderBtnState[encoderIdx] == HIGH) {
    if (now - lastEncoderBtnPress[encoderIdx] > DEBOUNCE_MS) {
      // Cycle through modes
      encoderMode[encoderIdx] = (encoderMode[encoderIdx] + 1) % 3;
      updateEncoderLED(encoderIdx);
      lastEncoderBtnPress[encoderIdx] = now;
    }
  }

  lastEncoderBtnState[encoderIdx] = btnState;

  // Handle encoder rotation using quadrature decoding for Bourns PEC11R
  int currentA = digitalRead(pinA);
  int currentB = digitalRead(pinB);
  int lastA = lastEncoderA[encoderIdx];
  int lastB = lastEncoderB[encoderIdx];

  // Full quadrature state change detection
  if (currentA != lastA || currentB != lastB) {
    // Quadrature lookup table: determine if clockwise (1) or counter-clockwise (-1)
    // States: 00, 01, 10, 11 (4 possible states)
    // Clockwise sequence: 11->10->00->01->11
    // Counter-clockwise: 11->01->00->10->11

    int oldState = (lastA << 1) | lastB;      // Previous state
    int newState = (currentA << 1) | currentB; // Current state

    // Simple quadrature table approach
    // Only trigger on certain transitions to avoid jitter
    if (oldState == 3 && newState == 2) {  // 11->10: clockwise step 1
      sendEncoderCommand(encoderIdx, 1);
    } else if (oldState == 2 && newState == 0) {  // 10->00: clockwise step 2
      sendEncoderCommand(encoderIdx, 1);
    } else if (oldState == 0 && newState == 1) {  // 00->01: clockwise step 3
      sendEncoderCommand(encoderIdx, 1);
    } else if (oldState == 1 && newState == 3) {  // 01->11: clockwise step 4
      sendEncoderCommand(encoderIdx, 1);
    }
    // Counter-clockwise transitions
    else if (oldState == 3 && newState == 1) {  // 11->01: counter-clockwise step 1
      sendEncoderCommand(encoderIdx, -1);
    } else if (oldState == 1 && newState == 0) {  // 01->00: counter-clockwise step 2
      sendEncoderCommand(encoderIdx, -1);
    } else if (oldState == 0 && newState == 2) {  // 00->10: counter-clockwise step 3
      sendEncoderCommand(encoderIdx, -1);
    } else if (oldState == 2 && newState == 3) {  // 10->11: counter-clockwise step 4
      sendEncoderCommand(encoderIdx, -1);
    }

    lastEncoderA[encoderIdx] = currentA;
    lastEncoderB[encoderIdx] = currentB;
  }
}

// Send encoder command with proper increment and rainbow animation
void sendEncoderCommand(int encoderIdx, int direction) {
  int increment = getIncrementForMode(encoderMode[encoderIdx]);
  char cmd[16];

  if (direction > 0) {
    sprintf(cmd, "D%d+%d", encoderIdx + 1, increment);
  } else {
    sprintf(cmd, "D%d-%d", encoderIdx + 1, increment);
  }

  sendI2CCommand(cmd);

  // Update rainbow animation
  lastEncoderRotation[encoderIdx] = millis();
  rainbowIndex[encoderIdx] = (rainbowIndex[encoderIdx] + 1) % RAINBOW_COLOURS_COUNT;
  setRGBLED(encoderIdx + 1, rainbowColours[rainbowIndex[encoderIdx]]);
}

// Get increment value based on encoder mode
int getIncrementForMode(int mode) {
  switch(mode) {
    case 0: return 3;  // Large detent
    case 1: return 2;  // Medium detent
    case 2: return 1;  // Small detent
    default: return 1;
  }
}

// Update encoder RGB LED colour based on mode
void updateEncoderLED(int encoderIdx) {
  const uint8_t *colour;
  switch(encoderMode[encoderIdx]) {
    case 0:
      colour = colourBig;
      break;
    case 1:
      colour = colourMedium;
      break;
    case 2:
      colour = colourSmall;
      break;
    default:
      colour = colourOff;
  }
  setRGBLED(encoderIdx + 1, colour);
}

// Set RGB LED color
void setRGBLED(int ledIdx, const uint8_t color[3]) {
  if (ledIdx == 1) {
    analogWrite(LED1_R, color[0]);
    analogWrite(LED1_G, color[1]);
    analogWrite(LED1_B, color[2]);
  } else if (ledIdx == 2) {
    analogWrite(LED2_R, color[0]);
    analogWrite(LED2_G, color[1]);
    analogWrite(LED2_B, color[2]);
  }
}

// I2C receive handler - receive status from Raspberry Pi
void onI2CReceive(int len) {
  if (len >= 2) {
    char buffer[len + 1];
    int i = 0;
    while (Wire.available()) {
      buffer[i++] = Wire.read();
    }
    buffer[i] = '\0';

    // Parse ON/OFF status
    if (strncmp(buffer, "ON", 2) == 0) {
      digitalWrite(BTN1_LED, HIGH);
      powerLEDStatus = true;
    } else if (strncmp(buffer, "OFF", 3) == 0) {
      digitalWrite(BTN1_LED, LOW);
      powerLEDStatus = false;
    }
  }
}

// I2C request handler - send command to Raspberry Pi
void onI2CRequest() {
  if (commandBufferIndex > 0) {
    Wire.write((uint8_t *)commandBuffer, commandBufferIndex);
    commandBufferIndex = 0;
    memset(commandBuffer, 0, sizeof(commandBuffer));
  } else {
    Wire.write(0); // Send null byte if no command
  }
}

// Queue I2C command to be sent to Raspberry Pi when requested
void sendI2CCommand(const char *cmd) {
  memset(commandBuffer, 0, sizeof(commandBuffer));
  strncpy(commandBuffer, cmd, sizeof(commandBuffer) - 2);
  commandBufferIndex = strlen(commandBuffer) + 1; // Include null terminator

  Serial.print("Queued I2C command: ");
  Serial.println(cmd);
}
