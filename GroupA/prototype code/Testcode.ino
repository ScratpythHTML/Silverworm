// Code to ensure motor runs and that hall effect sensor is working

// Define pins

#define INA 2 // drives motor clcokwise when high, pin 2 Brown wire
#define INB 4 // drives motor counter - clockwise when high, pin 4 orange wire 
#define PWM 3 // output the pwm to pin 3 Yellow wire
#define HALL 5 // Hall effect sensor input pin 5


volatile long pulseCount = 0; // number of pulses counted

// Interrupt function for Hall sensor
void hallISR() {
  pulseCount++;
}

void setup() {
  pinMode(INA, OUTPUT);
  pinMode(INB, OUTPUT);
  pinMode(PWM, OUTPUT);
  pinMode(HALL, INPUT_PULLUP);


  // Attach interrupt for Hall sensor (falling edge)
  attachInterrupt(digitalPinToInterrupt(HALL), hallISR, FALLING);

  Serial.begin(9600);
}

void loop() {
  // Example: run motor forward at half speed
  digitalWrite(INA, HIGH);
  digitalWrite(INB, LOW);
  analogWrite(PWM, 60); // 0-255 PWM

  // Print rotation count every second
  Serial.print("Pulses: ");
  Serial.println(pulseCount);
  delay(1000);
}


