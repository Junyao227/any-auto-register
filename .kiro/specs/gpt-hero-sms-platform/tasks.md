# Implementation Plan: GPT Hero SMS Platform

## Overview

本实现计划将 HeroSMS 接码平台集成到 any-auto-register 项目中，作为新的平台插件 "GPT (Hero接码)"。实现将复用现有的 ChatGPT 注册逻辑和 gpt-sms 项目的 HeroSMS 客户端，支持手机号缓存复用机制，并提供前端配置界面。

## Tasks

- [x] 1. 创建 GPT Hero SMS 平台插件基础结构
  - 创建 `platforms/gpt_hero_sms/` 目录
  - 创建 `platforms/gpt_hero_sms/__init__.py` 文件
  - 创建 `platforms/gpt_hero_sms/plugin.py` 文件，定义 GPTHeroSMSPlatform 类
  - 实现 BasePlatform 接口（name, display_name, version 属性）
  - 添加 @register 装饰器以自动注册到平台注册表
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.8_

- [ ] 2. 实现 HeroSMS 集成模块
  - [x] 2.1 创建 HeroSMS 集成模块文件
    - 创建 `platforms/gpt_hero_sms/herosms_integration.py` 文件
    - 导入 gpt-sms 项目的 HeroSMSClient 和相关函数
    - _Requirements: 2.1_

  - [x] 2.2 实现 HeroSMS 配置读取和验证
    - 实现 `_read_herosms_config()` 方法读取配置
    - 从 RegisterConfig.extra 读取 herosms_api_key, herosms_service, herosms_country, herosms_max_price
    - 实现配置验证逻辑，API Key 为空时抛出错误
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.3 实现手机验证回调函数
    - 实现 `create_herosms_phone_callback()` 函数
    - 封装 gpt-sms 项目的 `handle_add_phone_with_herosms` 函数
    - 处理手机号获取、验证码接收、验证码提交流程
    - 添加日志记录（手机号获取、验证码接收、验证成功/失败）
    - _Requirements: 3.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.1, 10.2, 10.3, 10.6_

  - [x] 2.4 实现回调注入函数
    - 实现 `inject_herosms_to_registration_engine()` 函数
    - 将 HeroSMS 回调注入到 ChatGPT 注册引擎中
    - _Requirements: 3.3_

- [ ] 3. 实现平台插件核心方法
  - [x] 3.1 实现 register 方法
    - 生成随机密码（如果未提供）
    - 读取 HeroSMS 配置并验证
    - 创建 HeroSMSClient 实例
    - 复用 ChatGPT 注册适配器（build_chatgpt_registration_mode_adapter）
    - 创建邮箱服务（复用 ChatGPT 平台逻辑）
    - 创建 ChatGPTRegistrationContext 上下文
    - 注入 HeroSMS 手机验证回调
    - 执行注册流程
    - 构建并返回 Account 对象（platform="gpt_hero_sms"）
    - _Requirements: 1.6, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.2 实现 check_valid 方法
    - 检查 Account.extra 中是否存在 access_token
    - 返回 True（有效）或 False（无效）
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 3.3 实现 get_platform_actions 方法
    - 返回平台支持的操作列表
    - 包含 "refresh_token" 和 "probe_local_status" 操作
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 3.4 实现 execute_action 方法
    - 处理 "refresh_token" 操作（刷新 access_token）
    - 处理 "probe_local_status" 操作（检查账号状态）
    - _Requirements: 11.4, 11.5, 11.6_

