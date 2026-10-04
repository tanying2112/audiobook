---
title: VoxCPM2 TTS Demo
emoji: 🎙️
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.1
app_file: app.py
pinned: false
license: apache-2.0
---

# VoxCPM2 文本转语音演示 (ModelScope Space)

基于 [OpenBMB/VoxCPM2](https://modelscope.cn/models/OpenBMB/VoxCPM2) 的零样本 TTS 演示，部署在魔搭创空间，享受**免费 xGPU 自动冷启动/自动回收**。

## 使用
1. 在文本框输入中文/英文/混合文本
2. 调整 `steps` (6~15，默认 10，越小越快) 与 `cfg` (1.0~3.5，默认 2.0)
3. 点击 **生成语音**，几秒后播放/下载 WAV

## 环境变量（在 Space 设置里配置）
| 变量 | 默认 | 说明 |
|------|------|------|
| `VOXCPM2_INFERENCE_TIMESTEPS` | 10 | 推理扩散步数，8≈1.13x 加速，质量需试听 |
| `HF_ENDPOINT` | https://hf-mirror.com | HF 镜像加速下载 |

## 持久化模型权重（避免冷启动重下 4.58GB）
在空间设置 → **挂载数据集/模型** → 选择已上传到魔搭的 `OpenBMB/VoxCPM2`（或私有镜像） → 挂载到 `/mnt/data/VoxCPM2`。代码会自动检测该路径。

## 本地开发
```bash
pip install -r requirements.txt
python app.py  # http://localhost:7860
```

## 许可
Apache-2.0 | Model: OpenBMB/VoxCPM2
