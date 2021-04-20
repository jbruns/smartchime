import RPi.GPIO as GPIO
import alsaaudio
import subprocess

from datetime import datetime, timedelta
from luma.core.render import canvas

class Encoder:

    def __init__(self, leftPin, rightPin, swPin, rotaryFunction, swFunction, state_tracker, device):
        self.leftPin = leftPin
        self.rightPin = rightPin
        self.swPin = swPin
        self.rotaryFunction = rotaryFunction
        self.swFunction = swFunction
        self.value = 0
        self.state = '00'
        self.direction = None
        self.state_tracker = state_tracker
        self.device = device
        self.mixer = alsaaudio.Mixer()
        
        # determine initial value based on configured function.
        if rotaryFunction == "volume":
            # get the current master volume and mute status.
            self.value = int(self.mixer.getvolume()[0])

        elif rotaryFunction == "audioFile":
            # on startup, use the filename specified first in the config.
            self.value = 0
        
        print(f"[encoder][init] assigned function for rotary: {self.rotaryFunction}, switch: {self.swFunction}. Initial value: {self.value}")

        GPIO.setup(self.leftPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.rightPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.swPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.add_event_detect(self.leftPin, GPIO.BOTH, callback=self.transitionOccurred)
        GPIO.add_event_detect(self.rightPin, GPIO.BOTH, callback=self.transitionOccurred)
        GPIO.add_event_detect(self.swPin, GPIO.FALLING, callback=self.swClicked, bouncetime=300)

    # Triggered when the GPIO state changes for the rotary pins. This determines the new state and thus the new value for the rotary encoder.
    # Once we land on a new value, pass the assigned action for the encoder and the current value to the rotary action function.
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
                    self.rotaryAction(self.rotaryFunction,self.value)

        elif self.state == "10": # R3 or L1
            if newState == "11": # Turned left 1
                self.direction = "L"
            elif newState == "00": # Turned right 1
                if self.direction == "R":
                    self.value = self.value + 1
                    self.rotaryAction(self.rotaryFunction,self.value)

        else: # self.state == "11"
            if newState == "01": # Turned left 1
                self.direction = "L"
            elif newState == "10": # Turned right 1
                self.direction = "R"
            elif newState == "00": # Skipped an intermediate 01 or 10 state, but if we know direction then a turn is complete
                if self.direction == "L":
                    self.value = self.value - 1
                    self.rotaryAction(self.rotaryFunction,self.value)
                elif self.direction == "R":
                    self.value = self.value + 1
                    self.rotaryAction(self.rotaryFunction,self.value)
                
        self.state = newState

    # Triggered when the GPIO falling signal is detected, indicating that the switch was pushed. Pass the assigned action to the switch action function.
    def swClicked(self, channel):
        self.swAction(self.swFunction)
    
    def rotaryAction(self, rotaryFunction, value):
        self.rotaryFunction = rotaryFunction
        self.value = value
        self.oled_text = False

        print(f"[encoder][rotaryAction] triggered {self.rotaryFunction} action, value: {self.value}")
        # reset the number of cycles that the main thread will run through, before restoring the display.
        self.state_tracker.controlsLockCycles = 40

        if self.rotaryFunction == "volume":
            # check that the master volume is not muted.
            if self.mixer.getmute()[0] == 0:
                # check valid range and cap the value if invalid.
                if self.value < 0:
                    self.value = 0
                elif self.value > 100:
                    self.value = 100

                # set the new volume.
                self.mixer.setvolume(self.value)
                self.oled_text = "Volume: " + str(self.value)
            
            else: # muted.
                self.oled_text = "MUTE ON"
        
        if self.rotaryFunction == "audioFile":
            # keep the value within valid range (number of files defined in config).
            print(f"{len(self.state_tracker.doorbell_audioFiles)} audio files available")
            if self.value < 0:
                self.value = 0
            if self.value >= len(self.state_tracker.doorbell_audioFiles):
                self.value = len(self.state_tracker.doorbell_audioFiles) - 1
            
            self.state_tracker.doorbell_currentAudioFile = self.value
            self.oled_text = self.state_tracker.doorbell_audioFiles[self.state_tracker.doorbell_currentAudioFile].rsplit("/")[-1]

        # Display the result of this action on the OLED, if it is enabled.
        if self.state_tracker.oled_enabled and self.oled_text:
            # reset the number of cycles that the main thread will run through, before restoring the display.
            self.state_tracker.controlsLockCycles = 40
            print(f"[encoder][{self.rotaryFunction}] {self.oled_text}")
            self.device.clear()
            with canvas(self.device) as draw:
                self.text_w, self.text_h = draw.textsize(self.oled_text,self.state_tracker.oled_default_font)
                self.text_x = 0
                self.text_y = (self.device.height / 2) - self.text_h
                draw.text((self.text_x,self.text_y), text=self.oled_text, font=self.state_tracker.oled_default_font, fill="white")

    def swAction(self, swFunction):
        self.swFunction = swFunction
        self.oled_text = False

        print(f"[encoder][swAction] triggered {self.swFunction} action")
        
        # reset the number of cycles that the main thread will run through, before restoring the display.
        self.state_tracker.controlsLockCycles = 40

        if self.swFunction == "mute":
            if self.mixer.getmute()[0] == 0:
                self.mixer.setmute(1)
                self.oled_text = "MUTE ON"
            else:
                self.mixer.setmute(0)
                self.value = self.mixer.getvolume()[0]
                self.oled_text = "Volume: " + str(self.value)
        
        if self.swFunction == "amoledToggle":
            if self.state_tracker.amoled_enabled:
                if self.state_tracker.amoled.display_power_state(self.state_tracker.amoled_display_id) == "on":
                    self.state_tracker.amoled.display_power_off(self.state_tracker.amoled_display_id)
                else:
                    self.state_tracker.amoled.display_power_on(self.state_tracker.amoled_display_id)

        # Display the result of this action on the OLED, if it is enabled.
        if self.state_tracker.oled_enabled and self.oled_text:
            # clear the oled display and temporarily use it to show the controls action.            
            self.device.clear()
            with canvas(self.device) as draw:
                self.text_w, self.text_h = draw.textsize(self.oled_text,self.state_tracker.oled_default_font)
                if self.text_w > self.device.width:
                    # shrink the text
                    self.oled_font = self.state_tracker.oled_small_font
                    self.text_w, self.text_h = draw.textsize(self.oled_text,self.state_tracker.oled_small_font)

                self.text_x = (self.device.width / 2) - self.text_w
                self.text_y = (self.device.height / 2) - self.text_h
                draw.text((self.text_x,self.text_y), text=self.oled_text, font=self.oled_font, fill="white")