- [ ] 4. 实现手机号缓存机制
  - [x] 4.1 创建手机号缓存管理模块
    - 创建 `platforms/gpt_hero_sms/phone_cache.py` 文件
    - 定义手机号缓存数据结构（phone_number, activation_id, acquired_at, use_count, used_codes）
    - _Requirements: 8.1, 8.2_

  - [x] 4.2 实现缓存读写逻辑
    - 实现内存缓存（使用 dict）
    - 实现磁盘持久化（保存到 `data/.herosms_phone_cache.json`）
    - 实现缓存加载和保存函数
    - 添加线程锁保护缓存操作
    - _Requirements: 8.6_

  - [x] 4.3 实现缓存生命周期管理
    - 实现 20 分钟缓存过期逻辑
    - 实现缓存命中检查（检查是否过期）
    - 实现缓存失效清理
    - _Requirements: 8.2, 8.3, 8.5_

  - [x] 4.4 集成缓存到手机验证流程
    - 在 `create_herosms_phone_callback()` 中集成缓存检查
    - 缓存命中时复用手机号
    - 缓存未命中时请求新手机号并缓存
    - 记录已使用的验证码，避免重复使用
    - 添加缓存复用日志
    - _Requirements: 8.3, 8.4, 10.4_

- [ ] 5. 实现错误处理和重试逻辑
  - [x] 5.1 定义错误类型
    - 创建 `platforms/gpt_hero_sms/exceptions.py` 文件
    - 定义 GPTHeroSMSError 基类
    - 定义 HeroSMSConfigError（配置错误）
    - 定义 HeroSMSAPIError（API 错误）
    - 定义 PhoneVerificationError（手机验证错误）
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 10.5_

  - [x] 5.2 实现错误处理逻辑
    - 在 register 方法中添加 try-except 错误处理
    - 捕获配置错误并抛出清晰的错误信息
    - 捕获 HeroSMS API 错误并记录日志
    - 捕获手机验证错误并处理重试
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 5.3 实现重试策略
    - 手机号被拒绝时清除缓存并重试（最多 2 次）
    - 验证码提交失败时根据错误类型决定是否重试
    - 注册流程失败时根据配置的最大重试次数重试
    - _Requirements: 9.4, 9.5_

- [x] 6. Checkpoint - 后端核心功能验证
  - 确保所有后端核心功能测试通过
  - 验证平台插件能够正确注册到注册表
  - 验证 HeroSMS 配置读取和验证逻辑
  - 验证手机号缓存机制工作正常
  - 如有问题请向用户反馈

- [ ] 7. 实现前端配置界面
  - [x] 7.1 添加 HeroSMS 配置节到 Settings 页面
    - 打开 `frontend/src/pages/Settings.tsx` 文件
    - 在 TAB_ITEMS 中添加新的配置节 "HeroSMS 接码"
    - 添加配置字段：herosms_api_key（密码输入框）、herosms_service（文本输入框，默认 "dr"）、herosms_country（数字输入框，默认 187）、herosms_max_price（数字输入框，默认 -1）
    - 添加字段说明和提示信息
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.2 实现配置保存逻辑
    - 确保配置保存时调用 `/api/config` 接口
    - 验证配置字段格式（API Key 必填，其他字段类型正确）
    - 添加保存成功/失败提示
    - _Requirements: 6.7, 7.1_

  - [x] 7.3 实现配置加载逻辑
    - 页面加载时从 `/api/config` 接口读取配置
    - 填充配置字段的默认值
    - _Requirements: 7.6_

- [ ] 8. 实现后端配置持久化
  - [x] 8.1 验证配置存储接口
    - 确认 `/api/config` 接口支持 HeroSMS 配置字段
    - 验证配置保存到 config_store
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 8.2 实现配置读取逻辑
    - 在 GPTHeroSMSPlatform 中从 RegisterConfig.extra 读取配置
    - 确保配置正确传递到注册流程
    - _Requirements: 7.6_

- [ ] 9. 实现平台列表显示
  - [x] 9.1 验证平台自动注册
    - 确认 GPTHeroSMSPlatform 使用 @register 装饰器
    - 验证平台在 `/api/platforms` 接口返回的列表中
    - _Requirements: 5.1, 5.2_

  - [x] 9.2 验证前端平台显示
    - 确认前端平台选择下拉框中显示 "GPT (Hero接码)"
    - 验证平台与其他平台（ChatGPT、Grok、Kiro）一起显示
    - _Requirements: 5.3, 5.4_

