# PERF-004: ffmpeg 子进程并发控制信号量

## 严重级别
**P1 - Medium** (资源保护 / OOM 防护)

## 问题描述
`src/audiobook_studio/export/m4b.py` `audio_postprocess.py` 并发导出时无限制启动 `ffmpeg` → CPU/Memory 抖动、容器 OOM Kill。

## 修复方案
1. `config/settings.py` 新增：
   ```python
   FFMPEG_CONCURRENCY: int = Field(default=0, alias="FFMPEG_CONCURRENCY")  # 0=auto(cpu_count)
   ```
2. 导出模块统一信号量：
   ```python
   # src/audiobook_studio/export/pool.py
   import asyncio
   from src.audiobook_studio.config import get_settings
   
   _semaphore: asyncio.Semaphore | None = None
   
   def get_ffmpeg_semaphore() -> asyncio.Semaphore:
       global _semaphore
       if _semaphore is None:
           s = get_settings()
           concurrency = s.FFMPEG_CONCURRENCY or max(1, (os.cpu_count() or 2) - 1)
           _semaphore = asyncio.Semaphore(concurrency)
       return _semaphore
   ```
3. `run_ffmpeg()` 包装：
   ```python
   async def run_ffmpeg(args: list[str], ...) -> CompletedProcess:
       sem = get_ffmpeg_semaphore()
       async with sem:
           return await asyncio.create_subprocess_exec(...)
   ```
4. 容器层 `ulimit -v` (Dockerfile `RUN echo "ulimit -v $((2*1024*1024))" >> /etc/profile` 约 2GB)

## 验收标准
- [ ] 并发 10 导出任务：内存稳定 < 2GB、CPU 无抖动
- [ ] 无 OOM Kill、无 `ffmpeg` 僵尸进程
- [ ] 导出队列平均等待时间 < 30s (并发 4 核场景)

## 关联文件
- `src/audiobook_studio/config/settings.py`
- 新建 `src/audiobook_studio/export/pool.py`
- `src/audiobook_studio/export/m4b.py`
- `src/audiobook_studio/pipeline/audio_postprocess.py`
- `Dockerfile` (ulimit)