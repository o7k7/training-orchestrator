import os

# app.config.Config() is instantiated at import time, so required settings must be
# present in the environment before any test module imports app.config (directly
# or transitively). Set sane defaults here, before test collection touches app.*.
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PASSWORD", "test-password")
os.environ.setdefault("ML_FLOW_URI", "http://localhost:5000")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("ENVIRONMENT", "local")
