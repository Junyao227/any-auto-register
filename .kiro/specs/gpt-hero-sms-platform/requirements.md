# Requirements Document

## Introduction

本文档定义了在 any-auto-register 项目中集成 gpt-sms 项目的 HeroSMS 接码功能作为新平台选项的需求。该功能将允许用户通过 HeroSMS 接码平台进行 ChatGPT 账号注册，并在前端平台管理界面中作为独立的平台选项 "GPT (Hero接码)" 显示。

## Glossary

- **Platform**: 平台，指 any-auto-register 系统中支持的注册服务（如 ChatGPT、Grok、Kiro 等）
- **Platform_Plugin**: 平台插件，位于 platforms/ 目录下的 Python 模块，实现特定平台的注册逻辑
- **Registry**: 注册表，负责自动扫描和加载平台插件的核心模块
- **HeroSMS**: HeroSMS 接码平台，提供虚拟手机号码用于接收短信验证码
- **Frontend_Settings**: 前端设置页面，用于配置各平台的注册参数
- **BasePlatform**: 平台插件基类，定义平台插件必须实现的接口
- **Account**: 账号对象，包含平台、邮箱、密码、Token 等信息
- **RegisterConfig**: 注册配置对象，包含执行器类型、验证码解决器、代理等配置
- **HeroSMSClient**: HeroSMS API 客户端，封装与 HeroSMS 平台的交互逻辑

## Requirements

### Requirement 1: 创建 GPT Hero SMS 平台插件

**User Story:** 作为开发者，我希望创建一个新的平台插件来集成 HeroSMS 接码功能，以便用户可以使用 HeroSMS 进行 ChatGPT 账号注册

#### Acceptance Criteria

1. THE Platform_Plugin SHALL be created at path `platforms/gpt_hero_sms/plugin.py`
2. THE Platform_Plugin SHALL inherit from BasePlatform class
3. THE Platform_Plugin SHALL define name as "gpt_hero_sms"
4. THE Platform_Plugin SHALL define display_name as "GPT (Hero接码)"
5. THE Platform_Plugin SHALL define version as "1.0.0"
6. THE Platform_Plugin SHALL implement the register method accepting email and password parameters
7. THE Platform_Plugin SHALL implement the check_valid method accepting an Account parameter
8. THE Platform_Plugin SHALL be decorated with @register decorator to enable automatic registration

### Requirement 2: 集成 HeroSMS 客户端

**User Story:** 作为开发者，我希望在新平台插件中集成 HeroSMS 客户端，以便实现手机验证码接收功能

#### Acceptance Criteria

1. THE Platform_Plugin SHALL import HeroSMSClient from gpt-sms project
2. WHEN register method is called, THE Platform_Plugin SHALL read HeroSMS configuration from RegisterConfig.extra
3. THE Platform_Plugin SHALL read herosms_api_key from configuration
4. THE Platform_Plugin SHALL read herosms_service from configuration with default value "dr"
5. THE Platform_Plugin SHALL read herosms_country from configuration with default value 187
6. THE Platform_Plugin SHALL read herosms_max_price from configuration with default value -1
7. WHEN herosms_api_key is empty, THE Platform_Plugin SHALL raise a configuration error
8. THE Platform_Plugin SHALL create HeroSMSClient instance with api_key and proxy parameters

### Requirement 3: 实现 ChatGPT 注册流程

**User Story:** 作为用户，我希望通过 HeroSMS 接码完成 ChatGPT 账号注册，以便获得可用的 ChatGPT 账号

#### Acceptance Criteria

1. WHEN register method is called, THE Platform_Plugin SHALL reuse ChatGPT registration adapter from chatgpt platform
2. THE Platform_Plugin SHALL integrate HeroSMS phone verification into the registration flow
3. WHEN phone verification is required, THE Platform_Plugin SHALL call handle_add_phone_with_herosms function
4. WHEN registration succeeds, THE Platform_Plugin SHALL return an Account object with platform set to "gpt_hero_sms"
5. THE Account SHALL contain email, password, and access_token in extra field
6. WHEN registration fails, THE Platform_Plugin SHALL raise RuntimeError with error message

### Requirement 4: 实现账号有效性检查

**User Story:** 作为系统，我希望能够检查 GPT Hero SMS 账号的有效性，以便识别失效账号

#### Acceptance Criteria

1. WHEN check_valid method is called, THE Platform_Plugin SHALL verify the Account has valid access_token
2. THE Platform_Plugin SHALL return True when access_token exists in Account.extra
3. THE Platform_Plugin SHALL return False when access_token is missing or empty

### Requirement 5: 前端平台列表显示

**User Story:** 作为用户，我希望在前端平台管理界面看到 "GPT (Hero接码)" 选项，以便选择该平台进行注册

#### Acceptance Criteria

1. WHEN Frontend loads platform list, THE Frontend SHALL call /api/platforms endpoint
2. THE /api/platforms endpoint SHALL return platform list including gpt_hero_sms
3. THE Frontend SHALL display "GPT (Hero接码)" in platform selection dropdown
4. THE Platform SHALL appear alongside other platforms like ChatGPT, Grok, Kiro

