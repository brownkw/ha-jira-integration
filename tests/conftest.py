import sys
import pytest
sys.path.insert(0, ".")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Auto-enable custom integrations for all HA-fixture tests."""
