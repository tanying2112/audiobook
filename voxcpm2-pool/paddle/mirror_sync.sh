#!/usr/bin/env bash
# 同步 HF 镜像到百度 BOS，在 Job 启动前执行

set -euo pipefail

# Source .env to get credentials
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Use pip with --break-system-packages for macOS
python3 -m pip install boto3 huggingface_hub --break-system-packages -q

python3 -c "
from huggingface_hub import snapshot_download
import os
import sys

# Download model
token = os.getenv('HF_TOKEN', '')
snapshot_download(
    'openbmb/VoxCPM2',
    local_dir='/tmp/voxcpm2-model',
    token=token if token else None
)
print('✅ Model downloaded to /tmp/voxcpm2-model')

# Upload to Baidu BOS
import boto3

# Get credentials from environment (already sourced from .env)
bos_ak = os.getenv('BOS_ACCESS_KEY_ID')
bos_sk = os.getenv('BOS_ACCESS_KEY_SECRET')
bos_endpoint = os.getenv('BOS_ENDPOINT', 'https://bj.bcebos.com')
bos_bucket = os.getenv('BOS_BUCKET', 'voxcpm2-model')

if not bos_ak or not bos_sk:
    print('❌ Missing BOS credentials')
    print(f'  BOS_ACCESS_KEY_ID={bos_ak if bos_ak else \"NOT_SET\"}')
    print(f'  BOS_ACCESS_KEY_SECRET={\"***\" if bos_sk else \"NOT_SET\"}')
    sys.exit(1)

s3 = boto3.client(
    's3',
    endpoint_url=bos_endpoint,
    aws_access_key_id=bos_ak,
    aws_secret_access_key=bos_sk
)

# Upload entire model directory to BOS
import glob
uploaded = 0
for file_path in glob.glob('/tmp/voxcpm2-model/**/*', recursive=True):
    if os.path.isfile(file_path):
        rel_path = os.path.relpath(file_path, '/tmp/voxcpm2-model')
        object_key = f'voxcpm2/{rel_path}'
        print(f'  Uploading {rel_path}...', end=' ')
        s3.upload_file(file_path, bos_bucket, object_key)
        print('OK')
        uploaded += 1

print(f'✅ Uploaded {uploaded} files to bos://{bos_bucket}/voxcpm2/')
"
