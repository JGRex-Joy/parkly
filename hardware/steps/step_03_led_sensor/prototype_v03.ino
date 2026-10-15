const int ledPin = 7;
const int echoPin = 8;
const int trgPin = 9;

long duration;
int distance;

void setup()
{
  pinMode(trgPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(ledPin, OUTPUT);
}

void loop()
{
  digitalWrite(trgPin, LOW);
  delayMicroseconds(2);
  
  digitalWrite(trgPin, HIGH);
  delayMicroseconds(10);
  
  digitalWrite(trgPin, LOW);
  
  duration = pulseIn(echoPin, HIGH, 30000);
  distance = duration * 0.0343 / 2;

  if (distance > 0){
    if (distance < 150){
      digitalWrite(ledPin, HIGH);	
    }
    else {
      digitalWrite(ledPin, LOW);
    } 
  }
  
  
}
