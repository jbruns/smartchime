import time
import logging
from datetime import datetime
from threading import Timer
from os import path
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageDraw, ImageFont

class OLEDManager:
    """Manages a 128x32 OLED display with optimized updates and multiple display modes."""
    
    # Font Awesome icons for status bar
    ICON_CLOCK = "\uf017"      # fa-clock
    ICON_WALKING = "\uf554"    # fa-person-walking
    
    # Display modes
    MODE_DEFAULT = "default"
    MODE_CENTERED = "centered_2line"
    
    def __init__(self, spi_port=0, spi_device=0):
        """Initialize the OLED display manager.
        
        Args:
            spi_port (int): SPI port number (default: 0)
            spi_device (int): SPI device number (default: 0)
        """
        self.logger = logging.getLogger(__name__)
        
        # Initialize display
        try:
            serial = spi(port=spi_port, device=spi_device)
            self.device = ssd1306(serial, width=128, height=32)
            # We're actually using an ssd1305-based display, so we need to accomodate the differences.
            # https://github.com/rm-hull/luma.oled/issues/309#issuecomment-2559715206
            self.device.command(0xDA, 0x12) # Use alternate COM pin configuration
            self.device._colstart += 4
            self.device._colend += 4
            self.logger.info(f"Initialized OLED display on SPI port {spi_port}, device {spi_device}")
        except Exception as e:
            self.logger.error(f"Failed to initialize OLED display: {e}")
            raise
            
        # Load fonts
        try:
            font_dir = path.join(path.dirname(path.abspath(__file__)), "fonts")
            self.icon_font = ImageFont.truetype(path.join(font_dir, "fa-solid-900.ttf"), 8)
            self.status_font = ImageFont.truetype(path.join(font_dir, "Dot Matrix Regular.ttf"), 9)
            self.text_font = ImageFont.truetype(path.join(font_dir, "Dot Matrix Regular.ttf"), 11)
            self.scroll_font = ImageFont.truetype(path.join(font_dir, "Dot Matrix Regular.ttf"), 20)
            self.logger.info("Loaded display fonts")
        except Exception as e:
            self.logger.error(f"Failed to load fonts: {e}")
            raise
            
        # Display state
        self.current_mode = self.MODE_DEFAULT
        self.current_message = ""
        self.temp_message = None
        self.original_message = None
        self.temp_timer = None
        self.line1 = ""
        self.line2 = ""
        self.last_motion_time = None
        self.motion_active = False
        
        # Scroll state
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        
        # Update tracking
        self.last_minute = -1
        self.status_update_needed = True
        self.content_update_needed = True
        
    def set_mode(self, mode, line1="", line2="", duration=None):
        """Set the display mode and content.
        
        Args:
            mode (str): Either 'default' or 'centered_2line'
            line1 (str, optional): First line for centered mode
            line2 (str, optional): Second line for centered mode
            duration (float, optional): Duration in seconds before reverting to default mode
        """
        if mode not in [self.MODE_DEFAULT, self.MODE_CENTERED]:
            raise ValueError(f"Invalid mode: {mode}")
            
        # Clear any temporary message state
        self._cancel_temp_message()
        
        # Update display state
        self.current_mode = mode
        if mode == self.MODE_CENTERED:
            self.line1 = line1
            self.line2 = line2
            self.scroll_position = 0
            self.scroll_start_time = None
            
            if duration:
                Timer(duration, self._revert_to_default).start()
        
        # Force full display update
        self._clear_display()
        self.status_update_needed = True
        self.content_update_needed = True
        
    def set_scrolling_message(self, message):
        """Set the scrolling message for default mode.
        
        Args:
            message (str): Message to scroll
        """
        if self.current_mode != self.MODE_DEFAULT:
            return
            
        self.current_message = message
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        self.content_update_needed = True
        
    def set_temporary_message(self, message, duration=None):
        """Set a temporary scrolling message with auto-revert.
        
        Args:
            message (str): Temporary message to display
            duration (float): Duration in seconds before reverting
        """
        if self.current_mode != self.MODE_DEFAULT:
            return
            
        # Store original message if this is the first temporary message
        if not self.temp_message:
            self.original_message = self.current_message
            
        # Update temporary message
        self.temp_message = message
        self.current_message = message
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        self.content_update_needed = True
        
        # Reset/create timer
        self._cancel_temp_message()
        if duration:
            self.temp_timer = Timer(duration, self._restore_original_message)
            self.temp_timer.start()

    def clear_temporary_message(self):
        """Clears the temporary scrolling message, if it is set."""
        if self.current_mode != self.MODE_DEFAULT:
            return
        
        self._cancel_temp_message()
        self._restore_original_message()

    def update_motion_status(self, active=None, last_time=None):
        """Update motion detection status.
        
        Args:
            active (bool, optional): Current motion state
            last_time (datetime, optional): Time of last detected motion
        """
        update_needed = False
        
        if active is not None and active != self.motion_active:
            self.motion_active = active
            update_needed = True
            
        if last_time is not None and last_time != self.last_motion_time:
            self.last_motion_time = last_time
            update_needed = True
            
        if update_needed:
            self.status_update_needed = True
            
    def update_display(self):
        """Update the display, optimizing updates by section."""
        current_time = datetime.now()
        
        # Check if clock needs updating (once per minute)
        if current_time.minute != self.last_minute:
            self.status_update_needed = True
            self.last_minute = current_time.minute
        
        # Update status bar if needed
        if self.status_update_needed:
            self._update_status_bar()
            
        # Update content area if needed
        if self.content_update_needed:
            self._update_content_area()
            
        # Schedule next scroll update if needed
        if self.current_mode == self.MODE_DEFAULT and self.current_message:
            self._update_scroll_state()
            
    def _clear_display(self):
        """Clear the entire display."""
        with canvas(self.device) as draw:
            draw.rectangle((0, 0, self.device.width-1, self.device.height-1), fill="black")
            
    def _update_status_bar(self):
        """Update the status bar section."""
        try:
            with canvas(self.device) as draw:
                # Clear status bar area
                draw.rectangle((0, 0, self.device.width-1, 9), fill="black")
                
                # Draw time
                current_time = datetime.now().strftime("%a %m/%d %-I:%M%p")
                icon_width = draw.textlength(self.ICON_CLOCK, font=self.icon_font)
                draw.text((0, 0), self.ICON_CLOCK, font=self.icon_font, fill="white")
                draw.text((icon_width + 2, 0), current_time, font=self.status_font, fill="white")
                
                # Draw separator
                sep_x = int(self.device.width * 0.75)
                draw.line([(sep_x, 0), (sep_x, 8)], fill="white", width=1)
                
                # Draw motion status
                motion_text = self._format_motion_time()
                motion_icon_width = draw.textlength(self.ICON_WALKING, font=self.icon_font)
                motion_text_width = draw.textlength(motion_text, font=self.status_font)
                motion_x = self.device.width - (motion_icon_width + 2 + motion_text_width)
                
                draw.text((motion_x, 0), self.ICON_WALKING, font=self.icon_font, fill="white")
                draw.text((motion_x + motion_icon_width + 2, 0), motion_text, font=self.status_font, fill="white")
                
                # Draw horizontal separator
                draw.line([(0, 9), (self.device.width-1, 9)], fill="white", width=1)
                
            self.status_update_needed = False
            
        except Exception as e:
            self.logger.error(f"Error updating status bar: {e}")
            
    def _update_content_area(self):
        """Update the main content area."""
        try:
            with canvas(self.device) as draw:
                # Clear content area
                draw.rectangle((0, 10, self.device.width-1, self.device.height-1), fill="black")
                
                if self.current_mode == self.MODE_CENTERED:
                    self._draw_centered_text(draw)
                elif self.current_mode == self.MODE_DEFAULT and self.current_message:
                    self._draw_scrolling_text(draw)
                    
            self.content_update_needed = False
            
        except Exception as e:
            self.logger.error(f"Error updating content area: {e}")
            
    def _draw_centered_text(self, draw):
        """Draw centered text lines."""
        if self.line1:
            line1 = self._truncate_text(self.line1, self.device.width, draw)
            x1, y1 = self._center_text(line1, draw, 12, 10)
            draw.text((x1, y1), line1, font=self.text_font, fill="white")
            
        if self.line2:
            line2 = self._truncate_text(self.line2, self.device.width, draw)
            x2, y2 = self._center_text(line2, draw, 12, 22)
            draw.text((x2, y2), line2, font=self.text_font, fill="white")
            
    def _draw_scrolling_text(self, draw):
        """Draw scrolling text."""
        if not self.current_message:
            return
            
        msg_width = draw.textlength(self.current_message, font=self.scroll_font)
        
        if msg_width <= self.device.width:
            # Center short messages
            x_pos = (self.device.width - msg_width) // 2
        else:
            # Scroll long messages
            x_pos = self.device.width - self.scroll_position
            
        draw.text((x_pos, 16), self.current_message, font=self.scroll_font, fill="white")
        
    def _update_scroll_state(self):
        """Update scrolling text state."""
        if not self.current_message:
            return
            
        current_time = time.time()
        
        if self.scroll_start_time is None:
            self.scroll_start_time = current_time
            return
            
        with canvas(self.device) as draw:
            msg_width = draw.textlength(self.current_message, font=self.scroll_font)
            
            if msg_width <= self.device.width:
                return
                
            if self.scroll_paused:
                if current_time - self.scroll_start_time >= 2.0:
                    self.scroll_paused = False
                    self.scroll_position = 0
                    self.content_update_needed = True
            else:
                if self.scroll_position >= msg_width + self.device.width:
                    self.scroll_paused = True
                    self.scroll_start_time = current_time
                else:
                    self.scroll_position += 1
                    self.content_update_needed = True
                    
    def _truncate_text(self, text, max_width, draw):
        """Truncate text to fit width, adding ellipsis if needed."""
        if draw.textlength(text, font=self.text_font) <= max_width:
            return text
            
        while len(text) > 3 and draw.textlength(text[:-3] + "...", font=self.text_font) > max_width:
            text = text[:-4]
        return text + "..."
        
    def _center_text(self, text, draw, height, y_offset):
        """Calculate position to center text."""
        text_width = draw.textlength(text, font=self.text_font)
        bbox = self.text_font.getbbox(text)
        text_height = bbox[3] - bbox[1]
        
        x = (self.device.width - text_width) // 2
        y = y_offset + (height - text_height) // 2
        return x, y
        
    def _format_motion_time(self):
        """Format time since last motion."""
        if self.motion_active:
            return "now"
            
        if self.last_motion_time is None:
            return "??"
            
        delta = datetime.now() - self.last_motion_time
        minutes = int(delta.total_seconds() / 60)
        
        if minutes < 60:
            return f"{minutes}m"
        return f"{minutes // 60}h"
        
    def _restore_original_message(self):
        """Restore the original message after temporary message expires."""
        if self.original_message is not None:
            self.current_message = self.original_message
            self.scroll_position = 0
            self.scroll_start_time = None
            self.scroll_paused = False
            self.content_update_needed = True
            
        self.temp_message = None
        self.temp_timer = None
        
    def _revert_to_default(self):
        """Revert to default mode."""
        self.set_mode(self.MODE_DEFAULT)
        
    def _cancel_temp_message(self):
        """Cancel any active temporary message timer."""
        if self.temp_timer:
            self.temp_timer.cancel()
            self.temp_timer = None
            
    def cleanup(self):
        """Clean up resources."""
        self._cancel_temp_message()