import logging
import time
from datetime import UTC, datetime
from os import path
from threading import RLock, Timer

import PIL
from luma.core.image_composition import ComposableImage, ImageComposition
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont


class OLEDManager:
    ICON_CLOCK = "\uf017"
    ICON_WALKING = "\uf554"
    LAYER_STATUS = "status"
    LAYER_CONTENT = "content"
    MODE_DEFAULT = "default"
    MODE_CENTERED = "centered_2line"

    SCROLL_SPEED_PPS = 45
    MAX_SCROLL_MESSAGE_LENGTH = 500
    BURN_IN_REFRESH_INTERVAL = 300
    BURN_IN_SLIDE_FRAMES = 10
    BURN_IN_BLANK_FRAMES = 4

    def __init__(self, spi_port=0, spi_device=0):
        """Initialize the OLED display manager.

        Args:
            spi_port (int): SPI port number.
            spi_device (int): SPI device number.
        """
        self.logger = logging.getLogger(__name__)
        self._state_lock = RLock()

        try:
            serial = spi(port=spi_port, device=spi_device)
            self.device = ssd1306(serial, width=128, height=32)

            # We're actually using an ssd1305-based display, so we need to accomodate the differences.
            # https://github.com/rm-hull/luma.oled/issues/309#issuecomment-2559715206
            self.device.command(0xDA, 0x12)  # Use alternate COM pin configuration
            self.device._colstart += 4
            self.device._colend += 4

            self.composition = ImageComposition(self.device)
            status_image = Image.new("1", (self.device.width, 10))
            content_image = Image.new("1", (self.device.width, 22))
            self.status_layer = ComposableImage(status_image, position=(0, 0))
            self.content_layer = ComposableImage(content_image, position=(0, 10))
            self.composition.add_image(self.status_layer)
            self.composition.add_image(self.content_layer)
            self.logger.info(f"Initialized OLED display on SPI port {spi_port}, device {spi_device}")
            self.logger.info(f"Using PIL/Pillow version: {PIL.__version__}")

        except Exception as e:
            self.logger.error(f"Failed to initialize OLED display: {e}")
            raise

        try:
            font_dir = path.join(path.dirname(path.abspath(__file__)), "fonts")
            self.icon_font = ImageFont.truetype(path.join(font_dir, "fa-solid-900.ttf"), 8)
            self.status_font = ImageFont.truetype(path.join(font_dir, "Dot Matrix Regular.ttf"), 9)
            self.text_font = ImageFont.truetype(path.join(font_dir, "Dot Matrix Regular.ttf"), 10)
            self.scroll_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 19)
            self.logger.info("Loaded display fonts")

        except Exception as e:
            self.logger.error(f"Failed to load fonts: {e}", exc_info=True)
            raise

        self.current_mode = self.MODE_DEFAULT
        self.current_message = ""
        self.temp_message = None
        self.original_message = None
        self.temp_timer = None
        self.mode_timer = None
        self.line1 = ""
        self.line2 = ""
        self.last_motion_time = None
        self.motion_active = False
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        self.last_minute = -1
        self.status_update_needed = True
        self.content_update_needed = True

        # Scroll performance: cached message width
        self._cached_msg_width = 0
        self._last_rendered_scroll_pos = -1

        # Burn-in prevention state
        self._last_burn_in_refresh = time.monotonic()
        self._refresh_state = None
        self._refresh_frame = 0
        self._burn_in_cycle_count = 0
        self._status_y_offset = 0
        self._old_status_image = None
        self._new_status_image = None

    def set_mode(self, mode, line1="", line2="", duration=None):
        """Set the display mode and content.

        Args:
            mode (str): Display mode.
            line1 (str): First line for centered mode.
            line2 (str): Second line for centered mode.
            duration (float): Duration before reverting to default mode.
        """
        if mode not in [self.MODE_DEFAULT, self.MODE_CENTERED]:
            raise ValueError(f"Invalid mode: {mode}")

        with self._state_lock:
            self._cancel_temp_message()

            if self.current_mode != mode:
                self._clear_display()

            self.current_mode = mode

            if mode == self.MODE_CENTERED:
                self.line1 = line1
                self.line2 = line2
                self.scroll_position = 0
                self.scroll_start_time = None

                if duration:
                    if self.mode_timer:
                        self.mode_timer.cancel()

                    self.mode_timer = Timer(duration, self._revert_to_default)
                    self.mode_timer.start()

            self.status_update_needed = True
            self.content_update_needed = True

    def set_scrolling_message(self, message):
        """Set the scrolling message for default mode.

        Args:
            message (str): Message to scroll.
        """
        with self._state_lock:
            if self.current_mode != self.MODE_DEFAULT:
                return

            if len(message) > self.MAX_SCROLL_MESSAGE_LENGTH:
                self.logger.warning(f"Message truncated from {len(message)} to {self.MAX_SCROLL_MESSAGE_LENGTH} chars")
                message = message[: self.MAX_SCROLL_MESSAGE_LENGTH - 1] + "…"

            self.current_message = message
            self._cached_msg_width = self.scroll_font.getlength(message) if message else 0
            self.scroll_position = 0
            self.scroll_start_time = None
            self.scroll_paused = False
            self._last_rendered_scroll_pos = -1
            self.content_update_needed = True

    def set_temporary_message(self, message, duration=None):
        """Set a temporary scrolling message with auto-revert.

        Args:
            message (str): Temporary message to display.
            duration (float): Duration before reverting.
        """
        with self._state_lock:
            if self.current_mode != self.MODE_DEFAULT:
                return

            if len(message) > self.MAX_SCROLL_MESSAGE_LENGTH:
                self.logger.warning(
                    f"Temp message truncated from {len(message)} to {self.MAX_SCROLL_MESSAGE_LENGTH} chars"
                )
                message = message[: self.MAX_SCROLL_MESSAGE_LENGTH - 1] + "…"

            if not self.temp_message:
                self.original_message = self.current_message

            self.temp_message = message
            self.current_message = message
            self._cached_msg_width = self.scroll_font.getlength(message) if message else 0
            self.scroll_position = 0
            self.scroll_start_time = None
            self.scroll_paused = False
            self._last_rendered_scroll_pos = -1
            self.content_update_needed = True

            self._cancel_temp_message()

            if duration:
                self.temp_timer = Timer(duration, self._restore_original_message)
                self.temp_timer.start()

    def clear_temporary_message(self):
        """Clear the temporary scrolling message."""
        with self._state_lock:
            if self.current_mode != self.MODE_DEFAULT:
                return

            self._cancel_temp_message()
            self._restore_original_message()

    def update_motion_status(self, active=None, last_time=None):
        """Update motion detection status.

        Args:
            active (bool): Current motion state.
            last_time (datetime): Time of last detected motion.
        """
        with self._state_lock:
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
        with self._state_lock:
            # Handle burn-in refresh animation (runs independently of normal updates)
            if self._refresh_state is not None:
                self._animate_refresh()
                return

            # Check if burn-in refresh is due
            now = time.monotonic()
            if now - self._last_burn_in_refresh >= self.BURN_IN_REFRESH_INTERVAL:
                self._start_burn_in_refresh()
                return

            current_time = datetime.now()
            if self.current_mode == self.MODE_DEFAULT and current_time.minute != self.last_minute:
                self.status_update_needed = True
                self.last_minute = current_time.minute

            should_update_status = self.status_update_needed
            should_update_content = self.content_update_needed
            mode = self.current_mode
            has_message = bool(self.current_message)

            # Snapshot state for rendering outside the lock
            snap = self._snapshot_render_state() if (should_update_status or should_update_content) else None

        if should_update_status:
            self._update_status_bar(snap)
        if should_update_content:
            self._update_content_area(snap)
        if mode == self.MODE_DEFAULT and has_message:
            self._update_scroll_state()

    def _snapshot_render_state(self):
        """Capture a snapshot of all state needed for rendering.
        Must be called with _state_lock held.
        """
        return {
            "mode": self.current_mode,
            "message": self.current_message,
            "msg_width": self._cached_msg_width,
            "scroll_position": self.scroll_position,
            "scroll_paused": self.scroll_paused,
            "line1": self.line1,
            "line2": self.line2,
            "motion_active": self.motion_active,
            "last_motion_time": self.last_motion_time,
            "status_y_offset": self._status_y_offset,
        }

    def _clear_display(self):
        """Clear the OLED display."""
        with canvas(self.device) as draw:
            draw.rectangle((0, 0, self.device.width - 1, self.device.height - 1), outline=0, fill=0)

    def _render_status_content_image(self, snap=None):
        """Render status bar content (clock, divider, motion) without the horizontal separator.

        Args:
            snap (dict): Optional state snapshot. If None, reads live state (must hold lock).
        """
        status_image = Image.new("1", (self.device.width, 10))
        draw = ImageDraw.Draw(status_image)
        y_off = snap["status_y_offset"] if snap else self._status_y_offset
        current_time = datetime.now().strftime("%a %m/%d %-I:%M%p")
        icon_width = self.icon_font.getlength(self.ICON_CLOCK)
        draw.text((0, y_off), self.ICON_CLOCK, font=self.icon_font, fill="white")
        draw.text((icon_width + 2, y_off), current_time, font=self.status_font, fill="white")
        sep_x = int(self.device.width * 0.75)
        draw.line([(sep_x, y_off), (sep_x, 8 + y_off)], fill="white", width=1)
        motion_text = self._format_motion_time(snap)
        motion_icon_width = self.icon_font.getlength(self.ICON_WALKING)
        motion_text_width = self.status_font.getlength(motion_text)
        motion_x = self.device.width - (motion_icon_width + 2 + motion_text_width)
        draw.text((motion_x, y_off), self.ICON_WALKING, font=self.icon_font, fill="white")
        draw.text((motion_x + motion_icon_width + 2, y_off), motion_text, font=self.status_font, fill="white")
        return status_image

    def _flush_composition(self):
        """Validate layers and send the current composition to the device."""
        for layer in [self.status_layer, self.content_layer]:
            if hasattr(layer, "image") and layer.image is not None:
                if not isinstance(layer.image, Image.Image):
                    layer.image = Image.new("1", (self.device.width, layer.height), 0)
            else:
                self.logger.warning(f"Missing image in layer: {layer}")
                layer.image = Image.new("1", (self.device.width, layer.height), 0)
        with canvas(self.device, background=self.composition()) as draw:
            self.composition.refresh()

    def _update_status_bar(self, snap=None):
        """Update the status bar section."""
        try:
            status_image = self._render_status_content_image(snap)
            draw = ImageDraw.Draw(status_image)
            draw.line([(0, 9), (self.device.width - 1, 9)], fill="white", width=1)
            self.status_layer.image = status_image
            self._flush_composition()
            self.status_update_needed = False
        except Exception as e:
            self.logger.error(f"Error updating status bar: {e}", exc_info=True)

    def _update_content_area(self, snap=None):
        """Update the main content area."""
        try:
            content_image = Image.new("1", (self.device.width, 22))
            draw = ImageDraw.Draw(content_image)
            mode = snap["mode"] if snap else self.current_mode
            message = snap["message"] if snap else self.current_message
            if mode == self.MODE_CENTERED:
                line1 = snap["line1"] if snap else self.line1
                line2 = snap["line2"] if snap else self.line2
                self._draw_centered_text(draw, line1, line2)
            elif mode == self.MODE_DEFAULT and message:
                msg_width = snap["msg_width"] if snap else self._cached_msg_width
                scroll_pos = snap["scroll_position"] if snap else self.scroll_position
                scroll_paused = snap["scroll_paused"] if snap else self.scroll_paused
                self._draw_scrolling_text(draw, message, msg_width, scroll_pos, scroll_paused)
            self.content_layer.image = content_image
            self._flush_composition()
            self.content_update_needed = False
        except Exception as e:
            self.logger.error(f"Error updating content area: {e}")

    def _draw_centered_text(self, draw, line1=None, line2=None):
        """Draw centered text lines."""
        if line1 is None:
            line1 = self.line1
        if line2 is None:
            line2 = self.line2
        if line1:
            line1 = self._truncate_text(line1, self.device.width, draw)
            x1, y1 = self._center_text(line1, draw, 12, 0)
            draw.text((x1, y1), line1, font=self.text_font, fill="white")
        if line2:
            line2 = self._truncate_text(line2, self.device.width, draw)
            x2, y2 = self._center_text(line2, draw, 12, 12)
            draw.text((x2, y2), line2, font=self.text_font, fill="white")

    def _draw_scrolling_text(self, draw, message=None, msg_width=None, scroll_pos=None, paused=None):
        """Draw scrolling text using snapshot values."""
        if message is None:
            message = self.current_message
        if not message:
            return
        if msg_width is None:
            msg_width = self._cached_msg_width
        if scroll_pos is None:
            scroll_pos = self.scroll_position
        if paused is None:
            paused = self.scroll_paused
        if msg_width <= self.device.width:
            x_pos = (self.device.width - msg_width) // 2
        elif paused:
            # Show text at starting position during pause
            x_pos = self.device.width
        else:
            x_pos = self.device.width - scroll_pos
        draw.text((x_pos, 0), message, font=self.scroll_font, fill="white")

    def _update_scroll_state(self):
        """Update scrolling text state using time-based positioning."""
        with self._state_lock:
            if self.current_mode == self.MODE_CENTERED or not self.current_message:
                return
            current_time = time.monotonic()
            if self.scroll_start_time is None:
                self.scroll_start_time = current_time
                return
            msg_width = self._cached_msg_width
            if msg_width <= self.device.width:
                return
            if self.scroll_paused:
                if current_time - self.scroll_start_time >= 2.0:
                    self.scroll_paused = False
                    self.scroll_position = 0
                    self.scroll_start_time = current_time
                    self._last_rendered_scroll_pos = -1
                    self.content_update_needed = True
            else:
                elapsed = current_time - self.scroll_start_time
                new_position = int(elapsed * self.SCROLL_SPEED_PPS)
                if new_position >= msg_width + self.device.width:
                    self.scroll_paused = True
                    self.scroll_start_time = current_time
                elif new_position != self._last_rendered_scroll_pos:
                    self.scroll_position = new_position
                    self._last_rendered_scroll_pos = new_position
                    self.content_update_needed = True

    def _truncate_text(self, text, max_width, draw):
        """Truncate text to fit width, adding ellipsis if needed.

        Args:
            text (str): Text to truncate.
            max_width (int): Maximum width for the text.
            draw (ImageDraw): Drawing context.
        """
        if self.text_font.getlength(text) <= max_width:
            return text
        while len(text) > 3 and self.text_font.getlength(text[:-3] + "...") > max_width:
            text = text[:-4]
        return text + "..."

    def _center_text(self, text, draw, height, y_offset):
        """Calculate position to center text.

        Args:
            text (str): Text to center.
            draw (ImageDraw): Drawing context.
            height (int): Height of the text area.
            y_offset (int): Vertical offset.
        """
        text_width = self.text_font.getlength(text)
        bbox = self.text_font.getbbox(text)
        text_height = bbox[3] - bbox[1]
        x = (self.device.width - text_width) // 2
        y = y_offset + (height - text_height) // 2
        return x, y

    def _format_motion_time(self, snap=None):
        """Format time since last motion."""
        motion_active = snap["motion_active"] if snap else self.motion_active
        last_motion_time = snap["last_motion_time"] if snap else self.last_motion_time
        if motion_active:
            return "now"
        if last_motion_time is None:
            return "--"
        delta = datetime.now(UTC) - last_motion_time
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m"
        return f"{minutes // 60}h"

    def _restore_original_message(self):
        """Restore the original message after temporary message expires."""
        with self._state_lock:
            if self.original_message is not None:
                self.current_message = self.original_message
                self._cached_msg_width = self.scroll_font.getlength(self.current_message) if self.current_message else 0
                self.scroll_position = 0
                self.scroll_start_time = None
                self.scroll_paused = False
                self._last_rendered_scroll_pos = -1
                self.content_update_needed = True
            self.temp_message = None
            self.temp_timer = None

    def _revert_to_default(self):
        """Revert to default mode."""
        with self._state_lock:
            if self.mode_timer:
                self.mode_timer.cancel()
                self.mode_timer = None
        self.set_mode(self.MODE_DEFAULT)

    def _cancel_temp_message(self):
        """Cancel any active temporary message timer."""
        if self.temp_timer:
            self.temp_timer.cancel()
            self.temp_timer = None

    def _start_burn_in_refresh(self):
        """Begin the burn-in prevention refresh animation.
        Must be called with _state_lock held.
        """
        self.logger.debug("Starting burn-in refresh animation")
        if self.status_layer.image and isinstance(self.status_layer.image, Image.Image):
            self._old_status_image = self.status_layer.image.copy()
        else:
            self._old_status_image = Image.new("1", (self.device.width, 10))
        self._new_status_image = None
        self._refresh_state = "wiping_up"
        self._refresh_frame = 0

    def _animate_refresh(self):
        """Advance the burn-in refresh animation by one frame.
        Must be called with _state_lock held.

        The horizontal separator line acts as a wiper:
          wiping_up:  line slides from y=9 to y=0, erasing status content below it
          blank:      brief all-black pause; toggle pixel jitter offset
          wiping_down: line slides from y=0 to y=9, revealing new status content above it
        """
        try:
            if self._refresh_state == "wiping_up":
                separator_y = 9 - self._refresh_frame
                self._draw_wiper_frame(self._old_status_image, separator_y)
                self._refresh_frame += 1
                if self._refresh_frame >= self.BURN_IN_SLIDE_FRAMES:
                    self._refresh_state = "blank"
                    self._refresh_frame = 0

            elif self._refresh_state == "blank":
                blank = Image.new("1", (self.device.width, 10))
                self.status_layer.image = blank
                self._flush_composition()
                self._refresh_frame += 1
                if self._refresh_frame >= self.BURN_IN_BLANK_FRAMES:
                    self._refresh_state = "wiping_down"
                    self._refresh_frame = 0
                    # Toggle Y offset for pixel jitter between refresh cycles
                    self._burn_in_cycle_count += 1
                    self._status_y_offset = self._burn_in_cycle_count % 2
                    # Pre-render new status content with updated offset
                    self._new_status_image = self._render_status_content_image()

            elif self._refresh_state == "wiping_down":
                separator_y = self._refresh_frame
                self._draw_wiper_frame(self._new_status_image, separator_y)
                self._refresh_frame += 1
                if self._refresh_frame >= self.BURN_IN_SLIDE_FRAMES:
                    self._refresh_state = None
                    self._refresh_frame = 0
                    self._last_burn_in_refresh = time.monotonic()
                    self.status_update_needed = True
                    self.content_update_needed = True
                    self._last_rendered_scroll_pos = -1
                    self._old_status_image = None
                    self._new_status_image = None
                    self.logger.debug("Burn-in refresh animation complete")

        except Exception as e:
            self.logger.error(f"Error during burn-in refresh animation: {e}", exc_info=True)
            self._refresh_state = None
            self._last_burn_in_refresh = time.monotonic()
            self._old_status_image = None
            self._new_status_image = None

    def _draw_wiper_frame(self, content_image, separator_y):
        """Draw a wiper animation frame: content visible above separator, black below."""
        status_image = Image.new("1", (self.device.width, 10))
        draw = ImageDraw.Draw(status_image)
        if separator_y > 0 and content_image:
            region = content_image.crop((0, 0, self.device.width, separator_y))
            status_image.paste(region, (0, 0))
        draw.line([(0, separator_y), (self.device.width - 1, separator_y)], fill="white", width=1)
        self.status_layer.image = status_image
        self._flush_composition()

    def cleanup(self):
        """Clean up resources."""
        self._cancel_temp_message()
