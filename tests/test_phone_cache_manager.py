"""
手机号缓存管理器单元测试

测试缓存读写逻辑、持久化和线程安全。
"""

import os
import json
import time
import tempfile
import threading
import pytest
from platforms.gpt_hero_sms.phone_cache import PhoneCache
from platforms.gpt_hero_sms.cache_manager import PhoneCacheManager


class TestPhoneCacheManager:
    """PhoneCacheManager 单元测试"""
    
    @pytest.fixture
    def temp_cache_file(self):
        """创建临时缓存文件"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            cache_file = f.name
        yield cache_file
        # 清理
        if os.path.exists(cache_file):
            os.remove(cache_file)
    
    @pytest.fixture
    def cache_manager(self, temp_cache_file):
        """创建缓存管理器实例"""
        return PhoneCacheManager(cache_file_path=temp_cache_file)
    
    @pytest.fixture
    def sample_cache(self):
        """创建示例缓存对象"""
        return PhoneCache(
            phone_number="+1234567890",
            activation_id="test_activation_123",
            acquired_at=time.time(),
            use_count=0,
            used_codes=set()
        )
    
    def test_init_with_default_path(self):
        """测试使用默认路径初始化"""
        manager = PhoneCacheManager()
        assert manager.cache_file_path.endswith(".herosms_phone_cache.json")
        assert "data" in manager.cache_file_path
    
    def test_init_with_custom_path(self, temp_cache_file):
        """测试使用自定义路径初始化"""
        manager = PhoneCacheManager(cache_file_path=temp_cache_file)
        assert manager.cache_file_path == temp_cache_file
    
    def test_get_cache_empty(self, cache_manager):
        """测试获取空缓存"""
        cache = cache_manager.get_cache()
        assert cache is None
    
    def test_set_and_get_cache(self, cache_manager, sample_cache):
        """测试设置和获取缓存"""
        cache_manager.set_cache(sample_cache)
        retrieved_cache = cache_manager.get_cache()
        
        assert retrieved_cache is not None
        assert retrieved_cache.phone_number == sample_cache.phone_number
        assert retrieved_cache.activation_id == sample_cache.activation_id
        assert retrieved_cache.use_count == sample_cache.use_count
    
    def test_invalidate_cache(self, cache_manager, sample_cache):
        """测试使缓存失效"""
        cache_manager.set_cache(sample_cache)
        assert cache_manager.get_cache() is not None
        
        cache_manager.invalidate_cache()
        assert cache_manager.get_cache() is None
    
    def test_cache_expiration(self, cache_manager):
        """测试缓存过期"""
        # 创建一个已过期的缓存（获取时间设置为 21 分钟前）
        expired_cache = PhoneCache(
            phone_number="+1234567890",
            activation_id="test_activation_123",
            acquired_at=time.time() - 1260,  # 21 分钟前
            use_count=0,
            used_codes=set()
        )
        
        cache_manager.set_cache(expired_cache)
        
        # 获取缓存时应该返回 None（因为已过期）
        retrieved_cache = cache_manager.get_cache()
        assert retrieved_cache is None
    
    def test_save_to_disk(self, cache_manager, sample_cache, temp_cache_file):
        """测试保存到磁盘"""
        cache_manager.set_cache(sample_cache)
        
        # 验证文件被创建
        assert os.path.exists(temp_cache_file)
        
        # 验证文件内容
        with open(temp_cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["phone_number"] == sample_cache.phone_number
        assert data["activation_id"] == sample_cache.activation_id
        assert data["use_count"] == sample_cache.use_count
    
    def test_load_from_disk(self, cache_manager, sample_cache, temp_cache_file):
        """测试从磁盘加载"""
        # 先保存缓存
        cache_manager.set_cache(sample_cache)
        
        # 创建新的管理器实例（模拟跨进程）
        new_manager = PhoneCacheManager(cache_file_path=temp_cache_file)
        
        # 从磁盘加载
        loaded_cache = new_manager.load_from_disk()
        
        assert loaded_cache is not None
        assert loaded_cache.phone_number == sample_cache.phone_number
        assert loaded_cache.activation_id == sample_cache.activation_id
        assert loaded_cache.use_count == sample_cache.use_count
    
    def test_load_from_disk_no_file(self, cache_manager):
        """测试从不存在的文件加载"""
        loaded_cache = cache_manager.load_from_disk()
        assert loaded_cache is None
    
    def test_load_from_disk_expired(self, cache_manager, temp_cache_file):
        """测试从磁盘加载过期缓存"""
        # 创建过期缓存并保存到磁盘
        expired_cache = PhoneCache(
            phone_number="+1234567890",
            activation_id="test_activation_123",
            acquired_at=time.time() - 1260,  # 21 分钟前
            use_count=0,
            used_codes=set()
        )
        
        # 手动写入文件
        with open(temp_cache_file, "w", encoding="utf-8") as f:
            json.dump(expired_cache.to_dict(), f)
        
        # 尝试加载
        loaded_cache = cache_manager.load_from_disk()
        
        # 应该返回 None，并且文件应该被删除
        assert loaded_cache is None
        assert not os.path.exists(temp_cache_file)
    
    def test_load_from_disk_corrupted_file(self, cache_manager, temp_cache_file):
        """测试从损坏的文件加载"""
        # 写入无效的 JSON
        with open(temp_cache_file, "w", encoding="utf-8") as f:
            f.write("invalid json content")
        
        # 尝试加载
        loaded_cache = cache_manager.load_from_disk()
        
        # 应该返回 None，并且文件应该被删除
        assert loaded_cache is None
        assert not os.path.exists(temp_cache_file)
    
    def test_invalidate_removes_disk_file(self, cache_manager, sample_cache, temp_cache_file):
        """测试使缓存失效时删除磁盘文件"""
        cache_manager.set_cache(sample_cache)
        assert os.path.exists(temp_cache_file)
        
        cache_manager.invalidate_cache()
        assert not os.path.exists(temp_cache_file)
    
    def test_get_remaining_time(self, cache_manager, sample_cache):
        """测试获取剩余时间"""
        cache_manager.set_cache(sample_cache)
        
        remaining_time = cache_manager.get_remaining_time()
        
        # 剩余时间应该接近 20 分钟（1200 秒）
        assert 1190 < remaining_time <= 1200
    
    def test_get_remaining_time_no_cache(self, cache_manager):
        """测试无缓存时获取剩余时间"""
        remaining_time = cache_manager.get_remaining_time()
        assert remaining_time == 0
    
    def test_thread_safety(self, cache_manager, sample_cache):
        """测试线程安全"""
        results = []
        
        def set_cache_thread():
            for i in range(10):
                cache = PhoneCache(
                    phone_number=f"+123456789{i}",
                    activation_id=f"activation_{i}",
                    acquired_at=time.time(),
                    use_count=i,
                    used_codes=set()
                )
                cache_manager.set_cache(cache)
                time.sleep(0.001)
        
        def get_cache_thread():
            for _ in range(10):
                cache = cache_manager.get_cache()
                results.append(cache)
                time.sleep(0.001)
        
        # 创建多个线程
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=set_cache_thread))
            threads.append(threading.Thread(target=get_cache_thread))
        
        # 启动所有线程
        for thread in threads:
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 验证没有异常发生（如果有异常，线程会失败）
        # 验证最终缓存存在
        final_cache = cache_manager.get_cache()
        assert final_cache is not None
    
    def test_cache_persistence_across_instances(self, sample_cache, temp_cache_file):
        """测试跨实例缓存持久化"""
        # 第一个实例：设置缓存
        manager1 = PhoneCacheManager(cache_file_path=temp_cache_file)
        manager1.set_cache(sample_cache)
        
        # 第二个实例：加载缓存
        manager2 = PhoneCacheManager(cache_file_path=temp_cache_file)
        loaded_cache = manager2.load_from_disk()
        
        assert loaded_cache is not None
        assert loaded_cache.phone_number == sample_cache.phone_number
        assert loaded_cache.activation_id == sample_cache.activation_id
        
        # 第二个实例：修改缓存
        loaded_cache.increment_use_count()
        manager2.set_cache(loaded_cache)
        
        # 第三个实例：验证修改
        manager3 = PhoneCacheManager(cache_file_path=temp_cache_file)
        final_cache = manager3.load_from_disk()
        
        assert final_cache is not None
        assert final_cache.use_count == 1


class TestCacheManagerSingleton:
    """测试全局缓存管理器单例"""
    
    def test_get_cache_manager_singleton(self):
        """测试获取单例实例"""
        from platforms.gpt_hero_sms.cache_manager import get_cache_manager
        
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        
        # 应该返回同一个实例
        assert manager1 is manager2
