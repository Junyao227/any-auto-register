"""
手机号缓存管理器演示

演示如何使用 PhoneCacheManager 进行缓存管理。
"""

import time
from platforms.gpt_hero_sms.phone_cache import PhoneCache
from platforms.gpt_hero_sms.cache_manager import get_cache_manager


def demo_basic_usage():
    """演示基本用法"""
    print("=== 基本用法演示 ===\n")
    
    # 获取缓存管理器（单例）
    manager = get_cache_manager()
    
    # 1. 检查缓存（首次应该为空）
    print("1. 检查缓存...")
    cache = manager.get_cache()
    print(f"   当前缓存: {cache}\n")
    
    # 2. 创建新缓存
    print("2. 创建新缓存...")
    new_cache = PhoneCache(
        phone_number="+1234567890",
        activation_id="demo_activation_123",
        acquired_at=time.time(),
        use_count=0,
        used_codes=set()
    )
    manager.set_cache(new_cache)
    print(f"   缓存已创建: {new_cache}\n")
    
    # 3. 获取缓存
    print("3. 获取缓存...")
    cache = manager.get_cache()
    print(f"   当前缓存: {cache}")
    print(f"   剩余时间: {manager.get_remaining_time():.0f} 秒\n")
    
    # 4. 使用缓存（模拟验证码使用）
    print("4. 使用缓存...")
    cache.mark_code_used("123456")
    cache.increment_use_count()
    manager.set_cache(cache)
    print(f"   使用次数: {cache.use_count}")
    print(f"   已使用验证码: {cache.used_codes}\n")
    
    # 5. 检查验证码是否已使用
    print("5. 检查验证码...")
    print(f"   '123456' 已使用: {cache.is_code_used('123456')}")
    print(f"   '789012' 已使用: {cache.is_code_used('789012')}\n")
    
    # 6. 使缓存失效
    print("6. 使缓存失效...")
    manager.invalidate_cache()
    cache = manager.get_cache()
    print(f"   当前缓存: {cache}\n")


def demo_disk_persistence():
    """演示磁盘持久化"""
    print("=== 磁盘持久化演示 ===\n")
    
    # 1. 创建缓存并保存
    print("1. 创建缓存（进程 A）...")
    manager1 = get_cache_manager()
    cache1 = PhoneCache(
        phone_number="+9876543210",
        activation_id="persistent_activation_456",
        acquired_at=time.time(),
        use_count=2,
        used_codes={"111111", "222222"}
    )
    manager1.set_cache(cache1)
    print(f"   缓存已保存: {cache1}")
    print(f"   缓存文件: {manager1.cache_file_path}\n")
    
    # 2. 从磁盘加载（模拟另一个进程）
    print("2. 从磁盘加载（进程 B）...")
    # 注意：实际使用中应该创建新的管理器实例
    # 这里为了演示，直接调用 load_from_disk
    loaded_cache = manager1.load_from_disk()
    print(f"   加载的缓存: {loaded_cache}")
    print(f"   手机号: {loaded_cache.phone_number}")
    print(f"   使用次数: {loaded_cache.use_count}")
    print(f"   已使用验证码: {loaded_cache.used_codes}\n")
    
    # 3. 清理
    print("3. 清理缓存...")
    manager1.invalidate_cache()
    print("   缓存已清除\n")


def demo_cache_expiration():
    """演示缓存过期"""
    print("=== 缓存过期演示 ===\n")
    
    manager = get_cache_manager()
    
    # 1. 创建一个即将过期的缓存（19 分 50 秒前）
    print("1. 创建即将过期的缓存...")
    cache = PhoneCache(
        phone_number="+1111111111",
        activation_id="expiring_activation_789",
        acquired_at=time.time() - 1190,  # 19 分 50 秒前
        use_count=0,
        used_codes=set()
    )
    manager.set_cache(cache)
    print(f"   缓存创建时间: 19 分 50 秒前")
    print(f"   剩余时间: {manager.get_remaining_time():.0f} 秒")
    print(f"   是否过期: {cache.is_expired()}\n")
    
    # 2. 等待缓存过期（模拟）
    print("2. 模拟缓存过期...")
    # 修改缓存时间戳（实际使用中应该等待）
    cache.acquired_at = time.time() - 1210  # 20 分 10 秒前
    manager.set_cache(cache)
    print(f"   缓存创建时间: 20 分 10 秒前")
    print(f"   是否过期: {cache.is_expired()}\n")
    
    # 3. 尝试获取过期缓存
    print("3. 尝试获取过期缓存...")
    retrieved_cache = manager.get_cache()
    print(f"   获取结果: {retrieved_cache}")
    print("   （过期缓存会自动清除）\n")


def demo_thread_safety():
    """演示线程安全"""
    print("=== 线程安全演示 ===\n")
    
    import threading
    
    manager = get_cache_manager()
    results = []
    
    def worker(worker_id):
        """工作线程"""
        for i in range(3):
            # 创建缓存
            cache = PhoneCache(
                phone_number=f"+{worker_id}{i:09d}",
                activation_id=f"worker_{worker_id}_activation_{i}",
                acquired_at=time.time(),
                use_count=i,
                used_codes=set()
            )
            manager.set_cache(cache)
            
            # 读取缓存
            retrieved = manager.get_cache()
            results.append((worker_id, i, retrieved.phone_number if retrieved else None))
            
            time.sleep(0.01)
    
    # 创建多个线程
    print("1. 启动 3 个工作线程...")
    threads = []
    for worker_id in range(3):
        thread = threading.Thread(target=worker, args=(worker_id,))
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    print(f"2. 所有线程完成，共 {len(results)} 次操作")
    print("3. 最终缓存状态:")
    final_cache = manager.get_cache()
    if final_cache:
        print(f"   手机号: {final_cache.phone_number}")
        print(f"   使用次数: {final_cache.use_count}")
    else:
        print("   无缓存")
    print()
    
    # 清理
    manager.invalidate_cache()


def main():
    """主函数"""
    print("\n" + "="*60)
    print("手机号缓存管理器演示")
    print("="*60 + "\n")
    
    try:
        # 1. 基本用法
        demo_basic_usage()
        
        # 2. 磁盘持久化
        demo_disk_persistence()
        
        # 3. 缓存过期
        demo_cache_expiration()
        
        # 4. 线程安全
        demo_thread_safety()
        
        print("="*60)
        print("演示完成！")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 演示过程中发生错误: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
