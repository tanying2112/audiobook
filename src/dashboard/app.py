"""
Hermes Dashboard — Real-time Fleet & Task Monitoring for Multi-Cloud VoxCPM2 TTS.

Streamlit-based dashboard displaying:
- Worker fleet health (per-platform)
- Queue depth & throughput
- Task status distribution
- GPU utilization heatmap
- Alert banner for queue > 50 with zero active workers
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import plotly.express as px
import plotly.graph_objects as go
import redis
import requests
import streamlit as st

# Page config
st.set_page_config(
    page_title="Hermes Dashboard — VoxCPM2 Fleet Monitor",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Constants
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_AUTH = os.getenv("REDIS_AUTH", "")
REFRESH_INTERVAL = int(os.getenv("DASHBOARD_REFRESH", "5"))  # seconds
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")  # For quality report API calls

# Platform routing priority (for display ordering)
PLATFORM_ORDER = ["modal", "baidu", "lightning", "kaggle"]
PLATFORM_COLORS = {
    "modal": "#FF6B6B",
    "baidu": "#4ECDC4",
    "lightning": "#45B7D1",
    "kaggle": "#96CEB4",
}
PLATFORM_ICONS = {
    "modal": "☁️",
    "baidu": "🐉",
    "lightning": "⚡",
    "kaggle": "📊",
}


@dataclass
class DashboardConfig:
    """Dashboard configuration from environment."""

    redis_host: str = REDIS_HOST
    redis_port: int = REDIS_PORT
    redis_auth: str = REDIS_AUTH
    refresh_interval: int = REFRESH_INTERVAL
    api_base_url: str = API_BASE_URL


@st.cache_resource
def get_redis_client(config: DashboardConfig) -> redis.Redis:
    """Cached Redis client."""
    return redis.Redis(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_auth or None,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def scan_worker_heartbeats(redis_client: redis.Redis) -> List[Dict[str, Any]]:
    """Scan all worker heartbeats using SCAN (production-safe)."""
    workers = []
    cursor = 0

    while True:
        cursor, keys = redis_client.scan(
            cursor=cursor,
            match="worker:heartbeat:*",
            count=100,
        )
        if keys:
            pipe = redis_client.mget(keys)
            for key, raw in zip(keys, pipe):
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    platform = key.split(":")[-1].split("-")[0]
                    workers.append(
                        {
                            "worker_id": data["worker_id"],
                            "platform": platform,
                            "status": data["status"],
                            "gpu_mem_used_mb": data["gpu_metrics"].get("gpu_mem_used_mb", 0),
                            "gpu_mem_total_mb": data["gpu_metrics"].get("gpu_mem_total_mb", 0),
                            "device_name": data["gpu_metrics"].get("device_name", "UNKNOWN"),
                            "backend": data["gpu_metrics"].get("backend"),
                            "queue_depth": data.get("queue_depth", 0),
                            "ts": data["ts"],
                            "studio_id": data.get("studio_id", "unknown"),
                            "idle_timeout": data.get("idle_timeout", 900),
                        }
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    st.warning(f"Malformed heartbeat {key}: {e}")

        if cursor == 0:
            break

    return workers


def get_queue_depth(redis_client: redis.Redis) -> int:
    """Get pending task queue depth."""
    try:
        return redis_client.llen("tts:tasks")
    except Exception:
        return -1


def get_results_count(redis_client: redis.Redis) -> int:
    """Get completed results count."""
    try:
        return redis_client.llen("tts:results")
    except Exception:
        return -1


def get_task_states(redis_client: redis.Redis, limit: int = 200) -> Dict[str, int]:
    """Scan task states for distribution chart."""
    states = {"PENDING": 0, "CLAIMED": 0, "SYNTHESIZING": 0, "UPLOADING": 0, "COMPLETED": 0, "FAILED": 0}
    cursor = 0
    scanned = 0

    while scanned < limit:
        cursor, keys = redis_client.scan(cursor=cursor, match="tts:task:*", count=50)
        if keys:
            pipe = redis_client.mget(keys)
            for raw in pipe:
                if raw:
                    try:
                        data = json.loads(raw)
                        state = data.get("state", "UNKNOWN")
                        if state in states:
                            states[state] += 1
                    except Exception:
                        pass
            scanned += len(keys)

        if cursor == 0:
            break

    return states


def compute_fleet_metrics(workers: List[Dict], now: float) -> Dict[str, Any]:
    """Compute aggregated fleet metrics."""
    by_platform = {}
    total = len(workers)
    active = 0
    stale = 0

    for w in workers:
        p = w["platform"]
        if p not in by_platform:
            by_platform[p] = {
                "count": 0,
                "active": 0,
                "stale": 0,
                "total_gpu_mb": 0,
                "used_gpu_mb": 0,
                "workers": [],
            }

        by_platform[p]["count"] += 1
        by_platform[p]["total_gpu_mb"] += w["gpu_mem_total_mb"]
        by_platform[p]["used_gpu_mb"] += w["gpu_mem_used_mb"]
        by_platform[p]["workers"].append(w)

        if w["status"] == "processing":
            by_platform[p]["active"] += 1
            active += 1

        age = now - w["ts"]
        is_stale = age > w["idle_timeout"] + 60  # TTL buffer
        if is_stale:
            by_platform[p]["stale"] += 1
            stale += 1

    # Compute utilization per platform
    for p, data in by_platform.items():
        if data["total_gpu_mb"] > 0:
            data["gpu_utilization"] = data["used_gpu_mb"] / data["total_gpu_mb"]
        else:
            data["gpu_utilization"] = 0

    return {
        "total_workers": total,
        "active_workers": active,
        "stale_workers": stale,
        "by_platform": by_platform,
    }


# --- UI Components ---


def render_header():
    """Render dashboard header with title and refresh control."""
    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        st.title("🎙️ Hermes Dashboard — VoxCPM2 Fleet Monitor")

    with col2:
        auto_refresh = st.checkbox("Auto-refresh", value=True)

    with col3:
        if st.button("🔄 Refresh Now"):
            st.rerun()

    if auto_refresh:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()


def render_alert_banner(metrics: Dict, queue_depth: int):
    """Render alert banner for critical conditions."""
    alerts = []

    # Alert: Queue backing up with no workers
    if queue_depth > 50 and metrics["active_workers"] == 0 and metrics["total_workers"] > 0:
        alerts.append(
            {
                "type": "error",
                "message": f"🚨 **CRITICAL**: Queue depth {queue_depth} with {metrics['total_workers']} workers online but **0 active**!",
            }
        )

    # Alert: All workers stale
    if metrics["total_workers"] > 0 and metrics["stale_workers"] == metrics["total_workers"]:
        alerts.append(
            {
                "type": "error",
                "message": f"🚨 **ALL {metrics['total_workers']} WORKERS STALE** — Fleet appears dead!",
            }
        )

    # Alert: Some workers stale
    elif metrics["stale_workers"] > 0:
        alerts.append(
            {
                "type": "warning",
                "message": f"⚠️ {metrics['stale_workers']}/{metrics['total_workers']} workers stale (no heartbeat > TTL)",
            }
        )

    # Alert: No workers at all
    elif metrics["total_workers"] == 0:
        alerts.append(
            {
                "type": "warning",
                "message": "⚠️ **NO WORKERS ONLINE** — Fleet is offline. Check platform deployments.",
            }
        )

    # Render alerts
    for alert in alerts:
        if alert["type"] == "error":
            st.error(alert["message"], icon="🚨")
        else:
            st.warning(alert["message"], icon="⚠️")


def render_metrics_grid(metrics: Dict, queue_depth: int, results_count: int):
    """Render top-level metrics grid."""
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("👥 Total Workers", metrics["total_workers"])

    with col2:
        st.metric("⚡ Active Workers", metrics["active_workers"])

    with col3:
        st.metric("📦 Queue Depth", queue_depth, delta=None if queue_depth >= 0 else "N/A")

    with col4:
        st.metric("✅ Completed", results_count)

    with col5:
        st.metric("💀 Stale Workers", metrics["stale_workers"], delta_color="inverse")


def render_platform_cards(metrics: Dict):
    """Render per-platform health cards."""
    st.subheader("🌐 Platform Fleet Status")

    cols = st.columns(len(PLATFORM_ORDER))

    for i, platform in enumerate(PLATFORM_ORDER):
        data = metrics["by_platform"].get(platform)
        if not data or data["count"] == 0:
            with cols[i]:
                st.info(f"{PLATFORM_ICONS[platform]} {platform.title()}\n\nNo workers")
            continue

        with cols[i]:
            color = PLATFORM_COLORS[platform]
            util = data["gpu_utilization"]

            st.markdown(
                f"""
            <div style="border: 2px solid {color}; border-radius: 8px; padding: 12px; background: #fafafa;">
                <h4 style="color: {color}; margin: 0;">{PLATFORM_ICONS[platform]} {platform.title()}</h4>
                <p style="margin: 8px 0;"><b>{data['count']}</b> workers · <b>{data['active']}</b> active</p>
                <p style="margin: 4px 0;">GPU: <b>{data['used_gpu_mb']:,} / {data['total_gpu_mb']:,} MB</b> ({util:.1%})</p>
                {'<p style="color: red; margin: 4px 0;">⚠️ ' + str(data['stale']) + ' stale</p>' if data['stale'] else ''}
            </div>
            """,
                unsafe_allow_html=True,
            )


def render_worker_table(workers: List[Dict], now: float):
    """Render detailed worker table."""
    st.subheader("👷 Worker Details")

    if not workers:
        st.info("No workers registered")
        return

    # Sort by platform priority, then by status
    platform_order = {p: i for i, p in enumerate(PLATFORM_ORDER)}
    workers.sort(key=lambda w: (platform_order.get(w["platform"], 99), w["status"] != "processing"))

    rows = []
    for w in workers:
        age = now - w["ts"]
        is_stale = age > w["idle_timeout"] + 60
        util = w["gpu_mem_used_mb"] / w["gpu_mem_total_mb"] if w["gpu_mem_total_mb"] > 0 else 0

        rows.append(
            {
                "Worker ID": w["worker_id"][:20] + "..." if len(w["worker_id"]) > 20 else w["worker_id"],
                "Platform": f"{PLATFORM_ICONS.get(w['platform'], '')} {w['platform']}",
                "Status": w["status"].upper(),
                "GPU": w["device_name"],
                "Backend": w.get("backend", "-"),
                "GPU Util": f"{util:.1%}",
                "GPU Mem": f"{w['gpu_mem_used_mb']:,}/{w['gpu_mem_total_mb']:,} MB",
                "Age": f"{age:.0f}s",
                "Stale": "🔴" if is_stale else "🟢",
                "Studio": w["studio_id"],
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_gpu_heatmap(workers: List[Dict]):
    """Render GPU utilization heatmap."""
    st.subheader("📊 GPU Utilization Heatmap")

    if not workers:
        st.info("No GPU data available")
        return

    # Prepare data for heatmap
    platforms = sorted(set(w["platform"] for w in workers), key=lambda p: PLATFORM_ORDER.get(p, 99))

    fig = go.Figure()

    for platform in platforms:
        platform_workers = [w for w in workers if w["platform"] == platform]
        if not platform_workers:
            continue

        worker_ids = [w["worker_id"][-8:] for w in platform_workers]
        utils = [
            w["gpu_mem_used_mb"] / w["gpu_mem_total_mb"] if w["gpu_mem_total_mb"] > 0 else 0 for w in platform_workers
        ]
        colors = ["red" if u > 0.9 else "orange" if u > 0.7 else "yellow" if u > 0.4 else "green" for u in utils]

        fig.add_trace(
            go.Bar(
                name=platform.title(),
                x=worker_ids,
                y=utils,
                marker_color=colors,
                text=[f"{u:.0%}" for u in utils],
                textposition="auto",
            )
        )

    fig.update_layout(
        barmode="group",
        yaxis=dict(title="GPU Memory Utilization", range=[0, 1], tickformat=".0%"),
        xaxis=dict(title="Worker (suffix)"),
        height=300,
        showlegend=True,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_task_distribution(task_states: Dict[str, int]):
    """Render task state distribution pie chart."""
    st.subheader("📋 Task State Distribution")

    if sum(task_states.values()) == 0:
        st.info("No tasks in system")
        return

    fig = px.pie(
        values=list(task_states.values()),
        names=list(task_states.keys()),
        color_discrete_map={
            "PENDING": "#FFD93D",
            "CLAIMED": "#6BCB77",
            "SYNTHESIZING": "#4D96FF",
            "UPLOADING": "#FF6B6B",
            "COMPLETED": "#4ECDC4",
            "FAILED": "#FF6B6B",
        },
        hole=0.4,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=300, showlegend=True)

    st.plotly_chart(fig, use_container_width=True)


def render_task_queue_preview(redis_client: redis.Redis):
    """Render preview of pending task queue."""
    st.subheader("📥 Pending Task Queue (sample)")

    try:
        # Peek at first 10 tasks
        tasks = redis_client.lrange("tts:tasks", 0, 9)
        if not tasks:
            st.info("Queue empty")
            return

        rows = []
        for t in tasks:
            try:
                data = json.loads(t)
                task_id = data.get("id", "unknown")
                # Get task details
                task_data = redis_client.get(f"tts:task:{task_id}")
                if task_data:
                    td = json.loads(task_data)
                    rows.append(
                        {
                            "Task ID": task_id,
                            "State": td.get("state", "?"),
                            "Voice": td.get("voice_id", "?"),
                            "Chars": len(td.get("text", "")),
                            "Worker": td.get("worker_id", "unassigned"),
                        }
                    )
            except Exception:
                pass

        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Queue has tasks but details unavailable")

    except Exception as e:
        st.error(f"Failed to read queue: {e}")


def render_sidebar(config: DashboardConfig):
    """Render sidebar with configuration and controls."""
    with st.sidebar:
        st.header("⚙️ Configuration")

        st.text(f"Redis: {config.redis_host}:{config.redis_port}")
        st.text(f"Refresh: {config.refresh_interval}s")

        st.divider()

        st.header("📖 Key Schema")
        st.code(
            """
