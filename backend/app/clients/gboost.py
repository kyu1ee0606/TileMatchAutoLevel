"""GBoost server client for level data management."""
import json
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, List

from ..config import get_settings


def parse_gboost_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse GBoost server response format.

    GBoost returns data in compressed format:
    {
        "__keys": ["field1", "field2", ...],
        "__vals": [
            [val1_1, val1_2, ...],  // row 1
            [val2_1, val2_2, ...],  // row 2
            ...
        ]
    }

    Convert to standard format:
    {
        "id1": {"field1": val1_1, "field2": val1_2, ...},
        "id2": {"field1": val2_1, "field2": val2_2, ...},
        ...
    }
    """
    if not data:
        return {}

    keys = data.get("__keys", [])
    vals = data.get("__vals", [])

    if not keys or not vals:
        # Not in compressed format, return as-is
        return data

    result = {}

    # Find the 'id' field index (usually first column)
    id_index = 0
    if "id" in keys:
        id_index = keys.index("id")

    for row in vals:
        if not row or len(row) != len(keys):
            continue

        # Get the ID from this row
        row_id = row[id_index] if id_index < len(row) else None
        if not row_id:
            continue

        # Build object from keys and values
        obj = {}
        for i, key in enumerate(keys):
            if key and i < len(row):  # Skip empty keys
                obj[key] = row[i]

        result[row_id] = obj

    return result


class GBoostClient:
    """Client for communicating with GBoost server (townpop pattern)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """
        Initialize GBoost client.

        Args:
            base_url: GBoost server URL (e.g., https://gameboost.cafe24.com/gameboost/)
            api_key: API authentication key (optional, not used in townpop).
            project_id: App ID / Game ID (e.g., 21ff4576052).
        """
        settings = get_settings()
        self.base_url = (base_url or settings.gboost_url or "").rstrip("/")
        self.api_key = api_key or settings.gboost_api_key
        self.project_id = project_id or settings.gboost_project_id

    @property
    def is_configured(self) -> bool:
        """Check if client is properly configured."""
        # API key is optional for townpop pattern
        return bool(self.base_url and self.project_id)

    async def save_level(
        self,
        board_id: str,
        level_id: str,
        level_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Save level data to GBoost server using real_array.php API.

        Args:
            board_id: Board identifier (bid parameter).
            level_id: Level identifier (used as key in json).
            level_json: Level data to save.

        Returns:
            Response with success status and metadata.
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "GBoost client not configured",
            }

        # Townpop pattern: POST to real_array.php
        endpoint = f"{self.base_url}/real_array.php"

        # Ensure level_id has proper prefix
        array_id = level_id if level_id.startswith("level_") else f"level_{level_id}"

        # Wrap level data with array_id as key (townpop pattern)
        json_data = {array_id: level_json}

        # Form data for POST (townpop pattern)
        form_data = {
            "act": "save",
            "gid": self.project_id,
            "bid": board_id,
            "new": "1",
            "json": json.dumps(json_data),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    result_text = await response.text()

                    if response.status == 200:
                        return {
                            "success": True,
                            "saved_at": datetime.utcnow().isoformat(),
                            "message": f"Level {array_id} saved successfully",
                            "data": result_text,
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Server error: {result_text}",
                            "status_code": response.status,
                        }

        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
            }

    async def load_level(
        self,
        board_id: str,
        level_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Load level data from GBoost server using real_array.php API.

        Args:
            board_id: Board identifier (bid parameter).
            level_id: Level identifier (id parameter).

        Returns:
            Level JSON data or None if not found.
        """
        if not self.is_configured:
            return None

        # Ensure level_id has proper prefix
        array_id = level_id if level_id.startswith("level_") else f"level_{level_id}"

        # Townpop pattern: GET from real_array.php
        endpoint = f"{self.base_url}/real_array.php?act=load&gid={self.project_id}&bid={board_id}&id={array_id}&filter="

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    endpoint,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        result_text = await response.text()

                        if not result_text or result_text.strip() == "" or result_text.strip() == "{}":
                            return None

                        try:
                            raw_result = json.loads(result_text)

                            # Parse GBoost compressed format
                            result = parse_gboost_response(raw_result)

                            # Extract level data from response
                            if array_id in result:
                                level_data = result[array_id]
                            elif result:
                                # If only one key, use that
                                first_key = next(iter(result.keys()), None)
                                level_data = result.get(first_key, result)
                            else:
                                return None

                            return {
                                "level_json": level_data,
                                "metadata": {
                                    "id": array_id,
                                    "created_at": level_data.get("etime", ""),
                                    "updated_at": datetime.utcnow().isoformat(),
                                    "version": "1.0",
                                },
                            }
                        except json.JSONDecodeError:
                            return None
                    elif response.status == 404:
                        return None
                    else:
                        return None

        except (aiohttp.ClientError, json.JSONDecodeError):
            return None

    async def list_levels(
        self,
        board_id: str,
        prefix: str = "level_",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List levels from GBoost server.

        Args:
            board_id: Board identifier.
            prefix: Filter prefix for level IDs.
            limit: Maximum number of results.

        Returns:
            List of level metadata.
        """
        if not self.is_configured:
            return []

        # Load all data from the board (empty id = all)
        endpoint = f"{self.base_url}/real_array.php?act=load&gid={self.project_id}&bid={board_id}&id=&filter="

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    endpoint,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status == 200:
                        result_text = await response.text()

                        if not result_text or result_text.strip() == "" or result_text.strip() == "{}":
                            return []

                        try:
                            raw_result = json.loads(result_text)

                            # Parse GBoost compressed format
                            result = parse_gboost_response(raw_result)

                            levels = []

                            for key, value in result.items():
                                if key.startswith(prefix):
                                    level_info = {
                                        "id": key,
                                        "created_at": "",
                                    }

                                    # Extract metadata if available
                                    if isinstance(value, dict):
                                        if "etime" in value:
                                            # Convert Unix timestamp to ISO format
                                            try:
                                                etime = int(value["etime"])
                                                level_info["created_at"] = datetime.fromtimestamp(etime).isoformat()
                                            except (ValueError, TypeError):
                                                pass

                                        if "difficulty" in value:
                                            try:
                                                level_info["difficulty"] = float(value["difficulty"]) / 100.0
                                            except (ValueError, TypeError):
                                                pass

                                    levels.append(level_info)

                            # Sort by level number
                            def get_level_num(lvl):
                                try:
                                    import re
                                    match = re.search(r'\d+', lvl.get("id", ""))
                                    return int(match.group()) if match else 0
                                except:
                                    return 0

                            levels.sort(key=get_level_num)

                            return levels[:limit]
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}")
                            return []
                    else:
                        return []

        except aiohttp.ClientError as e:
            print(f"Client error: {e}")
            return []

    async def delete_level(
        self,
        board_id: str,
        level_id: str,
    ) -> bool:
        """
        Delete level from GBoost server.

        Note: Townpop pattern may not support direct delete.
        This saves an empty object to effectively "delete" the level.

        Args:
            board_id: Board identifier.
            level_id: Level identifier.

        Returns:
            True if deletion was successful.
        """
        if not self.is_configured:
            return False

        # Ensure level_id has proper prefix
        array_id = level_id if level_id.startswith("level_") else f"level_{level_id}"

        # Save empty/null data to "delete" the level
        endpoint = f"{self.base_url}/real_array.php"

        # Townpop pattern: save null/empty to delete
        form_data = {
            "act": "save",
            "gid": self.project_id,
            "bid": board_id,
            "new": "1",
            "json": json.dumps({array_id: None}),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    return response.status == 200

        except aiohttp.ClientError:
            return False

    async def save_thumbnail(
        self,
        board_id: str,
        level_id: str,
        png_data: bytes,
        size: int = 128,
    ) -> Dict[str, Any]:
        """
        Save thumbnail PNG to GBoost server.

        Args:
            board_id: Board identifier (bid parameter).
            level_id: Level identifier.
            png_data: PNG image data as bytes.
            size: Thumbnail size (default 128).

        Returns:
            Response with success status.
        """
        if not self.is_configured:
            return {
                "success": False,
                "error": "GBoost client not configured",
            }

        # Ensure level_id has proper prefix
        array_id = level_id if level_id.startswith("level_") else f"level_{level_id}"

        # Townpop pattern: POST to real_array.php with thumbpng action
        endpoint = f"{self.base_url}/real_array.php"

        try:
            # Use aiohttp FormData for multipart upload
            form_data = aiohttp.FormData()
            form_data.add_field("act", "thumbpng")
            form_data.add_field("gid", self.project_id)
            form_data.add_field("bid", board_id)
            form_data.add_field("id", array_id)
            form_data.add_field("size", str(size))
            form_data.add_field(
                "png",
                png_data,
                filename="image.png",
                content_type="image/png"
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    result_text = await response.text()

                    if response.status == 200:
                        return {
                            "success": True,
                            "message": f"Thumbnail for {array_id} saved successfully",
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Server error: {result_text}",
                            "status_code": response.status,
                        }

        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
            }

    async def health_check(self) -> Dict[str, Any]:
        """
        Check GBoost server health.

        Returns:
            Health status information.
        """
        if not self.base_url:
            return {
                "healthy": False,
                "error": "GBoost URL not configured",
            }

        try:
            # Try to access a simple endpoint
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/real_array.php?act=load&gid={self.project_id or 'test'}&bid=_health_check&id=",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    return {
                        "healthy": response.status == 200,
                        "status_code": response.status,
                    }

        except aiohttp.ClientError as e:
            return {
                "healthy": False,
                "error": str(e),
            }


# Singleton instance
_client = None


def get_gboost_client() -> GBoostClient:
    """Get or create GBoost client singleton instance."""
    global _client
    if _client is None:
        _client = GBoostClient()
    return _client


def update_gboost_client(
    base_url: str,
    api_key: str,
    project_id: str,
) -> GBoostClient:
    """Update GBoost client with new configuration."""
    global _client
    _client = GBoostClient(
        base_url=base_url,
        api_key=api_key,
        project_id=project_id,
    )
    return _client
