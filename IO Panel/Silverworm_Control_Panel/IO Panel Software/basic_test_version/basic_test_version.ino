#include <Wire.h>

const uint8_t I2C_SLAVE_ADDR = 0x55;
const uint8_t I2C_SDA = 8;
const uint8_t I2C_SCL = 22;
const uint32_t I2C_FREQ = 100000;

const size_t BUFFER_SIZE = 32;

char serialInputBuffer[BUFFER_SIZE] = {0};
size_t serialInputLength = 0;

char pendingTxBuffer[BUFFER_SIZE] = {0};
size_t pendingTxLength = 0;
bool pendingTxReady = false;

char pendingRxBuffer[BUFFER_SIZE] = {0};
size_t pendingRxLength = 0;
bool pendingRxReady = false;

void queueLineForI2C(const char *line);
void handleSerialInput();
void printPendingI2CReceive();
void onI2CReceive(int len);
void onI2CRequest();

void setup() {
	Serial.begin(115200);
	delay(500);

	Wire.onReceive(onI2CReceive);
	Wire.onRequest(onI2CRequest);
  Wire.begin(I2C_SLAVE_ADDR, I2C_SDA, I2C_SCL, I2C_FREQ);

	Serial.println("ESP32-H2 basic I2C serial bridge ready");
	Serial.println("Slave address: 0x55");
	Serial.println("SDA: GPIO8, SCL: GPIO22, I2C: 100000 Hz");
	Serial.println("Type a line in the serial monitor to queue it for the next I2C read");
	Serial.println("Any I2C write from the Raspberry Pi will be printed here");
}

void loop() {
	handleSerialInput();
	printPendingI2CReceive();
	delay(5);
}

void handleSerialInput() {
	while (Serial.available()) {
		char incoming = static_cast<char>(Serial.read());

		if (incoming == '\r') {
			continue;
		}

		if (incoming == '\n') {
			if (serialInputLength > 0) {
				serialInputBuffer[serialInputLength] = '\0';
				queueLineForI2C(serialInputBuffer);
				Serial.print("SERIAL->I2C: ");
				Serial.println(serialInputBuffer);
				serialInputLength = 0;
				memset(serialInputBuffer, 0, sizeof(serialInputBuffer));
			}
			continue;
		}

		if (serialInputLength < BUFFER_SIZE - 1) {
			serialInputBuffer[serialInputLength++] = incoming;
		}
	}
}

void queueLineForI2C(const char *line) {
	size_t length = strnlen(line, BUFFER_SIZE - 1);
	memset(pendingTxBuffer, 0, sizeof(pendingTxBuffer));
	memcpy(pendingTxBuffer, line, length);
	pendingTxLength = length;
	pendingTxReady = true;
}

void printPendingI2CReceive() {
	if (!pendingRxReady) {
		return;
	}

	Serial.print("I2C->SERIAL: ");
	Serial.println(pendingRxBuffer);
	pendingRxReady = false;
	pendingRxLength = 0;
	memset(pendingRxBuffer, 0, sizeof(pendingRxBuffer));
}

void onI2CReceive(int len) {
	size_t index = 0;

	while (Wire.available() && index < BUFFER_SIZE - 1) {
		pendingRxBuffer[index++] = static_cast<char>(Wire.read());
	}

	while (Wire.available()) {
		(void)Wire.read();
	}

	pendingRxBuffer[index] = '\0';
	pendingRxLength = index;

	if (pendingRxLength > 0) {
		pendingRxReady = true;
	}
}

void onI2CRequest() {
	if (!pendingTxReady || pendingTxLength == 0) {
		Wire.write(static_cast<uint8_t>(0));
		return;
	}

	uint8_t payloadLength = static_cast<uint8_t>(pendingTxLength);
	Wire.write(payloadLength);
	Wire.write(reinterpret_cast<const uint8_t *>(pendingTxBuffer), payloadLength);

	pendingTxReady = false;
	pendingTxLength = 0;
	memset(pendingTxBuffer, 0, sizeof(pendingTxBuffer));
}
