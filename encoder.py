import RPi.GPIO as GPIO

class Encoder:

    def __init__(self, leftPin, rightPin, swPin, rotaryCallback=None, swCallback=None):
        self.leftPin = leftPin
        self.rightPin = rightPin
        self.swPin = swPin
        self.value = 0
        self.state = '00'
        self.direction = None
        self.rotaryCallback = rotaryCallback
        self.swCallback = swCallback
        
        GPIO.setup(self.leftPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.rightPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.swPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        GPIO.add_event_detect(self.leftPin, GPIO.BOTH, callback=self.transitionOccurred)
        GPIO.add_event_detect(self.rightPin, GPIO.BOTH, callback=self.transitionOccurred)
        GPIO.add_event_detect(self.swPin, GPIO.FALLING, callback=self.swClicked, bouncetime=300)

    def transitionOccurred(self, channel):
        p1 = GPIO.input(self.leftPin)
        p2 = GPIO.input(self.rightPin)
        newState = "{}{}".format(p1, p2)

        if self.state == "00": # Resting position
            if newState == "01": # Turned right 1
                self.direction = "R"
            elif newState == "10": # Turned left 1
                self.direction = "L"

        elif self.state == "01": # R1 or L3 position
            if newState == "11": # Turned right 1
                self.direction = "R"
            elif newState == "00": # Turned left 1
                if self.direction == "L":
                    self.value = self.value - 1
                    if self.rotaryCallback is not None:
                        self.rotaryCallback(self.value)

        elif self.state == "10": # R3 or L1
            if newState == "11": # Turned left 1
                self.direction = "L"
            elif newState == "00": # Turned right 1
                if self.direction == "R":
                    self.value = self.value + 1
                    if self.rotaryCallback is not None:
                        self.rotaryCallback(self.value)

        else: # self.state == "11"
            if newState == "01": # Turned left 1
                self.direction = "L"
            elif newState == "10": # Turned right 1
                self.direction = "R"
            elif newState == "00": # Skipped an intermediate 01 or 10 state, but if we know direction then a turn is complete
                if self.direction == "L":
                    self.value = self.value - 1
                    if self.rotaryCallback is not None:
                        self.rotaryCallback(self.value)
                elif self.direction == "R":
                    self.value = self.value + 1
                    if self.rotaryCallback is not None:
                        self.rotaryCallback(self.value)
                
        self.state = newState

    def getValue(self):
        return self.value

    def swClicked(self, channel):
        if self.swCallback is not None:
            self.swCallback()