"""Tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_level():
    """Sample level JSON for testing."""
    return {
        "layer": 8,
        "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
        "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_3": {"col": "7", "row": "7", "tiles": {"3_3": ["t0", ""]}, "num": "1"},
        "layer_4": {
            "col": "8",
            "row": "8",
            "tiles": {
                "3_3": ["t0", ""],
                "4_3": ["t0", ""],
                "3_4": ["t0", ""],
                "4_4": ["t0", ""],
            },
            "num": "4",
        },
        "layer_5": {
            "col": "7",
            "row": "7",
            "tiles": {
                "2_2": ["t0", "chain"],
                "3_2": ["t0", ""],
                "4_2": ["t0", ""],
            },
            "num": "3",
        },
        "layer_6": {
            "col": "8",
            "row": "8",
            "tiles": {
                "2_1": ["t2", ""],
                "5_1": ["t0", "frog"],
            },
            "num": "2",
        },
        "layer_7": {
            "col": "7",
            "row": "7",
            "tiles": {
                "0_0": ["t4", ""],
                "1_0": ["t0", ""],
                "3_6": ["craft_s", "", [3]],
            },
            "num": "3",
        },
    }


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_info(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data


class TestHealthEndpoint:
    """Tests for health endpoint."""

    def test_health_check(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestAnalyzeEndpoint:
    """Tests for analyze endpoint."""

    def test_analyze_valid_level(self, client, sample_level):
        """Test analyzing a valid level."""
        response = client.post(
            "/api/analyze",
            json={"level_json": sample_level},
        )

        assert response.status_code == 200
        data = response.json()
        assert "score" in data
        assert "grade" in data
        assert "metrics" in data
        assert "recommendations" in data

    def test_analyze_score_range(self, client, sample_level):
        """Test that score is in valid range."""
        response = client.post(
            "/api/analyze",
            json={"level_json": sample_level},
        )

        data = response.json()
        assert 0 <= data["score"] <= 100

    def test_analyze_grade_valid(self, client, sample_level):
        """Test that grade is valid."""
        response = client.post(
            "/api/analyze",
            json={"level_json": sample_level},
        )

        data = response.json()
        assert data["grade"] in ["S", "A", "B", "C", "D"]

    def test_analyze_metrics_present(self, client, sample_level):
        """Test that metrics are present in response."""
        response = client.post(
            "/api/analyze",
            json={"level_json": sample_level},
        )

        data = response.json()
        metrics = data["metrics"]

        assert "total_tiles" in metrics
        assert "active_layers" in metrics
        assert "chain_count" in metrics
        assert "frog_count" in metrics
        assert "link_count" in metrics
        assert "goal_amount" in metrics
        assert "layer_blocking" in metrics

    def test_analyze_empty_request(self, client):
        """Test analyzing with missing level_json."""
        response = client.post("/api/analyze", json={})

        assert response.status_code == 422  # Validation error


class TestGenerateEndpoint:
    """Tests for generate endpoint."""

    def test_generate_basic(self, client):
        """Test basic level generation."""
        response = client.post(
            "/api/generate",
            json={"target_difficulty": 0.5},
        )

        assert response.status_code == 200
        data = response.json()
        assert "level_json" in data
        assert "actual_difficulty" in data
        assert "grade" in data

    def test_generate_with_params(self, client):
        """Test generation with custom parameters."""
        response = client.post(
            "/api/generate",
            json={
                "target_difficulty": 0.7,
                "grid_size": [6, 6],
                "max_layers": 6,
            },
        )

        assert response.status_code == 200
        data = response.json()

        level = data["level_json"]
        assert level["layer"] == 6

    def test_generate_with_goals(self, client):
        """Test generation with custom goals."""
        response = client.post(
            "/api/generate",
            json={
                "target_difficulty": 0.5,
                "goals": [
                    {"type": "craft_s", "count": 5},
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "level_json" in data

    def test_generate_invalid_difficulty(self, client):
        """Test generation with invalid difficulty."""
        response = client.post(
            "/api/generate",
            json={"target_difficulty": 1.5},  # Out of range
        )

        assert response.status_code == 422  # Validation error

    def test_generate_difficulty_range(self, client):
        """Test that generated level has valid difficulty."""
        response = client.post(
            "/api/generate",
            json={"target_difficulty": 0.5},
        )

        data = response.json()
        assert 0 <= data["actual_difficulty"] <= 1


class TestSimulateEndpoint:
    """Tests for simulate endpoint."""

    def test_simulate_basic(self, client, sample_level):
        """Test basic simulation."""
        response = client.post(
            "/api/simulate",
            json={
                "level_json": sample_level,
                "iterations": 50,
                "strategy": "greedy",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "clear_rate" in data
        assert "avg_moves" in data
        assert "min_moves" in data
        assert "max_moves" in data
        assert "difficulty_estimate" in data

    def test_simulate_clear_rate_range(self, client, sample_level):
        """Test that clear rate is in valid range."""
        response = client.post(
            "/api/simulate",
            json={
                "level_json": sample_level,
                "iterations": 50,
                "strategy": "greedy",
            },
        )

        data = response.json()
        assert 0 <= data["clear_rate"] <= 1

    def test_simulate_different_strategies(self, client, sample_level):
        """Test simulation with different strategies."""
        strategies = ["random", "greedy", "optimal"]

        for strategy in strategies:
            response = client.post(
                "/api/simulate",
                json={
                    "level_json": sample_level,
                    "iterations": 20,
                    "strategy": strategy,
                },
            )

            assert response.status_code == 200


class TestBatchAnalyzeEndpoint:
    """Tests for batch analyze endpoint."""

    def test_batch_analyze_multiple_levels(self, client, sample_level):
        """Test batch analyzing multiple levels."""
        response = client.post(
            "/api/levels/batch-analyze",
            json={
                "levels": [sample_level, sample_level],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 2

    def test_batch_analyze_results_complete(self, client, sample_level):
        """Test that batch results are complete."""
        response = client.post(
            "/api/levels/batch-analyze",
            json={
                "levels": [sample_level],
            },
        )

        data = response.json()
        result = data["results"][0]

        assert "level_id" in result
        assert "score" in result
        assert "grade" in result
        assert "metrics" in result


class TestGBoostEndpoints:
    """Tests for GBoost endpoints."""

    def test_gboost_health(self, client):
        """Test GBoost health check endpoint."""
        response = client.get("/api/gboost/health")

        assert response.status_code == 200
        data = response.json()
        assert "configured" in data

    def test_gboost_not_configured(self, client, sample_level):
        """Test GBoost operations when not configured."""
        # Without proper config, should return 503 or appropriate error
        response = client.post(
            "/api/gboost/test_board/test_level",
            json={"level_json": sample_level},
        )

        # Should fail because GBoost is not configured
        assert response.status_code in [503, 500, 400]
