#include <Servo.h>

const int trgPin1 = 6;
const int echoPin1 = 5;
const int servoPin1 = 4;

const int trgPin2 = 8;
const int echoPin2 = 7;
const int servoPin2 = 9;

long duration;
int distance;

Servo Servo1;
Servo Servo2;

int getDistance(int trgPin, int echoPin)
{
  digitalWrite(trgPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trgPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trgPin, LOW);

  duration = pulseIn(echoPin, HIGH, 30000);

  if (duration == 0)
  {
    return -1;
  }

  distance = duration * 0.0343 / 2;

  return distance;
}

void setup()
{
  pinMode(trgPin1, OUTPUT);
  pinMode(echoPin1, INPUT);

  pinMode(trgPin2, OUTPUT);
  pinMode(echoPin2, INPUT);

  Servo1.attach(servoPin1);
  Servo2.attach(servoPin2);

  Servo1.write(0);
  Servo2.write(0);
}

void loop()
{
  int distance1 = getDistance(trgPin1, echoPin1);

  if (distance1 > 0 && distance1 < 150)
  {
    Servo1.write(90);
  }
  else
  {
    Servo1.write(0);
  }

  delay(50);

  int distance2 = getDistance(trgPin2, echoPin2);

  if (distance2 > 0 && distance2 < 150)
  {
    Servo2.write(90);
  }
  else
  {
    Servo2.write(0);
  }

  delay(50);
}
