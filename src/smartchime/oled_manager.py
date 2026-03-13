import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from os import path
from threading import RLock, Timer

import PIL
from luma.core.image_composition import ComposableImage, ImageComposition
from luma.core.interface.serial import spi
from luma.oled.device import ssd1305
from PIL import Image, ImageDraw, ImageFont


@dataclass
class V2Item:
    """A single line2 rotation item."""

    key: str
    text: str
    priority: int


@dataclass
class V2State:
    """Parsed v2 contract state snapshot."""

    active: bool
    contrast: int  # 0–255 (converted from 0.0–1.0 on parse)
    line1_modes: set  # subset of {"clock", "motion"}
    motion_active: bool
    motion_timestamp: datetime | None
    line2_mode: str
    rotate_seconds: float
    items: list[V2Item] = field(default_factory=list)  # sorted by priority desc
    override_active: bool = False
    override_text: str = ""
    override_expires_at: datetime | None = None
    # Internal rotation tracking
    current_item_index: int = 0
    last_rotation_time: float = 0.0  # time.monotonic()


class OLEDManager:
    ICON_CLOCK = "\uf017"
    ICON_WALKING = "\uf554"
    LAYER_STATUS = "status"
    LAYER_CONTENT = "content"
    MODE_DEFAULT = "default"
    MODE_CENTERED = "centered_2line"
    MODE_VOLUME = "volume"
    ICON_SPEAKER = "\uf028"
    ICON_SPEAKER_MUTE = "\uf6a9"

    SCROLL_SPEED_PPS = 45
    MAX_SCROLL_MESSAGE_LENGTH = 500
    BURN_IN_REFRESH_INTERVAL = 300
    BURN_IN_SLIDE_FRAMES = 10
    BURN_IN_BLANK_FRAMES = 4
    FALLBACK_LINE1 = "No OLED state"
    FALLBACK_LINE2 = "Awaiting MQTT..."
    V2_STATE_FALLBACK_GRACE_SECONDS = 5.0

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
            self.device = ssd1305(serial)

            ### ssd1305 was added in luma.oled 3.15.0 - this was the previous workaround we used
            ## We're actually using an ssd1305-based display, so we need to accomodate the differences.
            ## https://github.com/rm-hull/luma.oled/issues/309#issuecomment-2559715206
            # self.device.command(0xDA, 0x12)  # Use alternate COM pin configuration
            # self.device._colstart += 4
            # self.device._colend += 4
            ###

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
        self.volume_level = 0.0
        self.volume_muted = False
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        self.last_minute = -1
        self.status_update_needed = True
        self.content_update_needed = True

        # Scroll performance: cached message width
        self._cached_msg_width = 0

        # v2 contract state (None = no state received yet)
        self._v2_state: V2State | None = None
        self._v2_state_transport_ready = False
        self._v2_state_wait_started_at: float | None = None
        self._fallback_warning_shown = False
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
        if mode not in [self.MODE_DEFAULT, self.MODE_CENTERED, self.MODE_VOLUME]:
            raise ValueError(f"Invalid mode: {mode}")

        with self._state_lock:
            self._cancel_temp_message()

            self.current_mode = mode

            if mode == self.MODE_CENTERED:
                self.line1 = line1
                self.line2 = line2
                self._reset_scroll_state()

                if duration:
                    if self.mode_timer:
                        self.mode_timer.cancel()

                    self.mode_timer = Timer(duration, self._revert_to_default)
                    self.mode_timer.start()

            self.status_update_needed = True
            self.content_update_needed = True

    def set_volume_display(self, level, muted=False, duration=None):
        """Set the display to show a volume bar.

        Args:
            level (float): Volume level from 0.0 to 1.0.
            muted (bool): Whether audio is muted.
            duration (float): Duration before reverting to default mode.
        """
        with self._state_lock:
            self._cancel_temp_message()

            self.current_mode = self.MODE_VOLUME
            self.volume_level = max(0.0, min(1.0, level))
            self.volume_muted = muted

            if duration:
                if self.mode_timer:
                    self.mode_timer.cancel()

                self.mode_timer = Timer(duration, self._revert_to_default)
                self.mode_timer.start()

            self.status_update_needed = True
            self.content_update_needed = True

    def set_v2_state_transport_ready(self, ready):
        """Track whether MQTT is currently ready to deliver v2 OLED state."""
        with self._state_lock:
            if self._v2_state_transport_ready == ready:
                return

            self._v2_state_transport_ready = ready

            if ready:
                self._v2_state_wait_started_at = None if self._v2_state is not None else time.monotonic()
                if self._v2_state_wait_started_at is not None:
                    self.logger.debug("MQTT ready for v2 OLED state; starting fallback grace period")
                return

            self._v2_state_wait_started_at = None
            self._clear_fallback_warning_locked()

    def _should_show_v2_fallback(self, now):
        """Return True when missing v2 state should be treated as a warning."""
        return (
            self._v2_state is None
            and self.current_mode == self.MODE_DEFAULT
            and self._v2_state_transport_ready
            and self._v2_state_wait_started_at is not None
            and now - self._v2_state_wait_started_at >= self.V2_STATE_FALLBACK_GRACE_SECONDS
        )

    def _clear_fallback_warning_locked(self):
        """Clear the missing-v2 fallback warning state.

        Must be called with _state_lock held.
        """
        self._fallback_warning_shown = False
        if (
            self.current_mode == self.MODE_CENTERED
            and self.mode_timer is None
            and self.line1 == self.FALLBACK_LINE1
            and self.line2 == self.FALLBACK_LINE2
        ):
            self.current_mode = self.MODE_DEFAULT
            self.line1 = ""
            self.line2 = ""
            self.status_update_needed = True
            self.content_update_needed = True

    def apply_v2_state(self, payload):
        """Apply a v2 contract state snapshot from MQTT.

        Validates the payload, parses all fields, and replaces the current v2 state.
        If the display is in an overlay mode (volume, centered), the v2 state is stored
        and will be applied when the overlay reverts to default.

        On validation failure, shows an error on the OLED and re-raises.

        Args:
            payload (dict): The v2 contract JSON payload.

        Raises:
            ValueError: If the payload is invalid or missing required fields.
        """
        try:
            parsed = self._parse_v2_payload(payload)
        except ValueError:
            self.logger.error("Invalid v2 OLED payload — displaying error on OLED")
            with self._state_lock:
                self.set_mode(self.MODE_CENTERED, "OLED state error", "Bad MQTT payload")
            raise

        with self._state_lock:
            old_state = self._v2_state
            items_changed = old_state is None or [i.key for i in old_state.items] != [i.key for i in parsed.items]

            if items_changed:
                parsed.current_item_index = 0
                parsed.last_rotation_time = time.monotonic()
            else:
                parsed.current_item_index = old_state.current_item_index
                parsed.last_rotation_time = old_state.last_rotation_time

            self._v2_state = parsed
            self._v2_state_wait_started_at = None
            self._clear_fallback_warning_locked()

            # Apply device-level controls
            try:
                self.device.contrast(parsed.contrast)
            except Exception as e:
                self.logger.error(f"Failed to set contrast: {e}")

            try:
                if parsed.active:
                    self.device.show()
                else:
                    self.device.hide()
            except Exception as e:
                self.logger.error(f"Failed to set display active state: {e}")

            # Switch to v2-driven content
            # If display is showing the fallback warning (centered without a timer),
            # force back to default mode. Otherwise, preserve active overlays.
            if self.current_mode == self.MODE_CENTERED and self.mode_timer is None:
                self.current_mode = self.MODE_DEFAULT
            if self.current_mode == self.MODE_DEFAULT:
                self._apply_v2_content()

            self.status_update_needed = True
            self.content_update_needed = True

        self.logger.info(
            f"Applied v2 state: active={parsed.active}, line1={parsed.line1_modes}, "
            f"items={len(parsed.items)}, override={parsed.override_active}"
        )

    def _parse_v2_payload(self, payload):
        """Parse and validate a v2 contract payload.

        Args:
            payload (dict): Raw JSON payload.

        Returns:
            V2State: Parsed state object.

        Raises:
            ValueError: If validation fails.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"Expected dict payload, got {type(payload).__name__}")

        version = payload.get("version")
        if version != 2:
            raise ValueError(f"Unsupported contract version: {version}")

        # Required top-level fields
        for field_name in ("active", "contrast", "line1", "line2", "override"):
            if field_name not in payload:
                raise ValueError(f"Missing required field: {field_name}")

        active = bool(payload["active"])

        contrast_raw = payload["contrast"]
        if not isinstance(contrast_raw, (int, float)) or not (0.0 <= contrast_raw <= 1.0):
            raise ValueError(f"contrast must be a number 0.0–1.0, got {contrast_raw}")
        contrast = int(contrast_raw * 255)

        # line1
        line1 = payload["line1"]
        if not isinstance(line1, dict) or "mode" not in line1:
            raise ValueError("line1 must be a dict with 'mode' field")

        raw_modes = {m.strip() for m in line1["mode"].split(",") if m.strip()}
        valid_modes = {"clock", "motion"}
        if not raw_modes:
            raise ValueError("line1.mode must contain at least one mode")
        invalid = raw_modes - valid_modes
        if invalid:
            raise ValueError(f"Invalid line1 modes: {invalid}")
        line1_modes = raw_modes

        # line1.motion (optional, required if "motion" in modes)
        motion_active = False
        motion_timestamp = None
        if "motion" in line1_modes:
            motion_data = line1.get("motion", {})
            if not isinstance(motion_data, dict):
                raise ValueError("line1.motion must be a dict")
            motion_active = bool(motion_data.get("active", False))
            ts_raw = motion_data.get("timestamp")
            if ts_raw:
                try:
                    motion_timestamp = datetime.fromisoformat(ts_raw)
                    if motion_timestamp.tzinfo is None:
                        motion_timestamp = motion_timestamp.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    raise ValueError(f"Invalid motion timestamp: {ts_raw}") from None

        # line2
        line2 = payload["line2"]
        if not isinstance(line2, dict) or "mode" not in line2:
            raise ValueError("line2 must be a dict with 'mode' field")
        line2_mode = line2["mode"]
        if line2_mode != "rotate":
            raise ValueError(f"Unsupported line2 mode: {line2_mode}")

        rotate_seconds = line2.get("rotate_seconds", 10)
        if not isinstance(rotate_seconds, (int, float)) or rotate_seconds <= 0:
            raise ValueError(f"rotate_seconds must be a positive number, got {rotate_seconds}")

        raw_items = line2.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("line2.items must be a list")

        items = []
        seen_keys = set()
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError(f"Each line2 item must be a dict, got {type(item).__name__}")
            for req in ("key", "text", "priority"):
                if req not in item:
                    raise ValueError(f"line2 item missing required field: {req}")
            key = str(item["key"])
            if key in seen_keys:
                raise ValueError(f"Duplicate line2 item key: {key}")
            seen_keys.add(key)
            items.append(V2Item(key=key, text=str(item["text"]), priority=int(item["priority"])))

        # Sort by priority descending
        items.sort(key=lambda i: i.priority, reverse=True)

        # override
        override = payload["override"]
        if not isinstance(override, dict):
            raise ValueError("override must be a dict")

        override_active = bool(override.get("active", False))
        override_text = str(override.get("text", ""))
        override_expires_at = None
        expires_raw = override.get("expires_at")
        if expires_raw:
            try:
                override_expires_at = datetime.fromisoformat(expires_raw)
                if override_expires_at.tzinfo is None:
                    override_expires_at = override_expires_at.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid override expires_at: {expires_raw}") from None

        return V2State(
            active=active,
            contrast=contrast,
            line1_modes=line1_modes,
            motion_active=motion_active,
            motion_timestamp=motion_timestamp,
            line2_mode=line2_mode,
            rotate_seconds=rotate_seconds,
            items=items,
            override_active=override_active,
            override_text=override_text,
            override_expires_at=override_expires_at,
        )

    def _apply_v2_content(self):
        """Set the current scrolling message from v2 state.
        Must be called with _state_lock held.
        """
        v2 = self._v2_state
        if v2 is None:
            return

        if v2.override_active:
            text = v2.override_text
        elif v2.items:
            idx = v2.current_item_index % len(v2.items)
            text = v2.items[idx].text
        else:
            text = ""

        if len(text) > self.MAX_SCROLL_MESSAGE_LENGTH:
            text = text[: self.MAX_SCROLL_MESSAGE_LENGTH - 1] + "…"

        # Only reset scroll state when the message actually changes.
        # MQTT updates may re-apply the same v2 state frequently;
        # resetting scroll on every call causes visible scroll freezes.
        if text != self.current_message:
            self.current_message = text
            self._cached_msg_width = self.scroll_font.getlength(text) if text else 0
            self._reset_scroll_state()
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
            self._reset_scroll_state()
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

            # Fallback: no v2 state received after MQTT was ready — show warning
            if self._should_show_v2_fallback(now):
                if not self._fallback_warning_shown:
                    self.logger.warning("No v2 OLED state received — displaying fallback warning")
                    self._fallback_warning_shown = True
                    self.set_mode(self.MODE_CENTERED, self.FALLBACK_LINE1, self.FALLBACK_LINE2)
                return

            # v2 override expiry check
            v2 = self._v2_state
            if v2 and v2.override_active and v2.override_expires_at and datetime.now(UTC) >= v2.override_expires_at:
                self.logger.info("v2 override expired, reverting to rotation")
                self._v2_state.override_active = False
                if self.current_mode == self.MODE_DEFAULT:
                    self._apply_v2_content()

            # v2 rotation check
            if (
                self._v2_state
                and not self._v2_state.override_active
                and self._v2_state.items
                and len(self._v2_state.items) > 1
                and self.current_mode == self.MODE_DEFAULT
            ):
                elapsed = now - self._v2_state.last_rotation_time
                if elapsed >= self._v2_state.rotate_seconds:
                    self._v2_state.current_item_index = (self._v2_state.current_item_index + 1) % len(
                        self._v2_state.items
                    )
                    self._v2_state.last_rotation_time = now
                    item = self._v2_state.items[self._v2_state.current_item_index]
                    self.logger.debug(f"v2 rotation: now showing '{item.key}' (priority={item.priority})")
                    self._apply_v2_content()

            current_time = datetime.now()
            if self.current_mode == self.MODE_DEFAULT and current_time.minute != self.last_minute:
                self.status_update_needed = True
                self.last_minute = current_time.minute

            if self.status_update_needed:
                self._update_status_bar()
            if self.content_update_needed:
                self._update_content_area()
            if self.current_mode == self.MODE_DEFAULT and self.current_message:
                self._advance_scroll_position()

    def _reset_scroll_state(self):
        """Reset all scroll-related fields to initial state.
        Must be called with _state_lock held.
        """
        self.scroll_position = 0
        self.scroll_start_time = None
        self.scroll_paused = False
        self._last_rendered_scroll_pos = -1

    def _render_status_content_image(self):
        """Render status bar content based on v2 line1 modes.

        Falls back to clock+motion before the first v2 message is received.
        Must be called with _state_lock held.
        """
        status_image = Image.new("1", (self.device.width, 10))
        draw = ImageDraw.Draw(status_image)
        y_off = self._status_y_offset
        v2 = self._v2_state

        modes = v2.line1_modes if v2 is not None else {"clock", "motion"}

        show_clock = "clock" in modes
        show_motion = "motion" in modes

        if show_clock and show_motion:
            # Both: clock on left ~75%, divider, motion on right
            self._draw_clock_section(draw, y_off, max_x=int(self.device.width * 0.75))
            sep_x = int(self.device.width * 0.75)
            draw.line([(sep_x, y_off), (sep_x, 8 + y_off)], fill="white", width=1)
            self._draw_motion_section(draw, y_off)
        elif show_clock:
            # Clock only, full width
            self._draw_clock_section(draw, y_off, max_x=self.device.width)
        elif show_motion:
            # Motion only, full width (left-aligned)
            motion_text = self._format_motion_time()
            motion_icon_width = self.icon_font.getlength(self.ICON_WALKING)
            draw.text((0, y_off), self.ICON_WALKING, font=self.icon_font, fill="white")
            draw.text((motion_icon_width + 2, y_off), motion_text, font=self.status_font, fill="white")

        return status_image

    def _draw_clock_section(self, draw, y_off, max_x):
        """Draw the clock section of the status bar.

        Args:
            draw (ImageDraw): Drawing context.
            y_off (int): Vertical pixel offset for burn-in jitter.
            max_x (int): Maximum x coordinate for clock text.
        """
        current_time = datetime.now().strftime("%a %m/%d %-I:%M%p")
        icon_width = self.icon_font.getlength(self.ICON_CLOCK)
        draw.text((0, y_off), self.ICON_CLOCK, font=self.icon_font, fill="white")
        draw.text((icon_width + 2, y_off), current_time, font=self.status_font, fill="white")

    def _draw_motion_section(self, draw, y_off):
        """Draw the motion section of the status bar (right-aligned).

        Args:
            draw (ImageDraw): Drawing context.
            y_off (int): Vertical pixel offset for burn-in jitter.
        """
        motion_text = self._format_motion_time()
        motion_icon_width = self.icon_font.getlength(self.ICON_WALKING)
        motion_text_width = self.status_font.getlength(motion_text)
        motion_x = self.device.width - (motion_icon_width + 2 + motion_text_width)
        draw.text((motion_x, y_off), self.ICON_WALKING, font=self.icon_font, fill="white")
        draw.text((motion_x + motion_icon_width + 2, y_off), motion_text, font=self.status_font, fill="white")

    def _flush_composition(self):
        """Validate layers and send the current composition to the device."""
        for layer in [self.status_layer, self.content_layer]:
            if hasattr(layer, "image") and layer.image is not None:
                if not isinstance(layer.image, Image.Image):
                    layer.image = Image.new("1", (self.device.width, layer.height), 0)
            else:
                self.logger.warning(f"Missing image in layer: {layer}")
                layer.image = Image.new("1", (self.device.width, layer.height), 0)
        # Refresh first: luma's canvas copies the background image immediately,
        # so passing self.composition() before refresh displays the previous frame.
        self.composition.refresh()
        self.device.display(self.composition())

    def _update_status_bar(self):
        """Update the status bar section.
        Must be called with _state_lock held.
        """
        try:
            status_image = self._render_status_content_image()
            draw = ImageDraw.Draw(status_image)
            draw.line([(0, 9), (self.device.width - 1, 9)], fill="white", width=1)
            self.status_layer.image = status_image
            self._flush_composition()
            self.status_update_needed = False
        except Exception as e:
            self.logger.error(f"Error updating status bar: {e}", exc_info=True)

    def _update_content_area(self):
        """Update the main content area.
        Must be called with _state_lock held.
        """
        try:
            content_image = Image.new("1", (self.device.width, 22))
            draw = ImageDraw.Draw(content_image)
            if self.current_mode == self.MODE_CENTERED:
                self._draw_centered_text(draw, self.line1, self.line2)
            elif self.current_mode == self.MODE_VOLUME:
                self._draw_volume_bar(draw, self.volume_level, self.volume_muted)
            elif self.current_mode == self.MODE_DEFAULT and self.current_message:
                self._draw_scrolling_text(
                    draw, self.current_message, self._cached_msg_width, self.scroll_position, self.scroll_paused
                )
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

    def _draw_volume_bar(self, draw, level, muted):
        """Draw a volume bar with speaker icon.

        Args:
            draw (ImageDraw): Drawing context for the content area (128x22).
            level (float): Volume level from 0.0 to 1.0.
            muted (bool): Whether audio is muted.
        """
        # Speaker icon on the left, vertically centered
        icon = self.ICON_SPEAKER_MUTE if muted else self.ICON_SPEAKER
        icon_x = 2
        icon_bbox = self.icon_font.getbbox(icon)
        icon_h = icon_bbox[3] - icon_bbox[1]
        icon_y = (22 - icon_h) // 2
        draw.text((icon_x, icon_y), icon, font=self.icon_font, fill="white")

        # Bar track: outline rectangle
        bar_left = 18
        bar_right = 124
        bar_top = 5
        bar_bottom = 17
        draw.rectangle([bar_left, bar_top, bar_right, bar_bottom], outline="white", fill="black")

        if muted:
            # Diagonal strikethrough across the empty bar
            draw.line([bar_left, bar_bottom, bar_right, bar_top], fill="white", width=1)
            return

        # Filled portion inside the track
        inner_left = bar_left + 2
        inner_right = bar_right - 2
        inner_top = bar_top + 2
        inner_bottom = bar_bottom - 2
        fill_width = int(level * (inner_right - inner_left))
        if fill_width > 0:
            draw.rectangle([inner_left, inner_top, inner_left + fill_width, inner_bottom], fill="white")

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
            self._advance_scroll_position()

    def _advance_scroll_position(self):
        """Advance scroll position based on elapsed time.
        Must be called with _state_lock held.
        """
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

    def _format_motion_time(self):
        """Format time since last motion.
        Must be called with _state_lock held.
        """
        v2 = self._v2_state
        motion_active = v2.motion_active if v2 else False
        last_motion_time = v2.motion_timestamp if v2 else None
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
        """Restore display content after temporary message expires.

        If v2 state is active, restores the current v2 rotation item.
        Otherwise, restores the previously saved original message.
        """
        with self._state_lock:
            if self._v2_state is not None:
                self._apply_v2_content()
            elif self.original_message is not None:
                self.current_message = self.original_message
                self._cached_msg_width = self.scroll_font.getlength(self.current_message) if self.current_message else 0
                self._reset_scroll_state()
                self.content_update_needed = True
            self.temp_message = None
            self.temp_timer = None

    def _revert_to_default(self):
        """Revert to default mode, restoring v2 state if active."""
        with self._state_lock:
            if self.mode_timer:
                self.mode_timer.cancel()
                self.mode_timer = None

            self._cancel_temp_message()
            self.current_mode = self.MODE_DEFAULT

            if self._v2_state is not None:
                self._apply_v2_content()
                try:
                    self.device.contrast(self._v2_state.contrast)
                except Exception as e:
                    self.logger.error(f"Failed to restore v2 contrast: {e}")

            self.status_update_needed = True
            self.content_update_needed = True

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
