import json
import simpleaudio as sa
import alsaaudio

from datetime import datetime

class StateTracker():
    def __init__(self):
        self.nextRefresh = datetime.now()

    def mqtt_on_connect(self,client,userdata,flags,rc):
        self.mqtt_client = client
        if rc == 0:
            print(f"[mqtt][on_connect]: connected")
            if self.mqtt_client.message_topic:
                self.mqtt_message_topic_subscription = self.mqtt_client.subscribe(self.mqtt_client.message_topic, qos=1)
            if self.mqtt_client.doorbell_topic:
                self.mqtt_doorbell_topic_subscription = self.mqtt_client.subscribe(self.mqtt_client.doorbell_topic, qos=1)
            if self.mqtt_client.motion_topic:
                self.mqtt_motion_topic_subscription = self.mqtt_client.subscribe(self.mqtt_client.motion_topic, qos=1)
        else:
            print(f"[mqtt][on_connect]: exception connecting to MQTT {connack_string(rc)}")

    def mqtt_on_subscribe(self,client,userdata,mid,granted_qos):
        self.mqtt_client = client
        if self.mqtt_client.doorbell_topic and mid == self.mqtt_doorbell_topic_subscription[1]:
            print(f"[mqtt][on_subscribe]: mid: {mid}, subscribed to {self.mqtt_client.doorbell_topic}")
        if self.mqtt_client.message_topic and mid == self.mqtt_message_topic_subscription[1]:
            print(f"[mqtt][on_subscribe]: mid: {mid}, subscribed to {self.mqtt_client.message_topic}")
        if self.mqtt_client.motion_topic and mid == self.mqtt_motion_topic_subscription[1]:
            print(f"[mqtt][on_subscribe]: mid: {mid}, subscribed to {self.mqtt_client.motion_topic}")

    def mqtt_on_message(self,client,userdata,message):
        self.mqtt_client = client
        self.nextRefresh = datetime.now()
        self.messageParse = str(message.payload.decode("utf-8")).split(",")
        print(f"[mqtt][on_message]: received message from topic {message.topic}: {self.messageParse}")
        if message.topic == self.mqtt_client.message_topic:
            # update the message display.
            self.last_message = str(message.payload.decode("utf-8"))
            self.message = self.last_message
        
        if message.topic == self.mqtt_client.motion_topic:
            if self.messageParse[0] == "on":
                print(f"[mqtt][on_message] Motion detected!")
                self.last_message = self.message
                self.message = "Motion detected on doorbell camera!"
                if self.amoled_enabled:
                    self.amoled.display_power_on(self.amoled_display_id)

            if self.messageParse[0] == "off":
                print(f"[mqtt][on_message] Motion event cleared")
                self.message = self.last_message
                if self.amoled_enabled:
                    self.amoled.display_power_off(self.amoled_display_id)
            self.last_motion = self.messageParse[1]
        
        if message.topic == self.mqtt_client.doorbell_topic:
            if self.messageParse[0] == "on":
                print(f"[mqtt][on_message] Doorbell ring!")
                # doorbell ring. preserve the existing message on the display, and play the configured audio file.
                self.last_message = self.message
                self.message = "Someone's at the door!"
                wave_obj = sa.WaveObject.from_wave_file(self.doorbell_audioFiles[self.doorbell_currentAudioFile])
                play_obj = wave_obj.play()
                if self.amoled_enabled:
                    self.amoled.display_power_on(self.amoled_display_id)
            if self.messageParse[0] == "off":
                # once HA indicates the doorbell ring state has cleared, restore the previous message so that we revert the display
                print("[mqtt][on_message] Doorbell event cleared")
                self.message = self.last_message
                if self.amoled_enabled:
                    self.amoled.display_power_on(self.amoled_display_id)
