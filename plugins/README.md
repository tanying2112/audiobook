# Audiobook Studio 插件生态 (S3.5)

本目录用于存放**用户/社区贡献的插件**。每个插件是一个子目录,内含一个
`manifest.json` 清单文件。系统通过 `discover_plugins()` 自动扫描本目录,
并在「模型市场」(`GET /api/v1/models`)中展示可一键安装的插件。

## 插件清单 (manifest.json) 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 插件唯一标识(子目录名一致) |
| `version` | string | 语义化版本,如 `1.0.0` |
| `type` | string | `tts_voice` / `llm_model` / `pipeline_stage` |
| `description` | string | 人类可读描述 |
| `models` | string[] | 该插件提供的模型/音色 id 列表 |
| `entry` | string | 插件入口模块(可选) |

## 安装

通过模型市场 `POST /api/v1/models/install` 一键安装;安装仅做**注册登记**
(写入 `config/installed_plugins.json`),不触发任何网络下载,完全符合
「仅用免费资源」的约束。TTS 模型权重本身由本地引擎(Kokoro / Edge)在
运行时按需加载。

## 示例

参见 `sample_tts_voice/manifest.json`。
