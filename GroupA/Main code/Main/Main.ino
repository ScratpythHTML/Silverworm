// Code for using PID control to reach a given target speed, using hall effect sensor feedback


#include <Arduino.h>
#include <SPI.h>
#include "Interrupts.h"
#include <QuickPID.h>
#include "motor.h"
#include <avr/interrupt.h>


#define INA 4 // drives motor clcokwise when high, pin 2
#define INB 2 // drives motor counter - clockwise when high, pin 4
#define PWM 3 // output the pwm to pin 3
#define HALL 5 // Hall effect sensor input pin 5

constexpr unsigned long SPEED_REPORT_INTERVAL_MS = 100;

// === SPI slave configuration (Nano Every / ATmega4809) ===
// Raspberry Pi SPI modes:
// - Mode 0: CPOL=0, CPHA=0
// - Mode 1: CPOL=0, CPHA=1
// - Mode 2: CPOL=1, CPHA=0
// - Mode 3: CPOL=1, CPHA=1
//
// Change this if the Pi reads garbage / shifted bytes.
constexpr uint8_t SPI_DATA_MODE = 0; // 0..3

#if defined(PIN_SPI_SS)
constexpr uint8_t SPI_SS_PIN = PIN_SPI_SS; // Nano Every core typically maps this to D8
#else
constexpr uint8_t SPI_SS_PIN = 8; // Nano Every default SS pin (D8)
#endif

volatile byte receivedBuffer[3];
volatile byte completedCommand[3];
volatile byte bufferIndex = 0;
volatile byte expectedCommandLength = 0;
volatile bool newCommand = false;
volatile byte replyBuffer[3];
volatile byte replyLength = 0;
volatile byte replyIndex = 0;

unsigned long lastSpeedReportMs = 0;



// True when ISR is mid-command or still shifting a reply (do not overwrite reply).
bool spiIdle() {
    return bufferIndex == 0 && replyLength == 0 && replyIndex == 0;
}

// Queue an outbound reply. Returns false if a transfer is already in progress.
// Note: On ATmega4809 we do NOT write the SPI data register here; the ISR does that.
bool setReply(byte a, byte b = 0, byte c = 0, byte length = 1) {
    bool ok = false;
    noInterrupts();
    if (spiIdle()) {
        replyBuffer[0] = a;
        replyBuffer[1] = b;
        replyBuffer[2] = c;
        replyLength = length;
        replyIndex = 0;
        ok = true;
    }
    interrupts();
    return ok;
}

static inline uint8_t spiModeToCtrlb(uint8_t mode) {
    switch (mode & 0x03) {
        case 0: return SPI_MODE_0_gc;
        case 1: return SPI_MODE_1_gc;
        case 2: return SPI_MODE_2_gc;
        default: return SPI_MODE_3_gc;
    }
}

// Interrupt for SPI transfers while the Nano Every acts as slave (ATmega4809 SPI0).
ISR(SPI0_INT_vect) {
    byte c = SPI0.DATA;

    if (bufferIndex < sizeof(receivedBuffer)) {
        receivedBuffer[bufferIndex++] = c;
    }

    if (bufferIndex == 1) {
        if (c == '1' || c == '3') expectedCommandLength = 3;
        else if (c == '2' || c == '4') expectedCommandLength = 2;
        else expectedCommandLength = 1;
    }

    if (expectedCommandLength > 0 && bufferIndex >= expectedCommandLength) {
        for (byte i = 0; i < 3; i++) {
            completedCommand[i] = (i < expectedCommandLength) ? receivedBuffer[i] : 0;
        }
        bufferIndex = 0;
        expectedCommandLength = 0;
        newCommand = true;
    }

    if (replyIndex < replyLength) {
        SPI0.DATA = replyBuffer[replyIndex++];
    } else {
        SPI0.DATA = 0;
        replyLength = 0;
        replyIndex = 0;
    }

    // Clear interrupt flag (required on megaAVR 0-series)
    SPI0.INTFLAGS = SPI_IF_bm;
}


Motor motor(INA, INB, PWM); // pins: INA, INB, PWM
float omega_ref = 0; // original reference speed rad/s

