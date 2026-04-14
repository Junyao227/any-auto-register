"""
Unit Tests for HeroSMS Disk Persistence Functions

These tests verify the disk persistence functions (_save_phone_cache_to_disk and
_load_phone_cache_from_disk) work correctly in isolation.

**Validates: Requirements 2.3, 2.5**
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import time
import json
import pytest
import tempfile
import shutil
from unittest.mock import patch

# Import the module under test
from platforms.gpt_hero_sms import phone_verification


class TestSavePhoneCacheToDisk:
    """Test _save_phone_cache_to_disk() function"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary directory for cache files"""
        temp_dir = tempfile.mkdtemp()
        cache_file = os.path.join(temp_dir, ".herosms_phone_cache.json")
        
        # Patch the cache file path
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
            yield cache_file
        
        # Clean up
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    def test_save_valid_cache_data(self, temp_cache_dir):
        """
        Test _save_phone_cache_to_disk() with valid cache data
        
        Verify JSON file is created with correct structure
        """
        # Set up valid cache data
        test_cache = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 2,
            "used_codes": {"123456", "654321"}  # Set
        }
        
        with patch.object(phone_verification, '_local_phone_cache', test_cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Verify file was created
        assert os.path.exists(temp_cache_dir), "Cache file should be created"
        
        # Verify file contains valid JSON
        with open(temp_cache_dir, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        # Verify structure
        assert saved_data["phone_number"] == "+11234567890", "Phone number should match"
        assert saved_data["activation_id"] == "test_activation_123", "Activation ID should match"
        assert saved_data["acquired_at"] == test_cache["acquired_at"], "Timestamp should match"
        assert saved_data["use_count"] == 2, "Use count should match"
        
        # Verify used_codes is converted from set to list
        assert isinstance(saved_data["used_codes"], list), "used_codes should be a list in JSON"
        assert set(saved_data["used_codes"]) == {"123456", "654321"}, "used_codes content should match"
    
    def test_save_none_cache_deletes_file(self, temp_cache_dir):
        """
        Test _save_phone_cache_to_disk() with None cache
        
        Verify file is deleted when cache is None
        """
        # Create a cache file first
        test_data = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 1,
            "used_codes": ["123456"]
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        assert os.path.exists(temp_cache_dir), "Cache file should exist initially"
        
        # Set cache to None and save
        with patch.object(phone_verification, '_local_phone_cache', None):
            phone_verification._save_phone_cache_to_disk()
        
        # Verify file was deleted
        assert not os.path.exists(temp_cache_dir), "Cache file should be deleted when cache is None"
    
    def test_save_creates_directory_if_missing(self):
        """
        Test cache directory creation
        
        Verify data/ folder is created if missing
        """
        # Create a temporary directory path that doesn't exist yet
        temp_base = tempfile.mkdtemp()
        cache_dir = os.path.join(temp_base, "data")
        cache_file = os.path.join(cache_dir, ".herosms_phone_cache.json")
        
        try:
            # Ensure directory doesn't exist
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
            
            assert not os.path.exists(cache_dir), "Cache directory should not exist initially"
            
            # Set up cache data
            test_cache = {
                "phone_number": "+11234567890",
                "activation_id": "test_activation_123",
                "acquired_at": time.time(),
                "use_count": 1,
                "used_codes": {"123456"}
            }
            
            with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
                with patch.object(phone_verification, '_local_phone_cache', test_cache):
                    phone_verification._save_phone_cache_to_disk()
            
            # Verify directory was created
            assert os.path.exists(cache_dir), "Cache directory should be created"
            assert os.path.isdir(cache_dir), "Cache directory should be a directory"
            
            # Verify file was created
            assert os.path.exists(cache_file), "Cache file should be created"
        
        finally:
            # Clean up
            if os.path.exists(temp_base):
                shutil.rmtree(temp_base)
    
    def test_save_handles_empty_used_codes(self, temp_cache_dir):
        """
        Test _save_phone_cache_to_disk() with empty used_codes set
        
        Verify empty set is saved as empty list
        """
        test_cache = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 0,
            "used_codes": set()  # Empty set
        }
        
        with patch.object(phone_verification, '_local_phone_cache', test_cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Verify file was created
        assert os.path.exists(temp_cache_dir), "Cache file should be created"
        
        # Verify empty set is saved as empty list
        with open(temp_cache_dir, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        assert saved_data["used_codes"] == [], "Empty used_codes set should be saved as empty list"


class TestLoadPhoneCacheFromDisk:
    """Test _load_phone_cache_from_disk() function"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary directory for cache files"""
        temp_dir = tempfile.mkdtemp()
        cache_file = os.path.join(temp_dir, ".herosms_phone_cache.json")
        
        # Patch the cache file path
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
            yield cache_file
        
        # Clean up
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    def test_load_valid_cache_file(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with valid cache file
        
        Verify cache is loaded correctly
        """
        # Create a valid cache file
        test_data = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 2,
            "used_codes": ["123456", "654321"]  # List in JSON
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Load cache
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was loaded
        assert loaded_cache is not None, "Cache should be loaded"
        assert loaded_cache["phone_number"] == "+11234567890", "Phone number should match"
        assert loaded_cache["activation_id"] == "test_activation_123", "Activation ID should match"
        assert loaded_cache["use_count"] == 2, "Use count should match"
        
        # Verify used_codes is converted from list to set
        assert isinstance(loaded_cache["used_codes"], set), "used_codes should be a set"
        assert loaded_cache["used_codes"] == {"123456", "654321"}, "used_codes content should match"
    
    def test_load_expired_cache_deletes_file(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with expired cache
        
        Verify file is deleted and returns None
        """
        # Create an expired cache file (25 minutes old)
        expired_time = time.time() - (25 * 60)  # 25 minutes ago
        test_data = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": expired_time,
            "use_count": 1,
            "used_codes": ["123456"]
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        assert os.path.exists(temp_cache_dir), "Cache file should exist initially"
        
        # Load cache
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was not loaded (expired)
        assert loaded_cache is None, "Expired cache should return None"
        
        # Verify file was deleted
        assert not os.path.exists(temp_cache_dir), "Expired cache file should be deleted"
    
    def test_load_corrupted_json_returns_none(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with corrupted JSON
        
        Verify returns None and doesn't crash
        """
        # Create a corrupted JSON file
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            f.write("{ invalid json content }")
        
        assert os.path.exists(temp_cache_dir), "Cache file should exist initially"
        
        # Load cache (should not crash)
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was not loaded
        assert loaded_cache is None, "Corrupted cache should return None"
        
        # Verify corrupted file was deleted
        assert not os.path.exists(temp_cache_dir), "Corrupted cache file should be deleted"
    
    def test_load_missing_file_returns_none(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with missing file
        
        Verify returns None
        """
        # Ensure file doesn't exist
        if os.path.exists(temp_cache_dir):
            os.remove(temp_cache_dir)
        
        assert not os.path.exists(temp_cache_dir), "Cache file should not exist"
        
        # Load cache
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was not loaded
        assert loaded_cache is None, "Missing cache file should return None"
    
    def test_load_missing_fields_returns_none(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with missing required fields
        
        Verify returns None when JSON is valid but missing fields
        """
        # Create a cache file with missing fields
        test_data = {
            "phone_number": "+11234567890",
            # Missing activation_id, acquired_at, etc.
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Load cache (should not crash)
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was not loaded
        assert loaded_cache is None, "Cache with missing fields should return None"
    
    def test_load_cache_within_lifetime(self, temp_cache_dir):
        """
        Test _load_phone_cache_from_disk() with cache within 20-minute lifetime
        
        Verify cache is loaded successfully
        """
        # Create a cache file that's 10 minutes old (within 20-minute window)
        recent_time = time.time() - (10 * 60)  # 10 minutes ago
        test_data = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": recent_time,
            "use_count": 1,
            "used_codes": ["123456"]
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Load cache
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify cache was loaded
        assert loaded_cache is not None, "Cache within lifetime should be loaded"
        assert loaded_cache["phone_number"] == "+11234567890", "Phone number should match"
        
        # Verify file still exists (not deleted)
        assert os.path.exists(temp_cache_dir), "Cache file should still exist"


class TestUsedCodesSetSerialization:
    """Test used_codes set serialization and deserialization"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary directory for cache files"""
        temp_dir = tempfile.mkdtemp()
        cache_file = os.path.join(temp_dir, ".herosms_phone_cache.json")
        
        # Patch the cache file path
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
            yield cache_file
        
        # Clean up
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    def test_set_converts_to_list_in_json(self, temp_cache_dir):
        """
        Test used_codes set converts to list in JSON
        
        Verify set is serialized as list (JSON doesn't support sets)
        """
        test_cache = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 3,
            "used_codes": {"code1", "code2", "code3"}  # Set
        }
        
        with patch.object(phone_verification, '_local_phone_cache', test_cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Read raw JSON
        with open(temp_cache_dir, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        # Verify used_codes is a list in JSON
        assert isinstance(saved_data["used_codes"], list), "used_codes should be a list in JSON"
        assert len(saved_data["used_codes"]) == 3, "Should have 3 codes"
        assert set(saved_data["used_codes"]) == {"code1", "code2", "code3"}, "Content should match"
    
    def test_list_converts_back_to_set_on_load(self, temp_cache_dir):
        """
        Test used_codes list converts back to set on load
        
        Verify list is deserialized as set for efficient lookups
        """
        # Create cache file with list
        test_data = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 3,
            "used_codes": ["code1", "code2", "code3"]  # List in JSON
        }
        
        with open(temp_cache_dir, 'w', encoding='utf-8') as f:
            json.dump(test_data, f)
        
        # Load cache
        with patch.object(phone_verification, '_local_phone_cache', None):
            loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify used_codes is a set
        assert isinstance(loaded_cache["used_codes"], set), "used_codes should be a set after loading"
        assert loaded_cache["used_codes"] == {"code1", "code2", "code3"}, "Content should match"


class TestRoundTripPersistence:
    """Test round-trip: save cache, load cache, verify data matches"""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary directory for cache files"""
        temp_dir = tempfile.mkdtemp()
        cache_file = os.path.join(temp_dir, ".herosms_phone_cache.json")
        
        # Patch the cache file path
        with patch.object(phone_verification, '_PHONE_CACHE_FILE', cache_file):
            yield cache_file
        
        # Clean up
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    def test_round_trip_preserves_data(self, temp_cache_dir):
        """
        Test round-trip: save cache, load cache, verify data matches
        
        Verify all data is preserved through save/load cycle
        """
        # Original cache data
        original_cache = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 5,
            "used_codes": {"code1", "code2", "code3", "code4", "code5"}
        }
        
        # Save cache
        with patch.object(phone_verification, '_local_phone_cache', original_cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Clear in-memory cache
        phone_verification._local_phone_cache = None
        
        # Load cache
        loaded_cache = phone_verification._load_phone_cache_from_disk()
        
        # Verify all data matches
        assert loaded_cache is not None, "Cache should be loaded"
        assert loaded_cache["phone_number"] == original_cache["phone_number"], "Phone number should match"
        assert loaded_cache["activation_id"] == original_cache["activation_id"], "Activation ID should match"
        assert loaded_cache["acquired_at"] == original_cache["acquired_at"], "Timestamp should match"
        assert loaded_cache["use_count"] == original_cache["use_count"], "Use count should match"
        assert loaded_cache["used_codes"] == original_cache["used_codes"], "Used codes should match"
    
    def test_round_trip_with_multiple_updates(self, temp_cache_dir):
        """
        Test round-trip with multiple cache updates
        
        Verify cache updates are preserved correctly
        """
        # Initial cache
        cache = {
            "phone_number": "+11234567890",
            "activation_id": "test_activation_123",
            "acquired_at": time.time(),
            "use_count": 0,
            "used_codes": set()
        }
        
        # Save initial cache
        with patch.object(phone_verification, '_local_phone_cache', cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Update 1: Add first code
        cache["use_count"] = 1
        cache["used_codes"].add("code1")
        with patch.object(phone_verification, '_local_phone_cache', cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Load and verify
        phone_verification._local_phone_cache = None
        loaded = phone_verification._load_phone_cache_from_disk()
        assert loaded["use_count"] == 1, "Use count should be 1"
        assert loaded["used_codes"] == {"code1"}, "Should have code1"
        
        # Update 2: Add second code
        cache["use_count"] = 2
        cache["used_codes"].add("code2")
        with patch.object(phone_verification, '_local_phone_cache', cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Load and verify
        phone_verification._local_phone_cache = None
        loaded = phone_verification._load_phone_cache_from_disk()
        assert loaded["use_count"] == 2, "Use count should be 2"
        assert loaded["used_codes"] == {"code1", "code2"}, "Should have code1 and code2"
        
        # Update 3: Add third code
        cache["use_count"] = 3
        cache["used_codes"].add("code3")
        with patch.object(phone_verification, '_local_phone_cache', cache):
            phone_verification._save_phone_cache_to_disk()
        
        # Load and verify final state
        phone_verification._local_phone_cache = None
        loaded = phone_verification._load_phone_cache_from_disk()
        assert loaded["use_count"] == 3, "Use count should be 3"
        assert loaded["used_codes"] == {"code1", "code2", "code3"}, "Should have all 3 codes"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])
