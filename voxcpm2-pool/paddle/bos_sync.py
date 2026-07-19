import os
import sys
from pathlib import Path

try:
    from baidubce.auth.bce_credentials import BceCredentials

    # 注意这里：修复了拼写错别字 configuration
    from baidubce.bce_client_configuration import BceClientConfiguration
    from baidubce.services.bos.bos_client import BosClient
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ 依赖导入错误: {e}")
    print("请确保在当前虚拟环境下运行了 `uv pip install bce-python-sdk python-dotenv`")
    sys.exit(1)

# 加载 secrets_setup.sh 生成的 .env
load_dotenv()

# 配置本地模型路径
LOCAL_MODEL_DIR = Path("/tmp/voxcpm2-model")

# 1. 读取百度云凭证
BOS_AK = os.getenv("BOS_ACCESS_KEY_ID")
BOS_SK = os.getenv("BOS_ACCESS_KEY_SECRET")  # .env uses BOS_ACCESS_KEY_SECRET
BUCKET_NAME = os.getenv("BOS_BUCKET")
ENDPOINT = os.getenv("BOS_ENDPOINT", "https://bj.bcebos.com")

if not all([BOS_AK, BOS_SK, BUCKET_NAME]):
    print("❌ 错误：.env 文件中缺少凭证！请确保包含 BOS_ACCESS_KEY_ID, BOS_ACCESS_KEY_SECRET, BOS_BUCKET")
    sys.exit(1)

if not LOCAL_MODEL_DIR.exists():
    print(f"❌ 错误：在本地未找到模型目录 {LOCAL_MODEL_DIR}")
    sys.exit(1)

# 2. 初始化百度 BOS 客户端 (类名也对应修正为 BceClientConfiguration)
config = BceClientConfiguration(credentials=BceCredentials(BOS_AK, BOS_SK), endpoint=ENDPOINT)
client = BosClient(config)

print(f"🚀 开始同步模型到百度云存储: bos://{BUCKET_NAME}/voxcpm2/")

# 3. 递归遍历并上传整个模型目录
for file_path in LOCAL_MODEL_DIR.rglob("*"):
    if file_path.is_file():
        # 计算在云端的相对路径
        rel_path = file_path.relative_to(LOCAL_MODEL_DIR.parent)
        object_key = f"voxcpm2/{rel_path}"

        print(f"📦 正在上传: {file_path.name} -> {object_key}")
        try:
            client.put_object_from_file(BUCKET_NAME, object_key, str(file_path))
        except Exception as e:
            print(f"❌ 上传失败 {file_path.name}: {e}")
            sys.exit(1)

print("\n🎉 百度 BOS 模型权重已全部 100% 同步成功！")
