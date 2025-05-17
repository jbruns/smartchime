import os
import alsaaudio
import logging
from pathlib import Path

class AudioManager:
    def __init__(self, audio_dir, mixer_device='0', mixer_control='Digital', oled_manager=None):
        """Initialize the audio manager with ALSA mixer and sound directory."""
        self.logger = logging.getLogger(__name__)
        self.audio_dir = Path(audio_dir)
        self.oled = oled_manager
        
        # Initialize ALSA mixer
        try:
            self.mixer = alsaaudio.Mixer(control=mixer_control, device=mixer_device)
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
                
    def play_sound(self, filename):
        """Play a WAV file using aplay."""
        if self.mixer.getmute()[0] == 1: # Muted
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
            
    def _display_volume(self):
        """Show volume information on the OLED display."""
        if not self.oled:
            return
        if self.is_muted:
            self.oled.set_mode("centered_2line", "Volume:", "MUTE", duration=5)
        else:
            self.oled.set_mode("centered_2line", "Volume:", f"{self.current_volume}%", duration=5)
                       
    def adjust_volume(self, delta):
        """Adjust the system volume by a relative amount."""
        if self.mixer.getmute()[0] == 1: # Muted
            self.logger.info("Volume adjustment ignored: audio is muted")
            self._display_volume()
            return
            
        old_volume = self.mixer.getvolume()[0]
        new_volume = max(0, min(100, old_volume + int(delta * 100)))
        self._set_volume(new_volume)
        self._display_volume()
        self.logger.info(f"Volume adjusted: {old_volume}% -> {new_volume}%")
        
    def toggle_mute(self):
        """Toggle the audio mute state."""
        try:
            if self.mixer.getmute()[0] == 1: # Muted
                self.mixer.setmute(0)
                self.logger.info("Audio unmuted")
            else: # Not muted
                self.mixer.setmute(1)
                self.logger.info("Audio muted")
            
            self._display_volume()
        
        except alsaaudio.ALSAAudioError as e:
            self.logger.error(f"Failed to {('mute' if self.is_muted else 'unmute')} audio: {e}")
        
    def _set_volume(self, volume):
        """Set the system volume to a specific level."""
        try:
            self.mixer.setvolume(volume)
            self.logger.debug(f"Volume set to {volume}%")
        
        except alsaaudio.ALSAAudioError as e:
            self.logger.error(f"Failed to set volume to {volume}%: {e}")
        
    def get_available_sounds(self):
        """Get a list of WAV files in the audio directory."""
        sounds = [f.name for f in self.audio_dir.glob("*.wav")]
        self.logger.debug(f"Found {len(sounds)} sound files")
        return sounds
