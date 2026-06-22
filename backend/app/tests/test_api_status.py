from unittest.mock import patch

import pytest

from app.core.config import Settings


@pytest.mark.anyio
async def test_runtime_status_is_public(client):
    """GET /api/status returns local dependency state without auth."""
    with patch("app.core.config.get_settings", return_value=Settings(auth_token="test-token")):
        response = await client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "steamanalysis"
    assert "database" in body
    assert "embedding" in body
    assert "scheduler" in body
    assert "task_worker" in body
