class StateTracker():
    def __init__(self,oledRefresh=True):
        self.oledRefresh = oledRefresh
    
    def mqtt_on_connect(self,client,userdata,flags,rc):
        print(f"[mqtt][on_connect]: {client.connack_string(rc)}")
        self.mqtt_client = client
        self.mqtt_client.subscribe(self.mqtt_client.smartchime_topic, qos=1)

    def mqtt_on_subscribe(self,client,userdata,mid,granted_qos):
        print(f"[mqtt][on_subscribe]: {mid}")
        self.mqtt_client = client
        self.mqtt_client.publish(self.mqtt_client.smartchime_topic, qos=1)
    
    def mqtt_on_message(self,client,userdata,message):
        print(f"[mqtt][on_message]: received message from topic {message.topic}")
        self.mqtt_message = str(message.payload)
        self.oledRefresh = True
