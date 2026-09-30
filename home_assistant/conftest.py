# The shared test harness: blueprint installation, then the fixtures tests use.
pytest_plugins = [
    "testing.blueprints",
    "testing.clock",
    "testing.helpers",
    "testing.sensors",
]
