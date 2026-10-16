#include <Servo.h>

const int trgPin1 = 3;
const int echoPin1 = 2;
const int ledPin1 = 4;

const int trgPin2 = 6;
const int echoPin2 = 5;
const int ledPin2 = 7;

const int trgPin3 = 10;
const int echoPin3 = 9;
const int ledPin3 = 8;

const int trgPin4 = 13;
const int echoPin4 = 12;
const int ledPin4 = 11;

const int trgPinG1 = A4;
const int echoPinG1 = A3;
const int servoPin1 = A5;

const int trgPinG2 = A1;
const int echoPinG2 = A0;
const int servoPin2 = A2;

Servo servo1;
Servo servo2;

const int detectionLimit = 150;
const int gateOpenAngle = 90;
const int gateClosedAngle = 0;

int getDistance(int trgPin, int echoPin)
{
  digitalWrite(trgPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trgPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trgPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 30000);

  if (duration == 0)
  {
    return -1;
  }

  return duration * 0.0343 / 2;
}

bool checkParkingSlot(int trgPin, int echoPin, int ledPin)
{
  int distance = getDistance(trgPin, echoPin);

  bool occupied =
    distance > 0 && distance < detectionLimit;

  digitalWrite(ledPin, occupied ? HIGH : LOW);

  return occupied;
}

bool isObjectDetected(int trgPin, int echoPin)
{
  int distance = getDistance(trgPin, echoPin);

  return distance > 0 && distance < detectionLimit;
}

void setup()
{
  pinMode(trgPin1, OUTPUT);
  pinMode(echoPin1, INPUT);
  pinMode(ledPin1, OUTPUT);

  pinMode(trgPin2, OUTPUT);
  pinMode(echoPin2, INPUT);
  pinMode(ledPin2, OUTPUT);

  pinMode(trgPin3, OUTPUT);
  pinMode(echoPin3, INPUT);
  pinMode(ledPin3, OUTPUT);

  pinMode(trgPin4, OUTPUT);
  pinMode(echoPin4, INPUT);
  pinMode(ledPin4, OUTPUT);

  pinMode(trgPinG1, OUTPUT);
  pinMode(echoPinG1, INPUT);

  pinMode(trgPinG2, OUTPUT);
  pinMode(echoPinG2, INPUT);

  servo1.attach(servoPin1);
  servo2.attach(servoPin2);

  servo1.write(gateClosedAngle);
  servo2.write(gateClosedAngle);
}

void loop()
{
  int occupiedSlots = 0;

  if (checkParkingSlot(trgPin1, echoPin1, ledPin1))
    occupiedSlots++;

  delay(50);

  if (checkParkingSlot(trgPin2, echoPin2, ledPin2))
    occupiedSlots++;

  delay(50);

  if (checkParkingSlot(trgPin3, echoPin3, ledPin3))
    occupiedSlots++;

  delay(50);

  if (checkParkingSlot(trgPin4, echoPin4, ledPin4))
    occupiedSlots++;

  delay(50);

  bool parkingAvailable = occupiedSlots < 4;

  bool entranceDetected =
    isObjectDetected(trgPinG1, echoPinG1);

  if (parkingAvailable && entranceDetected)
  {
    servo1.write(gateOpenAngle);
  }
  else
  {
    servo1.write(gateClosedAngle);
  }

  delay(50);

  bool exitDetected =
    isObjectDetected(trgPinG2, echoPinG2);

  if (exitDetected)
  {
    servo2.write(gateOpenAngle);
  }
  else
  {
    servo2.write(gateClosedAngle);
  }

  delay(50);
}
