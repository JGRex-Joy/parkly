#include <Servo.h>

const int servoPin = 8;

Servo Servo1;

void setup()
{
  Servo1.attach(servoPin);

  Servo1.write(0);
  delay(2000);

  Servo1.write(90);
  delay(2000);

  Servo1.write(0);
}

void loop()
{
  
}