### Requirement 6: 前端配置界面

**User Story:** 作为用户，我希望在前端设置页面配置 HeroSMS 参数，以便自定义接码行为

#### Acceptance Criteria

1. THE Frontend_Settings SHALL add a new configuration section titled "HeroSMS 接码配置"
2. THE Configuration_Section SHALL include input field for herosms_api_key with label "HeroSMS API Key"
3. THE Configuration_Section SHALL include input field for herosms_service with label "服务代码" and default value "dr"
4. THE Configuration_Section SHALL include input field for herosms_country with label "国家 ID" and default value "187"
5. THE Configuration_Section SHALL include input field for herosms_max_price with label "最高单价" and default value "-1"
6. THE herosms_api_key field SHALL use password input type to hide the API key
7. WHEN user saves configuration, THE Frontend SHALL send configuration to backend API

### Requirement 7: 配置持久化

**User Story:** 作为系统，我希望保存用户配置的 HeroSMS 参数，以便在注册任务中使用

#### Acceptance Criteria

1. WHEN user saves HeroSMS configuration, THE Backend SHALL store configuration in config_store
2. THE Backend SHALL persist herosms_api_key to configuration storage
3. THE Backend SHALL persist herosms_service to configuration storage
4. THE Backend SHALL persist herosms_country to configuration storage
5. THE Backend SHALL persist herosms_max_price to configuration storage
6. WHEN Platform_Plugin reads configuration, THE Backend SHALL provide stored values from config_store

### Requirement 8: 手机号码复用机制

**User Story:** 作为用户，我希望系统能够复用 HeroSMS 手机号码，以便降低接码成本

#### Acceptance Criteria

1. THE Platform_Plugin SHALL reuse handle_add_phone_with_herosms function from gpt-sms project
2. THE Phone_Reuse_Mechanism SHALL cache phone numbers for 20 minutes
3. WHEN a phone number is cached, THE Platform_Plugin SHALL reuse it for subsequent registrations
4. THE Platform_Plugin SHALL track used verification codes to avoid code reuse
5. WHEN phone cache expires, THE Platform_Plugin SHALL request a new phone number from HeroSMS
6. THE Platform_Plugin SHALL persist phone cache to disk for cross-process reuse

### Requirement 9: 错误处理

**User Story:** 作为用户，我希望系统能够妥善处理注册过程中的错误，以便了解失败原因

#### Acceptance Criteria

1. WHEN HeroSMS API key is missing, THE Platform_Plugin SHALL raise RuntimeError with message "HeroSMS API Key 未配置"
2. WHEN HeroSMS request_number fails, THE Platform_Plugin SHALL raise RuntimeError with error details
3. WHEN phone verification timeout occurs, THE Platform_Plugin SHALL raise RuntimeError with message "手机验证超时"
4. WHEN OpenAI rejects phone number, THE Platform_Plugin SHALL request a new number and retry
5. WHEN registration fails after all retries, THE Platform_Plugin SHALL raise RuntimeError with final error message

### Requirement 10: 日志记录

**User Story:** 作为开发者，我希望系统记录详细的注册日志，以便调试和监控

#### Acceptance Criteria

1. THE Platform_Plugin SHALL log HeroSMS phone number acquisition
2. THE Platform_Plugin SHALL log phone verification code reception
3. THE Platform_Plugin SHALL log phone verification success or failure
4. THE Platform_Plugin SHALL log phone cache reuse events
5. THE Platform_Plugin SHALL log configuration errors
6. THE Platform_Plugin SHALL use the _log_fn callback when available for logging

### Requirement 11: 平台操作支持

**User Story:** 作为用户，我希望能够对 GPT Hero SMS 账号执行额外操作，以便管理账号生命周期

#### Acceptance Criteria

1. THE Platform_Plugin SHALL implement get_platform_actions method
2. THE Platform_Plugin SHALL return action list including "refresh_token" action
3. THE Platform_Plugin SHALL return action list including "probe_local_status" action
4. THE Platform_Plugin SHALL implement execute_action method to handle action execution
5. WHEN "refresh_token" action is executed, THE Platform_Plugin SHALL refresh the Account access_token
6. WHEN "probe_local_status" action is executed, THE Platform_Plugin SHALL check Account authentication status

### Requirement 12: 代理支持

**User Story:** 作为用户，我希望系统支持通过代理访问 HeroSMS 和 OpenAI，以便在网络受限环境中使用

#### Acceptance Criteria

1. WHEN RegisterConfig contains proxy setting, THE Platform_Plugin SHALL pass proxy to HeroSMSClient
2. WHEN RegisterConfig contains proxy setting, THE Platform_Plugin SHALL pass proxy to ChatGPT registration adapter
3. THE Platform_Plugin SHALL support HTTP proxy format
4. THE Platform_Plugin SHALL support SOCKS5 proxy format
5. WHEN proxy is not configured, THE Platform_Plugin SHALL use direct connection

