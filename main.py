import json
import logging
import time
import socket
import pytz

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

from vcgencmd import Vcgencmd

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
    amoled_config = config['smartchime']['amoled_display']
    oled_config = config['smartchime']['oled_display']
    mqtt_config = config['smartchime']['mqtt']
    doorbell_config = config['smartchime']['doorbell']
    controls_config = config['smartchime']['controls']
    fonts_config = oled_config['fonts'][0]

    # Enable or disable major functions and provide that state to the state tracker.
    state_tracker.oled_enabled = oled_config['enabled']
    state_tracker.amoled_enabled = amoled_config['enabled']
    state_tracker.doorbell_enabled = doorbell_config['enabled']
    state_tracker.controls_enabled = controls_config['enabled']
    state_tracker.mqtt_enabled = mqtt_config['enabled']

    # Set up the AMOLED display.
    if state_tracker.amoled_enabled:
        print("[main] initializing AMOLED display")
        state_tracker.amoled_always_on = amoled_config['always_on']
        state_tracker.amoled_display_id = amoled_config['display_id']
        state_tracker.amoled = Vcgencmd()
        if state_tracker.amoled_always_on:
            state_tracker.amoled.display_power_on(state_tracker.amoled_display_id)

    # Initialize the OLED display.
    if state_tracker.oled_enabled:
        print("[main] Initializing OLED display")
        device = get_device()
        image_composition = ImageComposition(device)

        state_tracker.oled_default_font = make_font(fonts_config['font_large'][0]['name'],fonts_config['font_large'][0]['size'])
        state_tracker.oled_small_font = make_font(fonts_config['font_small'][0]['name'],fonts_config['font_small'][0]['size'])

        # HACK: temporary workaround for ssd1305 differences
        if oled_config['ssd1305hackenabled']:
            device.command(
                0xAE, 0x04, 0x10, 0x40, 0x81, 0x80, 0xA1, 0xA6,
                0xA8, 0x1F, 0xC8, 0xD3, 0x00, 0xD5, 0xF0, 0xd8,
                0x05, 0xD9, 0xC2, 0xDA, 0x12, 0xDB, 0x08, 0xAF)
            device._colstart += 4
            device._colend += 4
        # END HACK

        # initialize OLED layout
        # row settings that won't change
        num_rows = len(oled_config['arrangement'][0])
        scrollers = []

        for row in oled_config['arrangement'][0]:
            vars()[row] = oled_config['arrangement'][0][row]
            # transform font strings to ImageDraw objects
            vars()[row][0]['iconFont'] = make_font(fonts_config[vars()[row][0]['iconFont']][0]['name'],fonts_config[vars()[row][0]['iconFont']][0]['size'])
            vars()[row][0]['textFont'] = make_font(fonts_config[vars()[row][0]['textFont']][0]['name'],fonts_config[vars()[row][0]['textFont']][0]['size'])

        # Enable/disable widgets. The clock widget doesn't depend on external data, so to disable it, do not assign it in a column.
        # On the other hand, if other widgets are disabled, their external data will not be pulled in. Placeholder values will be used instead.
        state_tracker.oled_widget_motion_enabled = oled_config['motion'][0]['enabled']
        state_tracker.oled_widget_message_enabled = oled_config['message'][0]['enabled']

    else:
        device = False
        image_composition = False
    
    if state_tracker.mqtt_enabled:
        # set up MQTT client and subscribe to topics/functions that are enabled in config.
        print("[main] Initializing MQTT connection")
        mqtt_client = mqtt.Client(socket.getfqdn())
        mqtt_client.username_pw_set(mqtt_config['username'],mqtt_config['password'])
        
        if state_tracker.oled_enabled and state_tracker.oled_widget_message_enabled:
            print("[main] Initializing OLED message widget")
            mqtt_client.message_topic = oled_config['message'][0]['topic']
            # initialize the widget with a placeholder value until it is replaced by a real MQTT message.
            state_tracker.message = "smartchime ready for action!"
        else:
            mqtt_client.message_topic = False
            state_tracker.message = ""
            state_tracker.last_message = ""
        
        if state_tracker.oled_enabled and state_tracker.oled_widget_motion_enabled:
            print("[main] Initializing OLED motion widget")
            mqtt_client.motion_topic = oled_config['motion'][0]['topic']
            # initialize the widget with a placeholder value until it is replaced by a real MQTT message.
            state_tracker.last_motion = "00:00"
        else:
            mqtt_client.motion_topic = False

        if state_tracker.doorbell_enabled:
            print("[main] Initializing doorbell")
            mqtt_client.doorbell_topic = doorbell_config['topic']
            state_tracker.doorbell_audioFiles = doorbell_config['audioFiles']
            state_tracker.doorbell_currentAudioFile = 0
        else:
            mqtt_client.doorbell_topic = False
        
        mqtt_client.on_connect=state_tracker.mqtt_on_connect
        mqtt_client.on_subscribe=state_tracker.mqtt_on_subscribe
        mqtt_client.on_message=state_tracker.mqtt_on_message
        mqtt_client.connect(mqtt_config['address'])
        mqtt_client.loop_start()

    if state_tracker.controls_enabled:
        # set up front panel controls. initial values will be determined in the encoder object.
        GPIO.setmode(GPIO.BCM)
        renc1 = Encoder(
            controls_config['rotaryEncoder1'][0]['leftPin'], 
            controls_config['rotaryEncoder1'][0]['rightPin'], 
            controls_config['rotaryEncoder1'][0]['switchPin'],
            controls_config['rotaryEncoder1'][0]['rotaryFunction'],
            controls_config['rotaryEncoder1'][0]['switchFunction'],
            state_tracker,
            device)
        renc2 = Encoder(
            controls_config['rotaryEncoder2'][0]['leftPin'], 
            controls_config['rotaryEncoder2'][0]['rightPin'], 
            controls_config['rotaryEncoder2'][0]['switchPin'], 
            controls_config['rotaryEncoder2'][0]['rotaryFunction'],
            controls_config['rotaryEncoder2'][0]['switchFunction'],
            state_tracker,
            device)

        state_tracker.controlsLockCycles = 0
        
    # Main loop
    while True:
        time.sleep(0.0125)
        if state_tracker.controls_enabled:
            if state_tracker.controlsLockCycles > 0:
                state_tracker.controlsLockCycles = state_tracker.controlsLockCycles - 1
                state_tracker.must_refresh = True

        # physical controls take precedence over the "normal" widget display, so don't take away the display lock if the controls haven't released it.
        if state_tracker.oled_enabled and state_tracker.controlsLockCycles == 0:
            # Advance the scrolling widgets.
            for scroller in scrollers:
                vars()[scroller].tick()
                
            if state_tracker.must_refresh:
                state_tracker.must_refresh = False
                # clear the active scrolling widgets and reset the synchronizer.
                for scroller in scrollers:
                    del vars()[scroller]
                scrollers = []
                synchronizer = Synchronizer()
                
                # Arrange widgets on the ImageComposition, per the config. This is done one row at a time as follows:
                #   - set the y-coordinate for the row.
                #   - for each configured widget, call the WidgetFactory to create the widget content for eventual placement on the ImageComposition.
                #   - place each widget according to column identifier (1-4):
                #       - 1: left justified.
                #       - 4: right justified.
                #       - columns 2 and 3 make use of a little extra logic: if both exist, split them evenly across the center of the display. if only one is present, center it.
                #   - position the widgets (icon + text) according to the x/y coordinates that have been determined.
                #   - refresh the ImageComposition to make the new positions take effect.
                #   - enable scrolling for widgets that declare as such in their config.
                r = 0
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
                            if vars()[widget].icon_h == 0:
                                vars()[widget].icon_y = vars()[widget].text_y
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

            # Draw the ImageComposition to the device, adding dividers between rows.
            with canvas(device, background=image_composition()) as draw:
                image_composition.refresh()
                for row in oled_config['arrangement'][0]:
                    row_y = vars()[row][0]['y'] - 2
                    if row_y > 0:
                        draw.line(((0,row_y),(device.width,row_y)),fill="white",width=1)
        
            # trigger an update to the clock widget if necessary.        
            utcTime = datetime.utcnow().replace(tzinfo=pytz.utc)
            localTime = utcTime.astimezone(pytz.timezone(oled_config['clock'][0]['timezone']))
            clockTime = localTime.strftime(oled_config['clock'][0]['dateTimeFormat'])
            if clockTime != clock.text:
                state_tracker.must_refresh = True

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
