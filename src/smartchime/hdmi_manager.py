import logging
from threading import Event, Lock

import vlc
from vcgencmd import Vcgencmd


class HDMIManager:
    VLC_STARTUP_TIMEOUT = 5.0

    def __init__(self):
        """Initialize HDMI display manager."""
        self.logger = logging.getLogger(__name__)
        self.player = None
        self._vlc_instance = None
        self._playback_event = Event()
        self._player_lock = Lock()
        self.vcgencmd = Vcgencmd()
        self.logger.info("Initialized HDMI manager")

        self._set_display_power("off")

    def _get_vlc_instance(self):
        """Get or create the shared VLC instance."""
        if self._vlc_instance is None:
            vlc_opts = (
                "--quiet --no-audio --no-video-title --fullscreen"
                " --video-on-top --no-osd --vout=fb --no-fb-tty --no-xlib --aout=dummy"
            )
            self._vlc_instance = vlc.Instance(vlc_opts)
            self.logger.debug("Created VLC instance")
        return self._vlc_instance

    def _set_display_power(self, state):
        try:
            if state == "off":
                self.vcgencmd.display_power_off(2)
            elif state == "on":
                self.vcgencmd.display_power_on(2)

            self.logger.info(f"HDMI display powered {state}")

        except Exception as e:
            self.logger.error(f"Failed to power {state} HDMI display: {e}")

    def get_display_power_state(self):
        return self.vcgencmd.display_power_state(2)

    def _on_vlc_playing(self, event):
        """VLC callback: playback has started."""
        self.logger.debug("VLC event: MediaPlayerPlaying")
        self._playback_event.set()

    def _on_vlc_error(self, event):
        """VLC callback: playback encountered an error."""
        self.logger.warning("VLC event: MediaPlayerEncounteredError")
        self._playback_event.set()

    def _on_vlc_end_reached(self, event):
        """VLC callback: stream ended. Auto-cleanup."""
        self.logger.info("VLC event: MediaPlayerEndReached — stopping video")
        self.stop_video()

    def play_video(self, url):
        """Play a video stream on the HDMI display."""
        self.logger.info(f"Attempting to play video from: {url}")

        self.stop_video()

        with self._player_lock:
            try:
                instance = self._get_vlc_instance()
                self.player = instance.media_player_new()

                event_manager = self.player.event_manager()
                event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_vlc_playing)
                event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)
                event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_reached)

                self.player.set_mrl(url)
                self._playback_event.clear()
                self.player.play()

                self._set_display_power("on")

                started = self._playback_event.wait(timeout=self.VLC_STARTUP_TIMEOUT)

                if not started:
                    self.logger.warning(f"VLC startup timed out after {self.VLC_STARTUP_TIMEOUT}s for: {url}")
                elif self.player and self.player.get_state() == vlc.State.Error:
                    self.logger.warning(f"Failed to play video stream: {url}")
                else:
                    self.logger.info("Video playback started successfully")
                    return

            except Exception as e:
                self.logger.warning(f"Error setting up video playback: {e}")

        # If we fell through (timeout, error, exception), clean up
        self.stop_video()

    def stop_video(self):
        """Stop the currently playing video and release resources."""
        with self._player_lock:
            if self.player:
                try:
                    self.player.stop()
                except Exception as e:
                    self.logger.warning(f"Error stopping VLC player: {e}")
                try:
                    self.player.release()
                except Exception as e:
                    self.logger.warning(f"Error releasing VLC player: {e}")
                self.player = None
                self.logger.info("Video playback stopped")

        self._set_display_power("off")

    def cleanup(self):
        """Release all VLC resources."""
        self.stop_video()
        if self._vlc_instance:
            try:
                self._vlc_instance.release()
            except Exception as e:
                self.logger.warning(f"Error releasing VLC instance: {e}")
            self._vlc_instance = None
            self.logger.info("VLC instance released")
