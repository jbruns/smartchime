# from pytz import utc, timezone
import pytz
from datetime import datetime
from luma.core.image_composition import ImageComposition, ComposableImage
from luma.core.render import canvas

from PIL import Image, ImageDraw

class WidgetFactory():
    def __init__(self, device, image_composition, widget, widget_config, icon_font, text_font, state_tracker):
        self.device = device
        self.image_composition = image_composition
        self.widget = widget
        self.widget_config = widget_config
        self.icon_font = icon_font
        self.text_font = text_font
        self.state_tracker = state_tracker
        self.refreshWidget()
        self.renderWidget()
        
        print(f"[widgetFactory][{widget}] adding rendered images to composition")
        self.image_composition.add_image(self.ci_icon)
        self.image_composition.add_image(self.ci_text)
    
    def __del__(self):
        self.image_composition.remove_image(self.ci_icon)
        self.image_composition.remove_image(self.ci_text)

    def refreshWidget(self):
        self.icon = self.widget_config['icon']

        if self.widget == "clock":
            self.utcTime = datetime.utcnow().replace(tzinfo=pytz.utc)
            self.localTime = self.utcTime.astimezone(pytz.timezone(self.widget_config['timezone']))

            self.text = self.localTime.strftime(self.widget_config['dateTimeFormat'])
        
        if self.widget == "motion":
            self.text = "12:34" # TEMP
        
        if self.widget == "mqtt":
            self.text = self.state_tracker.mqtt_message

        print(f"[refreshwidget][{self.widget}] icon: {self.icon}, text: {self.text}")

    def renderWidget(self):
        with canvas(self.device) as draw:
            if self.widget_config['icon']:
                self.icon_w, self.icon_h = draw.textsize(self.icon, self.icon_font)
            else:
                self.icon_w, self.icon_h = (0,0)

            self.text_w, self.text_h = draw.textsize(self.text, self.text_font)
        
        self.icon_padding = 2
        self.line_padding = 2
        self.icon_w += (self.icon_padding + self.line_padding)
        self.icon_x = 0
        self.icon_y = 0
        if self.widget_config['icon']:
            self.text_x = self.icon_w
        else:
            self.text_x = 0
        
        self.text_y = 0

        self.widget_w = self.icon_w + self.text_w
        self.widget_h = max(self.icon_h,self.text_h)

        self.icon_image = Image.new(self.device.mode,(self.icon_w,self.icon_h))
        draw = ImageDraw.Draw(self.icon_image)
        
        if self.widget_config['icon']:
            draw.text((self.line_padding,0), text=self.icon, font=self.icon_font, fill="white")
            draw.line(((0,0),(0,self.icon_h)),fill="white",width=1)
        self.ci_icon = ComposableImage(self.icon_image)
        del draw


        self.text_image = Image.new(self.device.mode,(self.text_w,self.text_h))
        draw = ImageDraw.Draw(self.text_image)
        draw.text((0,0), text=self.text, font=self.text_font, fill="white")
        self.ci_text = ComposableImage(self.text_image)
        del draw

        print(f"[renderWidget][{self.widget}] icon x: {self.icon_x}, y: {self.icon_y}, w: {self.icon_w}, h: {self.icon_h}")
        print(f"[renderWidget][{self.widget}] text x: {self.text_x}, y: {self.text_y}, w: {self.text_w}, h: {self.text_h}")
        print(f"[renderWidget][{self.widget}] total width: {self.widget_w}, height: {self.widget_h}")