- [ ] 10. 实现代理支持
  - [x] 10.1 添加代理配置传递
    - 在创建 HeroSMSClient 时传递 proxy 参数
    - 在创建 ChatGPT 注册上下文时传递 proxy_url 参数
    - _Requirements: 12.1, 12.2_

  - [x] 10.2 验证代理格式支持
    - 验证支持 HTTP 代理格式
    - 验证支持 SOCKS5 代理格式
    - 验证未配置代理时使用直连
    - _Requirements: 12.3, 12.4, 12.5_

- [x] 11. Checkpoint - 功能集成验证
  - 确保前后端集成正常
  - 验证配置界面能够正确保存和加载配置
  - 验证平台在前端列表中正确显示
  - 验证代理支持正常工作
  - 如有问题请向用户反馈

- [ ] 12. 编写单元测试
  - [x] 12.1 测试平台插件初始化
    - 测试使用有效配置初始化
    - 测试缺少 API Key 时的错误处理
    - 测试配置验证逻辑
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 12.2 测试 register 方法
    - 使用 Mock 测试注册成功流程
    - 测试配置错误处理
    - 测试 HeroSMS API 错误处理
    - 测试手机验证失败处理
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 12.3 测试 check_valid 方法
    - 测试有效 Token 的账号检查
    - 测试无效 Token 的账号检查
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 12.4 测试 HeroSMS 集成模块
    - 使用 Mock 测试手机验证回调成功
    - 使用 Mock 测试手机验证回调失败
    - 测试回调注入逻辑
    - _Requirements: 3.3, 8.1, 8.2, 8.3_

  - [x] 12.5 测试手机号缓存机制
    - 测试缓存创建和保存
    - 测试缓存加载和复用
    - 测试缓存过期逻辑
    - 测试缓存持久化
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 12.6 测试错误处理
    - 测试各种错误类型的处理
    - 测试错误信息的清晰度
    - 测试重试逻辑
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ] 13. 编写集成测试
  - [x] 13.1 测试平台注册表集成
    - 测试平台自动注册到注册表
    - 测试从注册表获取平台
    - _Requirements: 5.1, 5.2_

  - [x] 13.2 测试配置持久化集成
    - 测试保存 HeroSMS 配置
    - 测试加载 HeroSMS 配置
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 13.3 测试手机号缓存跨进程共享
    - 测试缓存文件创建
    - 测试跨进程缓存加载
    - 测试缓存内容正确性
    - _Requirements: 8.6_

- [ ] 14. 最终集成和文档
  - [x] 14.1 验证完整注册流程
    - 手动测试首次注册（无缓存）
    - 手动测试缓存复用注册（20 分钟内）
    - 手动测试缓存过期后注册
    - 验证日志输出完整性
    - 验证错误提示清晰度
    - _Requirements: 所有需求_

  - [x] 14.2 更新项目文档
    - 在 README.md 中添加 GPT Hero SMS 平台说明
    - 添加 HeroSMS 配置指南
    - 添加使用示例和注意事项
    - _Requirements: 所有需求_

  - [x] 14.3 创建部署检查清单
    - 确认 gpt-sms 项目依赖可导入
    - 确认前端配置界面正常显示
    - 确认平台在列表中正确显示
    - 确认配置持久化正常工作
    - _Requirements: 所有需求_

- [x] 15. Final Checkpoint - 完整功能验证
  - 确保所有测试通过
  - 确保文档完整
  - 确保部署检查清单完成
  - 向用户确认功能符合预期
  - 如有问题请向用户反馈

## Notes

- 任务标记 `*` 的为可选任务（主要是测试相关），可以跳过以加快 MVP 开发
- 每个任务都引用了具体的需求编号，确保需求覆盖的可追溯性
- Checkpoint 任务用于在关键节点验证功能，确保增量开发的质量
- 手机号缓存机制是核心特性，需要特别注意缓存生命周期和跨进程共享
- 错误处理和日志记录对于调试和用户体验至关重要
- 前端配置界面需要与后端配置存储保持一致
- 代理支持需要在 HeroSMS 客户端和 ChatGPT 注册引擎中都正确配置