// Speed variables
float currentSpeed = 0.0;     // will receive instantaneous omega
float targetPWM =  30;        // will receive PID output and is the PWM aiming for

// QuickPID controller
// Arguments: &Input, &Output, &Setpoint, Kp, Ki, Kd
QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  30.0, 2, 0, speedPID.Action::direct);


void setup() {
    // Hall sensor input must be held stable; otherwise it can float and generate fake edges.
    pinMode(HALL, INPUT_PULLUP);

    // Interrupt for Hall sensor
    attachInterrupt(digitalPinToInterrupt(HALL), hallISR, FALLING); // add interrupt for hall sensor

    // Set up for PID
    // Hall sensor does not measure direction; keep output forward-only.
    speedPID.SetOutputLimits(-255, 255);      // PID output limits match PWM range
    speedPID.SetSampleTimeUs(50000);        // 50 ms sample time
    speedPID.SetMode(speedPID.Control::automatic);            // enable PID

    // SPI slave for Nano Every (ATmega4809).
    // The SPI library on megaavr targets master mode; we configure SPI0 directly for slave mode.
    pinMode(MISO, OUTPUT);
    pinMode(MOSI, INPUT);
    pinMode(SCK, INPUT);
    pinMode(SPI_SS_PIN, INPUT_PULLUP);

    // Route SPI0 pins to match Nano Every pinout (MOSI=11, MISO=12, SCK=13, SS=8).
    // (Matches ArduinoCore-megaavr SPI pin mux.)
    PORTMUX.TWISPIROUTEA = PORTMUX_SPI0_ALT2_gc;

    // Slave mode, enable module, enable interrupt.
    SPI0.CTRLA = SPI_ENABLE_bm;           // slave by default when MASTER bit is 0
    SPI0.CTRLA &= ~SPI_MASTER_bm;         // ensure slave/client mode
    SPI0.CTRLB = spiModeToCtrlb(SPI_DATA_MODE);
    SPI0.INTCTRL = SPI_IE_bm;             // enable SPI interrupt
    SPI0.INTFLAGS = SPI_IF_bm;            // clear any pending flag
    sei();                                // global interrupts

    // Default outgoing byte before first clock
    SPI0.DATA = 0;
    Serial.begin(9600);
}

void loop() {
  byte command[3] = {0, 0, 0};

  if (newCommand) {
    noInterrupts();
    for (byte i = 0; i < 3; i++) {
      command[i] = completedCommand[i];
    }
    newCommand = false;
    interrupts();

    byte prefix = command[0];

    switch (prefix) {

        case '1': {  // START
            int speed = command[1] | (command[2] << 8);
            omega_ref = speed;
            setReply('3', '1', 0, 2);
            break;
        }

        case '2': {  // STOP
            motor.setSpeed(0);
            omega_ref = 0;
            setReply('3', '2', 0, 2);
            break;
        }

        case '3': {  // SET SPEED
            int speed = command[1] | (command[2] << 8);
            omega_ref = speed;
            break;
        }

        case '4': {  

            break;
        }

        default:
            setReply('2', '1', 0, 2);
            break;
    }
  }


  // read latest instantaneous omega safely
  noInterrupts();
  currentSpeed = omega;
  interrupts();

  // run PID to set new pwm value
  speedPID.Compute();

  // clamp to valid PWM range
  targetPWM = constrain(targetPWM, -255, 255);

  // apply to motor
  motor.setSpeed((int)targetPWM);

  // Unsolicited speed report (only when SPI is idle so we do not stomp command acks).
  unsigned long now = millis();
  if (now - lastSpeedReportMs >= SPEED_REPORT_INTERVAL_MS) {
    lastSpeedReportMs = now;
    noInterrupts();
    bool idle = spiIdle();
    interrupts();
    if (idle) {
      int speed = (int)currentSpeed;
      setReply('1', speed & 0xFF, (speed >> 8) & 0xFF, 3);
    }
  }

  //output time current speed and target speed
  Serial.print(currentSpeed);
  Serial.print(",");
//   Serial.println(omega_ref);
//   Serial.print(",");
  Serial.println(targetPWM);
  
}
