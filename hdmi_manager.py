import vlc
import time
import logging
from vcgencmd import Vcgencmd

class HDMIManager:
    def __init__(self):
        """Initialize HDMI display manager."""
        self.logger = logging.getLogger(__name__)
        self.player = None
        self.vcgencmd = Vcgencmd()
        self.logger.info(f"Initialized HDMI manager")

        self._set_display_power("off")
        
    def _set_display_power(self, state):
        try:
            if state == 'off':
                self.vcgencmd.display_power_off(2)
            elif state == 'on':
                self.vcgencmd.display_power_on(2)
            
            self.logger.info(f"HDMI display powered {state}")
            
        except Exception as e:
            self.logger.error(f"Failed to power {state} HDMI display: {e}")

    def get_display_power_state(self):
        return self.vcgencmd.display_power_state(2)
    
    def play_video(self, url):
        """Play a video stream on the HDMI display."""
        self.logger.info(f"Attempting to play video from: {url}")
        
        if self.player:
            self.player.stop()
            
        try:
            instance = vlc.Instance("--vout fb --aout dummy --no-audio --no-fb-tty --video-filter=rotate --rotate-angle=270.0")
            self.player = instance.media_player_new()
            self.player.set_mrl(url)
            self.player.play()
            time.sleep(3)  # Give VLC a moment to start
            
            self._set_display_power("on")

            if self.player.get_state() == vlc.State.Error:
                self.logger.warning(f"Failed to play video stream: {url}")
                self._set_display_power("off")
            else:
                self.logger.info("Video playback started successfully")
                
        except Exception as e:
            self.logger.warning(f"Error setting up video playback: {e}")
            self._set_display_power("off")
        
    def stop_video(self):
        """Stop the currently playing video."""
        if self.player:
            self.player.stop()
            self.player = None
            self.logger.info("Video playback stopped")
            self._set_display_power("off")