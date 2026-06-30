import os

# Force the Config() default path (no /data/options.json) during tests.
os.environ.setdefault("PYTEST_CURRENT_TEST", "conftest")
