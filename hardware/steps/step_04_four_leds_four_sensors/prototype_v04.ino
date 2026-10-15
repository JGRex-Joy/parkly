const int trgPin1 = 2;
const int echoPin1 = 3;
const int ledPin1 = 4;

const int trgPin2 = 5;
const int echoPin2 = 6;
const int ledPin2 = 7;

const int trgPin3 = 8;
const int echoPin3 = 9;
const int ledPin3 = 10;

const int trgPin4 = 11;
const int echoPin4 = 12;
const int ledPin4 = 13;

long duration;
int distance;

void checkParkingSlot(int trgPin, int echoPin, int ledPin)
{
  digitalWrite(trgPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trgPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trgPin, LOW);

  duration = pulseIn(echoPin, HIGH, 30000);
  distance = duration * 0.0343 / 2;

  if (distance > 0 && distance < 150)
  {
    digitalWrite(ledPin, HIGH);  
  }
  else
  {
    digitalWrite(ledPin, LOW);   
  }
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
}

void loop()
{
  checkParkingSlot(trgPin1, echoPin1, ledPin1);
  delay(50);

  checkParkingSlot(trgPin2, echoPin2, ledPin2);
  delay(50);

  checkParkingSlot(trgPin3, echoPin3, ledPin3);
  delay(50);

  checkParkingSlot(trgPin4, echoPin4, ledPin4);
  delay(50);
}
