# Bugfix Requirements Document

## Introduction

HeroSMS 号码复用功能完全失效，导致每次注册都请求新号码并产生不必要的费用。HeroSMS 按激活（activation）收费（每次约 $0.05），一个 activation 可以在 20 分钟内接收多个验证码。当前问题是 8 次注册产生了 8 条激活记录（费用 $0.40），而预期应该只有 1-2 条激活记录（费用 $0.05-$0.10）。

根本原因是 `any-auto-register/platforms/gpt_hero_sms/phone_verification.py` 使用的是内存缓存实现（`_local_phone_cache`），缺少磁盘持久化功能，导致进程重启后缓存丢失，多个注册任务无法共享缓存。

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 多个注册任务在 20 分钟内执行 THEN 系统为每个任务请求新的 HeroSMS 号码（产生多条激活记录）

1.2 WHEN 注册进程重启后再次执行注册任务 THEN 系统无法读取之前的缓存号码，必须请求新号码

1.3 WHEN 缓存的号码信息存储在 `_local_phone_cache` 变量中 THEN 缓存仅存在于内存中，进程结束后丢失

1.4 WHEN 8 次注册任务执行 THEN 系统产生 8 条 HeroSMS 激活记录，费用为 $0.40

### Expected Behavior (Correct)

2.1 WHEN 多个注册任务在 20 分钟内执行 THEN 系统 SHALL 复用同一个 HeroSMS 号码（仅产生 1 条激活记录）

2.2 WHEN 注册进程重启后再次执行注册任务（距离上次获取号码不超过 20 分钟）THEN 系统 SHALL 从磁盘加载缓存的号码信息并复用

2.3 WHEN 缓存的号码信息需要持久化 THEN 系统 SHALL 将缓存保存到 `CPAP/any-auto-register/data/.herosms_phone_cache.json` 文件

2.4 WHEN 8 次注册任务在 20 分钟内执行 THEN 系统 SHALL 仅产生 1-2 条 HeroSMS 激活记录，费用降低到 $0.05-$0.10

2.5 WHEN 缓存的号码超过 20 分钟有效期 THEN 系统 SHALL 自动删除过期的缓存文件并请求新号码

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 缓存的号码在 20 分钟内仍然有效 THEN 系统 SHALL CONTINUE TO 使用 `_local_phone_verify_lock` 序列化验证流程

3.2 WHEN 验证码接收超时或验证失败 THEN 系统 SHALL CONTINUE TO 清除缓存并重试新号码

3.3 WHEN 号码验证成功 THEN 系统 SHALL CONTINUE TO 更新缓存的 `use_count` 和 `used_codes` 字段

3.4 WHEN 使用缓存的号码进行验证 THEN 系统 SHALL CONTINUE TO 跳过 `used_codes` 集合中已使用的验证码

3.5 WHEN HeroSMS 客户端调用 `request_number()`, `wait_for_code()`, `set_status()` 等方法 THEN 系统 SHALL CONTINUE TO 保持现有的调用逻辑和参数