worker:heartbeat:{worker_id}
tts:tasks (list)
tts:results (list)
tts:task:{task_id} (hash)
tts:lock:{task_id} (string)
tts:idempotency:{key} (string)
        """,
            language="text",
        )

        st.divider()

        st.header("🎯 Platform Routing")
        st.markdown(
            """
        **Priority Order:**
        1. ☁️ Modal (urgent, instant cold-start)
        2. 🐉 Baidu (throughput, V100 burst)
        3. ⚡ Lightning (core, 80h/mo T4)
        4. 📊 Kaggle (primary, 30h/wk P100)
        """
        )

        st.divider()

        if st.button("🔄 Force Refresh"):
            st.rerun()


# --- Main App ---


def render_fleet_monitor(config: DashboardConfig, redis_client: redis.Redis, now: float):
    """Render the Fleet Monitor tab content."""
    # Fetch data
    with st.spinner("Fetching fleet telemetry..."):
        workers = scan_worker_heartbeats(redis_client)
        queue_depth = get_queue_depth(redis_client)
        results_count = get_results_count(redis_client)
        task_states = get_task_states(redis_client)

    metrics = compute_fleet_metrics(workers, now)

    # Alert banner
    render_alert_banner(metrics, queue_depth)

    # Metrics grid
    render_metrics_grid(metrics, queue_depth, results_count)

    # Platform cards
    render_platform_cards(metrics)

    st.divider()

    # Two-column layout
    col1, col2 = st.columns([2, 1])

    with col1:
        render_gpu_heatmap(workers)
        render_task_distribution(task_states)

    with col2:
        render_worker_table(workers, now)
        render_task_queue_preview(redis_client)


def main():
    config = DashboardConfig()
    redis_client = get_redis_client(config)
    now = time.time()

    # Sidebar
    render_sidebar(config)

    # Header with tabs
    st.title("🎙️ Hermes Dashboard — VoxCPM2 Fleet Monitor")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col2:
        auto_refresh = st.checkbox("Auto-refresh", value=True)
    with col3:
        if st.button("🔄 Refresh Now"):
            st.rerun()

    if auto_refresh:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()

    # Tab layout
    tab1, tab2 = st.tabs(["📊 Fleet Monitor", "🔍 Quality Console"])

    with tab1:
        render_fleet_monitor(config, redis_client, now)

    with tab2:
        render_quality_console(config)

    # Footer
    st.divider()
    st.caption(
        f"Last updated: {time.strftime('%H:%M:%S')} | "
        f"Next auto-refresh: {REFRESH_INTERVAL}s | "
        f"Hermes Dashboard v1.0"
    )


if __name__ == "__main__":
    main()


# --- Quality Console Tab ---


def render_quality_console(config: DashboardConfig):
    """Render the Quality Console tab for audio quality reports."""
    st.subheader("🔍 Quality Console — Audio Quality Reports")

    # Project selector
    col1, col2 = st.columns([2, 1])

    with col1:
        project_id = st.number_input(
            "Project ID",
            min_value=1,
            value=1,
            step=1,
            help="Enter the project ID to view quality report",
        )

    with col2:
        chapter_index = st.number_input(
            "Chapter Index",
            min_value=0,
            value=0,
            step=1,
            help="Chapter index (0 for latest/default)",
        )

    if st.button("🔄 Fetch Quality Report", type="primary"):
        st.session_state["fetch_quality"] = True
        st.session_state["quality_project_id"] = project_id
        st.session_state["quality_chapter"] = chapter_index

    # Fetch and display quality report
    if st.session_state.get("fetch_quality", False):
        pid = st.session_state.get("quality_project_id", project_id)
        ch = st.session_state.get("quality_chapter", chapter_index)

        with st.spinner(f"Fetching quality report for project {pid}, chapter {ch}..."):
            try:
                response = requests.get(
                    f"{config.api_base_url}/api/projects/{pid}/quality-report",
                    params={"chapter_index": ch},
                    timeout=10,
                )

                if response.status_code == 404:
                    st.warning(
                        f"No quality report found for project {pid}, chapter {ch}. "
                        "Run the synthesis pipeline first to generate quality reports."
                    )
                    st.session_state["fetch_quality"] = False
                    return

                response.raise_for_status()
                report = response.json()

                st.session_state["quality_report"] = report
                st.session_state["fetch_quality"] = False

            except requests.exceptions.ConnectionError:
                st.error(f"Cannot connect to API at {config.api_base_url}. " "Make sure the FastAPI server is running.")
                st.session_state["fetch_quality"] = False
                return
            except requests.exceptions.RequestException as e:
                st.error(f"Failed to fetch quality report: {e}")
                st.session_state["fetch_quality"] = False
                return

    # Display quality report if available
    if "quality_report" in st.session_state:
        report = st.session_state["quality_report"]

        # Overall status banner
        if report["overall_passed"]:
            st.success(
                f"✅ **All Checks Passed** — {report['passed_segments']}/{report['total_segments']} segments healthy"
            )
        else:
            st.error(
                f"❌ **Quality Issues Detected** — {report['failed_segments']}/{report['total_segments']} segments failed"
            )

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Segments", report["total_segments"])
        with col2:
            st.metric("Passed", report["passed_segments"], delta=None)
        with col3:
            st.metric("Failed", report["failed_segments"], delta_color="inverse")
        with col4:
            pass_rate = report["passed_segments"] / max(report["total_segments"], 1)
            st.metric("Pass Rate", f"{pass_rate:.1%}")

        st.divider()

        # Segment details table
        st.subheader("📋 Segment Quality Details")

        # Create dataframe for display
        import pandas as pd

        rows = []
        for seg in report["segment_results"]:
            status_icon = "✅" if seg["passed"] else "❌"
            issues_str = "; ".join(seg["issues"]) if seg["issues"] else "—"

            rows.append(
                {
                    "Status": status_icon,
                    "Segment ID": seg["segment_id"],
                    "File": seg["file_path"].split("/")[-1] if seg["file_path"] else "N/A",
                    "Duration (ms)": seg["duration_ms"],
                    "Silence Ratio": f"{seg['silence_ratio']:.1%}",
                    "Silence Detected": "⚠️" if seg["silence_detected"] else "✅",
                    "Clipping": "⚠️" if seg["clipping_detected"] else "✅",
                    "Peak (dB)": f"{seg['peak_db']:.1f}",
                    "RMS (dB)": f"{seg['rms_db']:.1f}",
                    "Corruption": "⚠️" if seg["corruption_detected"] else "✅",
                    "Issues": issues_str,
                }
            )

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

        # Re-synthesize button for failed segments
        failed_segments = [s for s in report["segment_results"] if not s["passed"]]
        if failed_segments:
            st.divider()
            st.subheader("🔧 Manual Re-synthesis")

            selected_segment = st.selectbox(
                "Select failed segment to re-synthesize:",
                options=[s["segment_id"] for s in failed_segments],
                format_func=lambda x: f"{x} — {next(s['issues'][0] for s in failed_segments if s['segment_id'] == x)}",
            )

            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("🔁 Re-synthesize Selected", type="secondary"):
                    st.info(
                        f"Re-synthesis requested for {selected_segment}. This would trigger the pipeline to re-generate this segment."
                    )
                    # TODO: Implement actual re-synthesis via API call
                    st.warning(
                        "Re-synthesis API integration pending. Use the pipeline CLI for now: `python -m audiobook_studio.run_pipeline ...`"
                    )
            with col2:
                st.caption("Click to trigger re-synthesis of the selected failed segment via the pipeline.")

        # Raw JSON download
        st.divider()
        st.download_button(
            label="📥 Download Full Report (JSON)",
            data=json.dumps(report, ensure_ascii=False, indent=2),
            file_name=f"quality_report_p{report['project_id']}_ch{report['chapter_index']}.json",
            mime="application/json",
        )
