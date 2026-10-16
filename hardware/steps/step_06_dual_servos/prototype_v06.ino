prototype_v04#include <Servo.h>

const int servoPin1 = 9;
const int servoPin2 = 10;

Servo Servo1;
Servo Servo2;

void setup()
{
  Servo1.attach(servoPin1);
  Servo2.attach(servoPin2);

  Servo1.write(0);
  Servo2.write(0);

  delay(2000);
  
  Servo1.write(90);
  Servo2.write(90);

  delay(2000);

  Servo1.write(0);
  Servo2.write(0);
}

void loop()
{
  
}