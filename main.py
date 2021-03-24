import json
import logging
import time
import socket

import paho.mqtt.client as mqtt

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

def mqtt_on_message(client, userdata, message):
    str(message.payload.decode("utf-8"))
    next_refresh = datetime.now()

try:
    config = load_config()
    oled_config = config['smartchime']['oled']
    mqtt_config = config['smartchime']['mqtt']
    fonts_config = oled_config['fonts'][0]

    mqtt_widget_text = "Connecting to MQTT"
    mqtt_client = mqtt.Client(socket.getfqdn())
    mqtt_client.on_message=mqtt_on_message
    mqtt_client.username_pw_set(mqtt_config[0]['username'],mqtt_config[0]['password'])
    mqtt_client.connect(mqtt_config[0]['address'])
    mqtt_client.loop_start()
    mqtt_client.subscribe(mqtt_config[0]['topic'], qos=1)

    device = get_device()
    
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
    global next_refresh
    next_refresh = datetime.now() - timedelta(seconds=30)
    for row in oled_config['arrangement'][0]:
        vars()[row] = oled_config['arrangement'][0][row]
        # transform font strings to ImageDraw objects
        vars()[row][0]['iconFont'] = make_font(fonts_config[vars()[row][0]['iconFont']][0]['name'],fonts_config[vars()[row][0]['iconFont']][0]['size'])
        vars()[row][0]['textFont'] = make_font(fonts_config[vars()[row][0]['textFont']][0]['name'],fonts_config[vars()[row][0]['textFont']][0]['size'])

    while True:
        time.sleep(0.0125)
        for scroller in scrollers:
            vars()[scroller].tick()
        if datetime.now() > next_refresh:
            for scroller in scrollers:
                del vars()[scroller]
            scrollers = []
            next_refresh = datetime.now() + timedelta(seconds=30)
            r = 0
            synchronizer = Synchronizer()
            for row in oled_config['arrangement'][0]:
                r += 1
                row_columns = len(vars()[row][0]['columns'][0])
                row_y = vars()[row][0]['y']
                for col in vars()[row][0]['columns'][0]:
                    widget = vars()[row][0]['columns'][0][col]
                    print(f"[main][{row}] column {col}: {widget}")
                
                    vars()[widget] = WidgetFactory(device, image_composition, widget, oled_config[widget][0], vars()[row][0]['iconFont'], vars()[row][0]['textFont'])

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
                    vars()[widget_scroller] = scroller(image_composition,vars()[widget].ci_text,100,synchronizer)

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