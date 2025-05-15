import time
import logging
from datetime import datetime
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
from os import path
import threading

class OLEDManager:
    """OLED display manager providing a clean API for display updates.
    All display manipulations should go through this class."""
    
    # Font Awesome unicode characters
    ICON_CLOCK = "\uf017"  # fa-clock
    ICON_WALKING = "\uf554"  # fa-person-walking
    
    def __init__(self, spi_port, spi_device):
        """Initialize OLED display manager.
        
        Args:
            spi_port (int): SPI port number for display, usually 0
            spi_device (int): SPI device of the display, usually 0"""
        self.logger = logging.getLogger(__name__)
        try:
            serial = spi(port=spi_port, device=spi_device)
            self.device = ssd1306(serial, width=128, height=32)
            # We're actually using an ssd1305-based display, so we need to accomodate the differences.
            # https://github.com/rm-hull/luma.oled/issues/309#issuecomment-2559715206
            self.device.command(0xDA, 0x12) # Use alternate COM pin configuration
            self.device._colstart += 4
            self.device._colend += 4

            self.logger.info(f"Initialized OLED display on SPI port {spi_port}, device {spi_device}.")
        except Exception as e:
            self.logger.error(f"Failed to initialize OLED display: {e}")
            raise
        
        # Display state
        self.current_mode = "default"  # default, centered, scrolling
        self.scroll_position = 0
        self.previous_scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = True
        
        # Message state
        self.current_message = ""
        self.temporary_message = None
        self.temp_duration = 0
        self.temp_message_thread = None
        self.previous_message = ""
        
        # Motion state
        self.last_motion_time = None
        self.motion_active = False
        self.motion_update_required = True
        
        # Display content
        self.line1 = ""
        self.line2 = ""
        
        # Update tracking
        self.last_minute = -1
        self.last_content_update_time = 0
        self.status_bar_update_required = True
        self.content_update_required = True
        self._content_drawn = False  # Track whether content has been initially drawn
        self._status_drawn = False   # Track whether status bar has been initially drawn
        
        # Load fonts - try Font Awesome first, then fallback fonts
        try:
            self.project_dir = path.dirname(path.abspath(__file__))
            self.icon_font_path = path.join(self.project_dir, "fonts", "fa-solid-900.ttf")
            self.text_font_path = path.join(self.project_dir, "fonts", "Dot Matrix Regular.ttf")
            self.icon_font = ImageFont.truetype(self.icon_font_path, 8)
            self.status_font = ImageFont.truetype(self.text_font_path, 9)  # For clock and motion status
            self.scroll_font = ImageFont.truetype(self.text_font_path, 20)  # For scrolling messages
            self.text_font = ImageFont.truetype(self.text_font_path, 11)  # Default text font for other purposes
            self.logger.info("Loaded Font Awesome and Dot Matrix Regular fonts")
        except OSError as e:
            self.logger.warning(f"Could not load preferred fonts, falling back to alternatives: {e}")
            try:
                self.status_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
                self.scroll_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                self.text_font = self.status_font
                self.icon_font = self.text_font  # Fallback to regular font if FA not available
                self.logger.info("Loaded DejaVu Sans font as fallback")
            except OSError as e:
                self.logger.warning(f"Could not load DejaVu Sans font, using default: {e}")
                self.text_font = ImageFont.load_default()
                self.status_font = self.text_font
                self.scroll_font = self.text_font
                self.icon_font = self.text_font

    def show_centered_text(self, line1, line2="", duration=None):
        """Display two lines of centered text. Each line is truncated if too long.
        
        Args:
            line1 (str): First line of text (top)
            line2 (str, optional): Second line of text (bottom)
            duration (float, optional): How long to show text before reverting"""
        self.logger.debug(f"Showing centered text: '{line1}' / '{line2}' (duration: {duration}s)")
        self.current_mode = "centered"
        self.line1 = line1
        self.line2 = line2
        self._content_drawn = False  # Mark that new content needs to be drawn
        self.content_update_required = True
        
        if duration:
            self._set_temporary_message(duration)
        
    def show_scrolling_text(self, text, duration=None):
        """Display a scrolling message in the bottom portion of the display.
        
        Args:
            text (str): Text to scroll
            duration (float, optional): How long to show text before reverting"""
        self.logger.debug(f"Showing scrolling text: '{text}' (duration: {duration}s)")
        self.current_mode = "scrolling"
        self.current_message = text
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = True
        self._content_drawn = False  # Mark that new content needs to be drawn
        self.content_update_required = True
        
        if duration:
            self._set_temporary_message(duration)
            
    def show_status(self, motion_active=None, motion_time=None):
        """Update the motion detection status display.
        
        Args:
            motion_active (bool, optional): Whether motion is currently active
            motion_time (datetime, optional): Time of last motion detection"""
        if motion_active is not None:
            self.motion_active = motion_active
            self.motion_update_required = True
            self._status_drawn = False  # Mark that status needs to be redrawn
            self.logger.info(f"Motion status changed: {'active' if motion_active else 'inactive'}")
        if motion_time is not None:
            self.last_motion_time = motion_time
            self.motion_update_required = True
            self._status_drawn = False  # Mark that status needs to be redrawn
            self.logger.debug(f"Motion time updated: {motion_time}")
            
    def clear_display(self):
        """Clear all content from the display and cancel any temporary messages."""
        self.logger.debug("Clearing display")
        self.current_mode = "default"
        self.current_message = ""
        self.line1 = ""
        self.line2 = ""
        self._content_drawn = False
        self._status_drawn = False  # Ensure status bar is redrawn too
        self.content_update_required = True
        self.status_bar_update_required = True
        self._cancel_temporary_message()
        
    def _set_temporary_message(self, duration):
        """Set up a temporary message that reverts after duration.
        
        Args:
            duration (float): Time in seconds before reverting to previous state"""
        self._cancel_temporary_message()
        
        # Store current state
        self.temporary_message = {
            'mode': self.current_mode,
            'message': self.current_message,
            'line1': self.line1,
            'line2': self.line2
        }
        self.temp_duration = duration
        
        # Set up restore timer
        self.temp_message_thread = threading.Timer(duration, self._restore_previous_state)
        self.temp_message_thread.start()
        self.logger.debug(f"Set temporary message for {duration}s")
        
    def _cancel_temporary_message(self):
        """Cancel any active temporary message and its timer."""
        if self.temp_message_thread and self.temp_message_thread.is_alive():
            self.temp_message_thread.cancel()
            self.logger.debug("Cancelled temporary message")
        self.temporary_message = None
        
    def _restore_previous_state(self):
        """Restore the display state from before a temporary message."""
        if self.temporary_message:
            self.logger.debug("Restoring previous display state")
            self.current_mode = self.temporary_message['mode']
            self.current_message = self.temporary_message['message']
            self.line1 = self.temporary_message['line1']
            self.line2 = self.temporary_message['line2']
            self._content_drawn = False  # Mark that restored content needs to be drawn
            self.content_update_required = True
            self.temporary_message = None
            
    def _truncate_text(self, text, max_width, draw):
        """Truncate text to fit within given width, adding ellipsis if needed.
        
        Args:
            text (str): Text to truncate
            max_width (int): Maximum width in pixels
            draw: PIL ImageDraw object
            
        Returns:
            str: Truncated text with ellipsis if needed"""
        if draw.textlength(text, font=self.text_font) <= max_width:
            return text
            
        while len(text) > 3 and draw.textlength(text[:-3] + "...", font=self.text_font) > max_width:
            text = text[:-4]
        return text + "..."
        
    def _center_text(self, text, draw, area_width, area_height, y_offset=0):
        """Calculate position to center text within given area.
        
        Args:
            text (str): Text to center
            draw: PIL ImageDraw object
            area_width (int): Width of area
            area_height (int): Height of area
            y_offset (int): Additional vertical offset
            
        Returns:
            tuple: (x, y) coordinates for centered text"""
        text_width = draw.textlength(text, font=self.text_font)
        bbox = self.text_font.getbbox(text)
        text_height = bbox[3] - bbox[1]  # bottom - top
        x = (area_width - text_width) // 2
        y = y_offset + (area_height - text_height) // 2
        return x, y
        
    def _format_motion_time(self):
        """Format time since last motion for display.
        
        Returns:
            str: Formatted time string"""
        if self.motion_active:
            return "now"
        if self.last_motion_time is None:
            return "??"
        delta = datetime.now() - self.last_motion_time
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        return f"{hours}h"
    
    def _update_status_bar(self, draw):
        """Draw the status bar with time and motion information.
        
        Args:
            draw: PIL ImageDraw object"""
        current_time = datetime.now()
        current_time_str = current_time.strftime("%a %m/%d %-I:%M%p")
        
        # Draw time with icon
        icon_width = draw.textlength(self.ICON_CLOCK, font=self.icon_font)
        draw.text((0, 0), self.ICON_CLOCK, font=self.icon_font, fill="white")
        draw.text((icon_width + 2, 0), current_time_str, font=self.status_font, fill="white")
        
        # Calculate separator position
        separator_x = int(self.device.width * 0.75)
        draw.line([(separator_x, 0), (separator_x, 8)], fill="white", width=1)
        
        # Draw motion status with icon
        motion_icon_width = draw.textlength(self.ICON_WALKING, font=self.icon_font)
        motion_text = self._format_motion_time()
        motion_text_width = draw.textlength(motion_text, font=self.status_font)
        motion_total_width = motion_icon_width + 2 + motion_text_width
        motion_x = self.device.width - motion_total_width
        
        draw.text((motion_x, 0), self.ICON_WALKING, font=self.icon_font, fill="white")
        draw.text((motion_x + motion_icon_width + 2, 0), motion_text, font=self.status_font, fill="white")
        
        # Draw horizontal separator
        draw.line([(0, 9), (self.device.width-1, 9)], fill="white", width=1)
        
    def _update_content_area(self, draw):
        """Draw the main content area based on current mode.
        
        Args:
            draw: PIL ImageDraw object"""
        if self.current_mode == "centered":
            if self.line1:
                truncated_line1 = self._truncate_text(self.line1, self.device.width, draw)
                x1, y1 = self._center_text(truncated_line1, draw, self.device.width, 12, 10)
                draw.text((x1, y1), truncated_line1, font=self.text_font, fill="white")
            
            if self.line2:
                truncated_line2 = self._truncate_text(self.line2, self.device.width, draw)
                x2, y2 = self._center_text(truncated_line2, draw, self.device.width, 12, 22)
                draw.text((x2, y2), truncated_line2, font=self.text_font, fill="white")
                
        elif self.current_mode == "scrolling" and self.current_message:
            msg_width = draw.textlength(self.current_message, font=self.scroll_font)
            
            if msg_width > self.device.width:
                current_time = time.time()
                
                if self.scroll_start_time is None:
                    self.scroll_start_time = current_time
                    
                if current_time - self.scroll_start_time < 2.0:
                    x_pos = self.device.width
                elif self.scroll_paused and current_time - self.scroll_start_time >= 2.0:
                    self.scroll_paused = False
                    self.scroll_position = 0
                elif self.scroll_position >= msg_width and not self.scroll_paused:
                    self.scroll_paused = True
                    self.scroll_start_time = current_time
                elif not self.scroll_paused:
                    # Check if scroll position changed
                    if self.previous_scroll_position != self.scroll_position:
                        self.content_update_required = True
                    self.previous_scroll_position = self.scroll_position
                    self.scroll_position += 1
                    
                x_pos = self.device.width - self.scroll_position
                draw.text((x_pos, 16), self.current_message, font=self.scroll_font, fill="white")
            else:
                x_pos = (self.device.width - msg_width) // 2
                draw.text((x_pos, 16), self.current_message, font=self.scroll_font, fill="white")
        
    def update_display(self):
        """Update the OLED display. Should be called regularly in the main loop.
        Optimized to only update parts of the display that have changed."""
        current_time = datetime.now()
        current_minute = current_time.minute
        
        # Check if it's time to update the clock (once per minute)
        if current_minute != self.last_minute:
            self.status_bar_update_required = True
            self.last_minute = current_minute
            
        # Initial drawing of content if mode is set but content hasn't been drawn yet
        # This ensures that both centered and scrolling text are shown immediately
        if (self.current_mode in ["centered", "scrolling"]) and (not hasattr(self, "_content_drawn") or not self._content_drawn):
            self.content_update_required = True
            self._content_drawn = True
        
        # For scrolling text, update content frequently but only when needed
        elif self.current_mode == "scrolling":
            # Update content when scrolling is active or just starting/paused
            self.content_update_required = True
            
        # Make sure status bar is always drawn initially
        if not hasattr(self, "_status_drawn") or not self._status_drawn:
            self.status_bar_update_required = True
            self._status_drawn = True
        
        # Perform status bar updates if needed
        if self.status_bar_update_required or self.motion_update_required:
            try:
                with canvas(self.device) as draw:
                    # Clear the status bar area only (0-10px height)
                    draw.rectangle((0, 0, self.device.width-1, 9), fill="black")
                    
                    # Redraw the status bar
                    self._update_status_bar(draw)
                
                self.status_bar_update_required = False
                self.motion_update_required = False
                
                # Small delay to avoid display artifacts between updates
                time.sleep(0.01)
            except Exception as e:
                self.logger.error(f"Error updating status bar: {e}")
                # Reset update flag to try again
                self._status_drawn = False
            
        # Perform content updates if needed
        if self.content_update_required:
            try:
                with canvas(self.device) as draw:
                    # Clear content area only (10-32px height)
                    draw.rectangle((0, 10, self.device.width-1, self.device.height-1), fill="black")
                    
                    # Update the content area
                    self._update_content_area(draw)
                    
                self.content_update_required = False
            except Exception as e:
                self.logger.error(f"Error updating content area: {e}")
                # Reset update flag to try again
                self._content_drawn = False
        
    def cleanup(self):
        """Clean up resources and cancel any active timers."""
        self.logger.debug("Cleaning up resources")
        self._cancel_temporary_message()