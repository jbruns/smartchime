import os
import logging
import xml.etree.ElementTree as ET
from threading import Thread, Event

class ShairportMetadata:
    """Reads and parses metadata from a shairport-sync metadata pipe.
    Only processes artist (asar), title (minm), and playback state information."""

    def __init__(self, pipe_path="/tmp/shairport-sync-metadata"):
        """Initialize the shairport metadata reader.
        
        Args:
            pipe_path (str): Path to the shairport-sync metadata pipe"""
        self.logger = logging.getLogger(__name__)
        self.pipe_path = pipe_path
        self.current_artist = ""
        self.current_title = ""
        self.is_playing = False
        self._stop_event = Event()
        self._reader_thread = None
        self._callbacks = []

    def start(self):
        """Start reading metadata from the pipe in a background thread."""
        if self._reader_thread and self._reader_thread.is_alive():
            self.logger.warning("Metadata reader already running")
            return

        if not os.path.exists(self.pipe_path):
            self.logger.error(f"Metadata pipe not found at {self.pipe_path}")
            return

        self._stop_event.clear()
        self._reader_thread = Thread(target=self._read_metadata_loop, daemon=True)
        self._reader_thread.start()
        self.logger.info("Started metadata reader thread")

    def stop(self):
        """Stop reading metadata and clean up resources."""
        if self._reader_thread and self._reader_thread.is_alive():
            self._stop_event.set()
            self._reader_thread.join(timeout=1.0)
            self.logger.info("Stopped metadata reader thread")

    def add_callback(self, callback):
        """Add a callback to be called when metadata changes.
        
        Args:
            callback (callable): Function to call with (artist, title, is_playing) arguments"""
        if callable(callback) and callback not in self._callbacks:
            self._callbacks.append(callback)
            self.logger.debug(f"Added metadata callback {callback.__name__}")

    def remove_callback(self, callback):
        """Remove a previously added callback.
        
        Args:
            callback (callable): The callback function to remove"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            self.logger.debug(f"Removed metadata callback {callback.__name__}")

    def _read_metadata_loop(self):
        """Main loop for reading and parsing metadata from the pipe."""
        try:
            with open(self.pipe_path, 'rb', buffering=0) as pipe:
                buffer = ""
                while not self._stop_event.is_set():
                    char = pipe.read(1).decode('utf-8', errors='ignore')
                    if char == '':  # EOF
                        if self.is_playing:
                            self.is_playing = False
                            self._notify_callbacks()
                        continue

                    buffer += char
                    if '</item>' in buffer:
                        try:
                            self._parse_metadata(buffer)
                        except ET.ParseError:
                            self.logger.warning("Failed to parse metadata XML", exc_info=True)
                        buffer = ""

        except OSError as e:
            self.logger.error(f"Error reading from metadata pipe: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in metadata reader: {e}", exc_info=True)

    def _parse_metadata(self, xml_str):
        """Parse metadata XML and update current state.
        
        Args:
            xml_str (str): XML string to parse"""
        try:
            root = ET.fromstring(xml_str)
            
            # Check for playback state changes
            if root.get('type') == 'ssnc' and root.findtext('code') == 'pbeg':
                self.is_playing = True
                self._notify_callbacks()
                return
            elif root.get('type') == 'ssnc' and root.findtext('code') in ['pend', 'prgr']:
                self.is_playing = False
                self._notify_callbacks()
                return

            # Parse metadata items
            if root.get('type') == 'core':
                code = root.findtext('code')
                data = root.findtext('data')
                
                if code == 'asar' and data:  # Artist
                    self.current_artist = data
                    self._notify_callbacks()
                elif code == 'minm' and data:  # Title
                    self.current_title = data
                    self._notify_callbacks()

        except ET.ParseError:
            self.logger.warning("Failed to parse metadata XML", exc_info=True)
        except Exception as e:
            self.logger.error(f"Error processing metadata: {e}", exc_info=True)

    def _notify_callbacks(self):
        """Notify all registered callbacks of the current state."""
        for callback in self._callbacks:
            try:
                callback(self.current_artist, self.current_title, self.is_playing)
            except Exception as e:
                self.logger.error(f"Error in metadata callback: {e}", exc_info=True)