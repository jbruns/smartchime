import vlc
import time
import logging
from pathlib import Path
from vcgencmd import Vcgencmd

class HDMIManager:
    def __init__(self, framebuffer):
        """Initialize HDMI display manager."""
        self.logger = logging.getLogger(__name__)
        self.framebuffer = framebuffer
        self.player = None
        self.is_display_on = False
        self.vcgencmd = Vcgencmd()
        self.logger.info(f"Initialized HDMI manager with framebuffer: {framebuffer}")
        
    def turn_on_display(self):
        """Enable the HDMI display using vcgencmd."""
        if not self.is_display_on:
            try:
                self.vcgencmd.display_power(1)
                self.is_display_on = True
                time.sleep(1)  # Wait for display to initialize
                self.logger.info("HDMI display enabled")
            except Exception as e:
                self.logger.error(f"Failed to enable HDMI display: {e}")
            
    def turn_off_display(self):
        """Disable the HDMI display."""
        if self.is_display_on:
            if self.player:
                self.stop_video()
            try:
                self.vcgencmd.display_power(0)
                self.logger.info("HDMI display disabled")
            except Exception as e:
                self.logger.error(f"Failed to disable HDMI display: {e}")
            self.is_display_on = False
            
    def play_video(self, url):
        """Play a video stream on the HDMI display."""
        self.logger.info(f"Attempting to play video from: {url}")
        self.turn_on_display()
        
        if self.player:
            self.stop_video()
            
        try:
            instance = vlc.Instance()
            self.player = instance.media_player_new()
            media = instance.media_new(url)
            self.player.set_media(media)
            
            # Configure VLC for framebuffer output
            self.player.set_mrl("--vout=fb")
            self.player.set_options(f"--fb-device={self.framebuffer}")
                
            self.player.play()
            time.sleep(1)  # Give VLC a moment to start
            
            if self.player.get_state() == vlc.State.Error:
                self.logger.warning(f"Failed to play video stream: {url}")
                self.turn_off_display()
            else:
                self.logger.info("Video playback started successfully")
                
        except Exception as e:
            self.logger.warning(f"Error setting up video playback: {e}")
            self.turn_off_display()
        
    def stop_video(self):
        """Stop the currently playing video."""
        if self.player:
            self.player.stop()
            self.player = None
            self.logger.info("Video playback stopped")