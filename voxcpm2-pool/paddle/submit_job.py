#!/usr/bin/env python3
# submit_paddle_job.py
# Submit job to Baidu AI Studio using their REST API

import base64
import json
import os

import requests

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Configuration
BOS_AK = os.getenv("BOS_ACCESS_KEY_ID")
BOS_SK = os.getenv("BOS_ACCESS_KEY_SECRET")
BOS_ENDPOINT = os.getenv("BOS_ENDPOINT", "https://bj.bcebos.com")
BOS_BUCKET = os.getenv("BOS_BUCKET", "voxcpm2-model")

print("配置信息:")
print(f"  BOS_BUCKET: {BOS_BUCKET}")
print(f"  R2_ENDPOINT: {os.getenv('R2_ENDPOINT')}")
print(f"  R2_BUCKET: {os.getenv('R2_BUCKET')}")

# 如果有百度云 AISTUDIO_API_TOKEN，可以用 API 提交作业
# 否则建议直接在 https://aistudio.baidu.com 网页上：
# 1. 新建项目
# 2. 上传代码
# 3. 选择 GPU 规格
# 4. 挂载 BOS 数据集
# 4. 运行 worker.py

print(
    """
📋 百度飞桨 AI Studio 手动部署步骤：

1. 打开 https://aistudio.baidu.com/
2. 右上角登录 -> 个人中心 -> 账号设置 -> 获取 Access Token
3. 创建项目 -> 导入 GitHub 仓库或上传代码
3. 在项目中创建 Notebook 或 任务
4. 环境选择：GPU V100 / A100
5. 挂载数据集：
   - 数据集来源：对象存储 BOS
   - Bucket: voxcpm2-model
   - 挂载路径: /home/aistudio/data
7. 运行命令：
   pip install -r requirements.txt
   python kaggle_worker.py

或者使用 CLI（需要安装 paddlectl）：
  paddlectl login --access-key {AK} --secret-key {SK}
  paddlectl job create -f paddle_job.yaml
"""
)

# If you have AISTUDIO_API_TOKEN, you can use the API directly
# This is just a placeholder for future automation
print("\n🔧 建议：直接在 https://aistudio.baidu.com 网页界面操作会更可靠")
