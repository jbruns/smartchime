import json
from datetime import datetime

class StateTracker():
    def __init__(self):
        self.nextRefresh = datetime.now()
    
    def mqtt_on_connect(self,client,userdata,flags,rc):
        print(f"[mqtt][on_connect]: {rc}")
        self.mqtt_client = client
        self.mqtt_client.subscribe(self.mqtt_client.smartchime_topic, qos=1)

    def mqtt_on_subscribe(self,client,userdata,mid,granted_qos):
        print(f"[mqtt][on_subscribe]: {mid}")
        self.mqtt_client = client
        self.mqtt_client.publish(self.mqtt_client.smartchime_topic, payload="smartchime ready for action!", qos=1)
    
    def mqtt_on_message(self,client,userdata,message):
        print(f"[mqtt][on_message]: received message from topic {message.topic}")
        self.mqtt_message = str(message.payload.decode("utf-8"))
        self.nextRefresh = datetime.now()

    def renc1_on_rotary(self,value):
        print(f"[renc1][on_rotary] {value}")
    
    def renc1_on_switch(self):
        print(f"[renc1][on_switch]")
    
    def renc2_on_rotary(self,value):
        print(f"[renc2][on_rotary] {value}")
    
    def renc2_on_switch(self):
        print(f"[renc2][on_switch]")