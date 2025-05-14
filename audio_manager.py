import os
import alsaaudio
import threading
import time
import logging
from pathlib import Path

class AudioManager:
    def __init__(self, audio_dir, mixer_device='Digital', mixer_control='PCM', oled_manager=None):
        """Initialize the audio manager with ALSA mixer and sound directory."""
        self.logger = logging.getLogger(__name__)
        self.audio_dir = Path(audio_dir)
        self.oled_manager = oled_manager
        self.volume_display_thread = None
        self.previous_message = ""
        
        # Initialize ALSA mixer
        try:
            self.mixer = alsaaudio.Mixer(control=mixer_control, device=mixer_device)
            self.current_volume = self.mixer.getvolume()[0]
            self.logger.info(f"Initialized audio mixer: {mixer_device}:{mixer_control}")
        except alsaaudio.ALSAAudioError as e:
            self.logger.warning(f"Could not open mixer {mixer_device}:{mixer_control}, falling back to default: {e}")
            try:
                self.mixer = alsaaudio.Mixer()
                self.current_volume = self.mixer.getvolume()[0]
            except alsaaudio.ALSAAudioError as e:
                self.logger.error(f"Failed to initialize any audio mixer: {e}")
                raise
        
        if not self.audio_dir.exists():
            self.logger.warning(f"Audio directory does not exist: {self.audio_dir}")
        
        self.is_muted = False
        self._set_volume(self.current_volume)
        
    def play_sound(self, filename):
        """Play a WAV file using aplay."""
        if self.is_muted:
            self.logger.info(f"Not playing sound {filename}: audio is muted")
            return
        
        file_path = self.audio_dir / filename
        if not file_path.exists():
            self.logger.warning(f"Sound file not found: {file_path}")
            return
            
        self.logger.info(f"Playing sound: {filename}")
        try:
            exit_code = os.system(f"aplay {str(file_path)}")
            if exit_code != 0:
                self.logger.warning(f"aplay failed with exit code {exit_code} for file: {filename}")
        except Exception as e:
            self.logger.error(f"Failed to play sound {filename}: {e}")
            
    def _display_volume_temporarily(self, message):
        """Show volume information on the OLED display."""
        if not self.oled_manager:
            return
        self.oled_manager.show_centered_text("Volume Control", message, duration=5.0)
            
    def adjust_volume(self, delta):
        """Adjust the system volume by a relative amount."""
        if self.is_muted:
            self.logger.info("Volume adjustment ignored: audio is muted")
            return
            
        old_volume = self.current_volume
        new_volume = max(0, min(100, self.current_volume + int(delta * 100)))
        self._set_volume(new_volume)
        self._display_volume_temporarily(f"Volume: {self.current_volume}%")
        self.logger.info(f"Volume adjusted: {old_volume}% -> {new_volume}%")
        
    def toggle_mute(self):
        """Toggle the audio mute state."""
        self.is_muted = not self.is_muted
        try:
            if self.is_muted:
                self.mixer.setmute(1)
                self._display_volume_temporarily("Volume: Muted")
                self.logger.info("Audio muted")
            else:
                self.mixer.setmute(0)
                self._display_volume_temporarily(f"Volume: {self.current_volume}%")
                self.logger.info("Audio unmuted")
        except alsaaudio.ALSAAudioError as e:
            self.logger.error(f"Failed to {('mute' if self.is_muted else 'unmute')} audio: {e}")
        
    def _set_volume(self, volume):
        """Set the system volume to a specific level."""
        try:
            self.current_volume = volume
            self.mixer.setvolume(volume)
            self.logger.debug(f"Volume set to {volume}%")
        except alsaaudio.ALSAAudioError as e:
            self.logger.error(f"Failed to set volume to {volume}%: {e}")
        
    def get_available_sounds(self):
        """Get a list of WAV files in the audio directory."""
        sounds = [f.name for f in self.audio_dir.glob("*.wav")]
        self.logger.debug(f"Found {len(sounds)} sound files")
        return sounds
        
    def cleanup(self):
        """Clean up resources."""
        if self.volume_display_thread and self.volume_display_thread.is_alive():
            self.volume_display_thread.cancel()
            self.logger.debug("Cleaned up volume display thread")