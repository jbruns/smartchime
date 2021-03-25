import json
import logging
import time
import socket

import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO

from datetime import datetime, timedelta
from pathlib import Path

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.core.image_composition import ImageComposition
from luma.oled.device import ssd1306
from luma.core import cmdline, error

from PIL import ImageFont

from scroller import Scroller
from synchronizer import Synchronizer
from widgetFactory import WidgetFactory
from encoder import Encoder
from stateTracker import StateTracker

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)-15s - %(message)s'
)

def load_config():
    with open('config.json', 'r') as jsonConfig:
        data = json.load(jsonConfig)
        return data

def get_device():
    parser = cmdline.create_parser(description='smartchime.luma')
    lumaConfig = []
    for key,value in config['luma'].items():
        lumaConfig.append(f"--{key}={value}")

    args = parser.parse_args(lumaConfig)

    # create device
    try:
        device = cmdline.create_device(args)
        return device

    except error.Error as e:
        parser.error(e)
        return None

def make_font(name, size):
    font_path = str(Path(__file__).resolve().parent.joinpath('fonts', name))
    return ImageFont.truetype(font_path, size)



try:
    state_tracker = StateTracker()
    config = load_config()
    oled_config = config['smartchime']['oled']
    mqtt_config = config['smartchime']['mqtt']
    fonts_config = oled_config['fonts'][0]

    # set up MQTT client
    mqtt_client = mqtt.Client(socket.getfqdn())
    mqtt_client.username_pw_set(mqtt_config[0]['username'],mqtt_config[0]['password'])
    mqtt_client.smartchime_topic = mqtt_config[0]['topic']
    mqtt_client.smartchime_message = "Connecting to MQTT"
    mqtt_client.on_connect=state_tracker.mqtt_on_connect
    mqtt_client.on_subscribe=state_tracker.mqtt_on_subscribe
    mqtt_client.on_message=state_tracker.mqtt_on_message
    mqtt_client.connect(mqtt_config[0]['address'])
    mqtt_client.loop_start()

    # set up OLED display device
    device = get_device()
    
    # set up front panel controls and initial values
    GPIO.setmode(GPIO.BCM)
    renc1 = Encoder(15, 23, 14, state_tracker.renc1_on_rotary, state_tracker.renc1_on_switch)
    renc2 = Encoder(27, 22, 17, state_tracker.renc2_on_rotary, state_tracker.renc2_on_switch)

    # TODO: volume, audio file index?
    renc1.value = 100
    renc2.value = 1

    # HACK: temporary workaround for ssd1305 differences
    if oled_config['ssd1305hackenabled']:
        device.command(
            0xAE, 0x04, 0x10, 0x40, 0x81, 0x80, 0xA1, 0xA6,
            0xA8, 0x1F, 0xC8, 0xD3, 0x00, 0xD5, 0xF0, 0xd8,
            0x05, 0xD9, 0xC2, 0xDA, 0x12, 0xDB, 0x08, 0xAF)
        device._colstart += 4
        device._colend += 4
    # END HACK

    image_composition = ImageComposition(device)

    # initialize OLED layout
    # row settings that won't change
    num_rows = len(oled_config['arrangement'][0])
    scrollers = []

    for row in oled_config['arrangement'][0]:
        vars()[row] = oled_config['arrangement'][0][row]
        # transform font strings to ImageDraw objects
        vars()[row][0]['iconFont'] = make_font(fonts_config[vars()[row][0]['iconFont']][0]['name'],fonts_config[vars()[row][0]['iconFont']][0]['size'])
        vars()[row][0]['textFont'] = make_font(fonts_config[vars()[row][0]['textFont']][0]['name'],fonts_config[vars()[row][0]['textFont']][0]['size'])

    while True:
        time.sleep(0.0125)
        for scroller in scrollers:
            vars()[scroller].tick()
        if datetime.now() > state_tracker.nextRefresh:
            state_tracker.nextRefresh += timedelta(seconds=oled_config['refreshInterval'])
            for scroller in scrollers:
                del vars()[scroller]
            scrollers = []
            r = 0
            synchronizer = Synchronizer()
            for row in oled_config['arrangement'][0]:
                r += 1
                row_columns = len(vars()[row][0]['columns'][0])
                row_y = vars()[row][0]['y']
                for col in vars()[row][0]['columns'][0]:
                    widget = vars()[row][0]['columns'][0][col]
                    print(f"[main][{row}] column {col}: {widget}")
                
                    vars()[widget] = WidgetFactory(device, image_composition, widget, oled_config[widget][0], vars()[row][0]['iconFont'], vars()[row][0]['textFont'], state_tracker)

                    if col == "1":
                        vars()[widget].icon_x = 0
                    if col == "4":
                        vars()[widget].icon_x = device.width - vars()[widget].widget_w
                    
                    if row_columns == 3:
                        if col == "2":
                            vars()[widget].icon_x = round(device.width * 0.25)
                        if col == "3":
                            vars()[widget].icon_x = round(device.width * 0.75 - vars()[widget].widget_w)
                    elif col == "2" or col == "3":
                        vars()[widget].icon_x = round(device.width * 0.5 - vars()[widget].widget_w * 0.5)
                    
                    vars()[widget].text_x += vars()[widget].icon_x
                    
                    if row_y > 0:
                        s = (device.height - row_y) / (num_rows - 1)
                        f = [row_y + s * i for i in range(num_rows)]
                        r2 = r - 1
                        vars()[widget].icon_y = round(f[r2] - vars()[widget].icon_h) 
                        vars()[widget].text_y = round(f[r2] - vars()[widget].text_h)
                    else:
                        vars()[widget].icon_y = 0
                        vars()[widget].text_y = 0

                    print(f"[main][{row}][{widget}] placement: x: {vars()[widget].icon_x} y: {vars()[widget].icon_y}")
                    vars()[widget].ci_icon.position = (vars()[widget].icon_x, vars()[widget].icon_y)
                    vars()[widget].ci_text.position = (vars()[widget].text_x, vars()[widget].text_y)

                    image_composition.refresh()
                
                if vars()[row][0]['scroll']:
                    widget_scroller = widget + "_scroller"
                    scrollers.append(widget_scroller)
                    vars()[widget_scroller] = Scroller(image_composition,vars()[widget].ci_text,100,synchronizer)

        with canvas(device, background=image_composition()) as draw:
            image_composition.refresh()
            for row in oled_config['arrangement'][0]:
                row_y = vars()[row][0]['y'] - 2
                if row_y > 0:
                    draw.line(((0,row_y),(device.width,row_y)),fill="white",width=1)

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
