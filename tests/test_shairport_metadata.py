"""Tests for shairport_metadata module."""

from unittest.mock import MagicMock

from smartchime.shairport_metadata import ShairportMetadata


class TestShairportMetadata:
    def test_initial_state(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        assert reader.current_artist == ""
        assert reader.current_title == ""
        assert reader.is_playing is False

    def test_add_and_remove_callback(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")

        def my_callback(artist, title, is_playing):
            pass

        reader.add_callback(my_callback)
        assert my_callback in reader._callbacks

        reader.remove_callback(my_callback)
        assert my_callback not in reader._callbacks

    def test_add_callback_rejects_non_callable(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        reader.add_callback("not a function")
        assert len(reader._callbacks) == 0

    def test_add_callback_deduplication(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")

        def my_callback(artist, title, is_playing):
            pass

        reader.add_callback(my_callback)
        reader.add_callback(my_callback)
        assert len(reader._callbacks) == 1

    def test_parse_artist_metadata(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        received = []
        reader.add_callback(lambda a, t, p: received.append((a, t, p)))

        xml = '<item type="core"><code>asar</code><data>Test Artist</data></item>'
        reader._parse_metadata(xml)

        assert reader.current_artist == "Test Artist"
        assert len(received) == 1
        assert received[0][0] == "Test Artist"

    def test_parse_title_metadata(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        received = []
        reader.add_callback(lambda a, t, p: received.append((a, t, p)))

        xml = '<item type="core"><code>minm</code><data>Test Title</data></item>'
        reader._parse_metadata(xml)

        assert reader.current_title == "Test Title"
        assert len(received) == 1
        assert received[0][1] == "Test Title"

    def test_parse_playback_begin(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")

        xml = '<item type="ssnc"><code>pbeg</code></item>'
        reader._parse_metadata(xml)

        assert reader.is_playing is True

    def test_parse_playback_end(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        reader.is_playing = True

        xml = '<item type="ssnc"><code>pend</code></item>'
        reader._parse_metadata(xml)

        assert reader.is_playing is False

    def test_parse_invalid_xml(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        # Should not raise — errors are logged and swallowed
        reader._parse_metadata("this is not xml")

    def test_start_with_missing_pipe(self):
        reader = ShairportMetadata(pipe_path="/nonexistent/pipe")
        # Should not raise — logs error and returns
        reader.start()
        assert reader._reader_thread is None or not reader._reader_thread.is_alive()

    def test_parse_playback_progress_stops(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        reader.is_playing = True

        xml = '<item type="ssnc"><code>prgr</code></item>'
        reader._parse_metadata(xml)

        assert reader.is_playing is False

    def test_parse_core_metadata_without_data(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        reader.current_artist = "Original Artist"

        xml = '<item type="core"><code>asar</code></item>'
        reader._parse_metadata(xml)

        assert reader.current_artist == "Original Artist"

    def test_notify_callbacks_swallows_exception(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        received = []

        def bad_callback(artist, title, is_playing):
            raise RuntimeError("boom")

        def good_callback(artist, title, is_playing):
            received.append((artist, title, is_playing))

        reader.add_callback(bad_callback)
        reader.add_callback(good_callback)

        xml = '<item type="ssnc"><code>pbeg</code></item>'
        reader._parse_metadata(xml)

        assert len(received) == 1
        assert received[0][2] is True

    def test_stop_sets_event_and_joins(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        reader._reader_thread = mock_thread

        reader.stop()

        assert reader._stop_event.is_set()
        mock_thread.join.assert_called_once_with(timeout=1.0)

    def test_stop_noop_when_no_thread(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        assert reader._reader_thread is None
        reader.stop()
        assert not reader._stop_event.is_set()

    def test_remove_nonexistent_callback(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")

        def unknown_callback(artist, title, is_playing):
            pass

        reader.remove_callback(unknown_callback)
        assert len(reader._callbacks) == 0

    def test_start_already_running(self):
        reader = ShairportMetadata(pipe_path="/nonexistent")
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        reader._reader_thread = mock_thread

        reader.start()

        assert reader._reader_thread is mock_thread
