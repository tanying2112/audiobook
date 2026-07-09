"""Locust stress test for Audiobook Studio.

Scenarios:
- A: Concurrent export POST /api/projects/{project_id}/export, capture the
     task_id, then poll /api/export/tasks/{task_id}/status until completion.
- B: WebSocket long connections on /api/ws/pipeline/{project_id}.

Performance assertions:
- RTF (Real-Time Factor) < 0.2  (see note in ``_measure_performance``: the export
  status endpoint does not return audio_duration, so RTF is skipped honestly
  and client-side processing_time is reported instead).
- TTFB (Time To First Byte) < 500ms  (POST export → first 202 response).

Contract source of truth: ``src/audiobook_studio/api/export.py``
(``ExportRequest`` request schema, ``TaskStatusOut`` status schema) and
``src/audiobook_studio/api/websocket.py`` (``/api/ws/pipeline/{project_id}``).
"""

import json
import random
import time
from typing import List, Optional

from locust import HttpUser, between, events, task
from locust.exception import RescheduleTask


# Global storage for task IDs / WebSocket message counts (per-run, for inspection)
task_ids: List[str] = []
websocket_messages_received: List[int] = []

# ── Contract constants (keep aligned with api/export.py + api/websocket.py) ──
EXPORT_PATH_TEMPLATE = "/api/projects/{project_id}/export/"
STATUS_PATH_TEMPLATE = "/api/export/tasks/{task_id}/status"
PROJECTS_LIST_PATH = "/api/projects/"
PROJECTS_CREATE_PATH = "/api/projects/"
WS_PATH_TEMPLATE = "/api/ws/pipeline/{project_id}"
# TaskStatusOut.state is a Celery state string; progress is a human string
# ("pending"/"processing"/"complete"/"retrying"/"failed"). Completion = SUCCESS.
TERMINAL_SUCCESS_STATES = ("SUCCESS",)
TERMINAL_FAILURE_STATES = ("FAILURE",)


class ExportAPIUser(HttpUser):
    """User simulating export API workflow: POST -> poll -> verify."""

    wait_time = between(1, 3)

    def on_start(self):
        """Initialize user session and ensure a project exists to export."""
        self.task_id: Optional[str] = None
        self.project_id: Optional[int] = None
        self.post_time: Optional[float] = None  # client-side POST→SUCCESS wall-clock
        self.first_byte_time: Optional[float] = None
        self.project_id = self._ensure_project()

    def _ensure_project(self) -> int:
        """Get the first existing project id, creating one if none exists.

        Required because the export endpoint is project-scoped:
        ``POST /api/projects/{project_id}/export/`` — without a real project_id
        the endpoint returns 404 (the Sprint L locustfile omitted it).
        """
        with self.client.get(
            PROJECTS_LIST_PATH, catch_response=True, name="GET /api/projects/"
        ) as r:
            if r.status_code == 200:
                projects = r.json() or []
                if projects:
                    return projects[0]["id"]
        # No project — create a minimal one (ProjectCreate: title required).
        payload = {"title": f"locust-stress-{random.randint(1000, 9999)}", "language": "zh"}
        with self.client.post(
            PROJECTS_CREATE_PATH, json=payload, catch_response=True, name="POST /api/projects/"
        ) as r:
            if r.status_code == 201:
                return r.json()["id"]
            r.failure(f"could not ensure project: {r.status_code} {r.text[:200]}")
        raise RescheduleTask("no project available for export")

    @task(3)
    def export_workflow(self):
        """Full export workflow: create task, poll for completion, measure RTF/TTFB."""
        if self.project_id is None:
            self.project_id = self._ensure_project()

        # ExportRequest contract (api/export.py ExportRequest):
        #   chapter_ids: list[int] | None, formats: list[str], include_cover,
        #   normalize, ... — NOT {format, quality, chapters, voice_settings}.
        payload = {
            "chapter_ids": None,  # None ⇒ export all chapters
            "formats": ["m4b_srt"],
            "include_cover": False,
            "normalize": True,
        }

        self.post_time = time.time()
        with self.client.post(
            EXPORT_PATH_TEMPLATE.format(project_id=self.project_id),
            json=payload,
            catch_response=True,
            name="POST /api/projects/{id}/export",
        ) as response:
            self.first_byte_time = time.time()
            if response.status_code != 202:
                response.failure(f"Expected 202, got {response.status_code}: {response.text[:200]}")
                return

            try:
                data = response.json()
                self.task_id = data.get("task_id")
                if not self.task_id:
                    response.failure("No task_id in response")
                    return
                task_ids.append(self.task_id)
                response.success()
            except json.JSONDecodeError:
                response.failure("Invalid JSON response")
                return

        # Step 2: Poll for completion
        self._poll_for_completion()

    def _poll_for_completion(self):
        """Poll task status until completion or timeout."""
        max_polls = 60  # 60 seconds max
        poll_interval = 1.0

        for _ in range(max_polls):
            with self.client.get(
                STATUS_PATH_TEMPLATE.format(task_id=self.task_id),
                catch_response=True,
                name="GET /api/export/tasks/{task_id}/status",
            ) as response:
                if response.status_code != 200:
                    response.failure(f"Status check failed: {response.status_code}")
                    return

                try:
                    data = response.json()
                    # TaskStatusOut uses `state` (Celery) + `progress` (str), not
                    # `status == "completed"`. progress is a string
                    # ("pending"/"processing"/"complete"/"retrying"/"failed"),
                    # never a numeric percentage.
                    state = data.get("state")
                    progress = data.get("progress", "")

                    if state in TERMINAL_SUCCESS_STATES or progress == "complete":
                        response.success()
                        self._measure_performance(data)
                        return
                    elif state in TERMINAL_FAILURE_STATES or progress == "failed":
                        response.failure(f"Task failed: {data.get('error', 'Unknown error')}")
                        return
                    else:
                        # PENDING / STARTED / RETRY → keep polling
                        response.success()
                        time.sleep(poll_interval)
                        continue
                except json.JSONDecodeError:
                    response.failure("Invalid JSON in status response")
                    return

        # Timeout
        with self.client.get(
            STATUS_PATH_TEMPLATE.format(task_id=self.task_id),
            catch_response=True,
            name="GET /api/export/tasks/{task_id}/status (timeout)",
        ) as response:
            response.failure("Task polling timeout")

    def _measure_performance(self, data: dict):
        """Calculate and assert RTF and TTFB from client-observable data.

        NOTE on RTF (CLAUDE.md 铁律5 honesty): RTF = processing_time /
        audio_duration. The export status endpoint (TaskStatusOut in
        api/export.py) returns {task_id, state, progress, message,
        current_stage, output_paths, error} — it does NOT include
        ``audio_duration_seconds`` or ``processing_time_seconds``. So we measure
        ``processing_time`` client-side (wall-clock POST→SUCCESS) and treat
        ``audio_duration`` as unavailable: RTF cannot be computed honestly, so we
        log and skip the assertion rather than assert against phantom fields.
        """
        # Processing time: client wall-clock from POST → SUCCESS.
        processing_time = (time.time() - (self.post_time or time.time()))
        print(f"processing_time={processing_time:.2f}s")

        # RTF only assertable if the backend ever returns audio_duration
        # (it currently does not via TaskStatusOut).
        audio_duration = data.get("audio_duration_seconds")
        if audio_duration and audio_duration > 0 and processing_time > 0:
            rtf = processing_time / audio_duration
            print(f"RTF: {rtf:.3f} (threshold: 0.2)")
            if rtf > 0.2:
                self.environment.events.request.fire(
                    request_type="ASSERT",
                    name="RTF Check",
                    response_time=0,
                    response_length=0,
                    exception=AssertionError(f"RTF {rtf:.3f} exceeds threshold 0.2"),
                )
            else:
                self.environment.events.request.fire(
                    request_type="ASSERT",
                    name="RTF Check",
                    response_time=0,
                    response_length=0,
                    exception=None,
                )
        else:
            print("RTF: skipped — backend ExportStatusOut does not return audio_duration_seconds")

        # TTFB from POST → first byte (response received in export_workflow).
        if self.first_byte_time and self.post_time:
            ttfb = (self.first_byte_time - self.post_time) * 1000  # ms
            print(f"TTFB: {ttfb:.1f}ms (threshold: 500ms)")
            if ttfb > 500:
                self.environment.events.request.fire(
                    request_type="ASSERT",
                    name="TTFB Check",
                    response_time=0,
                    response_length=0,
                    exception=AssertionError(f"TTFB {ttfb:.1f}ms exceeds threshold 500ms"),
                )
            else:
                self.environment.events.request.fire(
                    request_type="ASSERT",
                    name="TTFB Check",
                    response_time=0,
                    response_length=0,
                    exception=None,
                )


class WebSocketUser(HttpUser):
    """User simulating long-lived WebSocket connections on the pipeline endpoint."""

    wait_time = between(0.5, 2)

    def on_start(self):
        """Establish WebSocket connection to the real pipeline endpoint."""
        self.ws = None
        self.message_count = 0
        self.connect_time = time.time()
        self._connect_websocket()

    def on_stop(self):
        """Close WebSocket on user stop."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _ensure_project_id(self) -> int:
        """Reuse the project-scoped contract: GET /api/projects/ → first id."""
        try:
            with self.client.get(
                PROJECTS_LIST_PATH, catch_response=True, name="GET /api/projects/ (ws)"
            ) as r:
                if r.status_code == 200:
                    projects = r.json() or []
                    if projects:
                        return projects[0]["id"]
        except Exception:
            pass
        return 1  # last-resort default (may 4xx on connect; acceptable for stress)

    def _connect_websocket(self):
        """Connect to the real WebSocket endpoint /api/ws/pipeline/{project_id}.

        Locust's HttpUser doesn't natively support WebSocket; we use
        websocket-client directly against the project-scoped pipeline endpoint
        (api/websocket.py sends a {"type": "connected", ...} frame on accept).
        The earlier Sprint L version posted to a non-existent /api/ws/stream.
        """
        try:
            import websocket
        except ImportError:
            self.ws = None
            return
        try:
            project_id = self._ensure_project_id()
            ws_url = self.client.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = ws_url + WS_PATH_TEMPLATE.format(project_id=project_id)
            self.ws = websocket.create_connection(ws_url, timeout=10)
            self.connect_time = time.time()
            # Validate the connected handshake frame from api/websocket.py.
            hello = self.ws.recv()
            try:
                msg = json.loads(hello)
                if isinstance(msg, dict) and msg.get("type") == "connected":
                    websocket_messages_received.append(1)
            except json.JSONDecodeError:
                pass
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            self.ws = None

    @task(2)
    def keep_connection_alive(self):
        """Receive pipeline progress frames for the life of the connection."""
        if not self.ws:
            self._connect_websocket()
            if not self.ws:
                return
        try:
            self.ws.settimeout(1.0)
            result = self.ws.recv()
            self.message_count += 1
            websocket_messages_received.append(1)
            self.environment.events.request.fire(
                request_type="WS",
                name="WebSocket Recv",
                response_time=0,
                response_length=len(result) if result else 0,
                exception=None,
            )
        except Exception:
            # Timeout / closed connection — reconnect on next tick.
            self.ws = None


class MixedWorkloadUser(HttpUser):
    """Mixed workload combining export API and WebSocket scenarios."""

    wait_time = between(1, 5)

    def on_start(self):
        self.export_user = ExportAPIUser(self.environment)
        self.export_user.client = self.client
        self.export_user.on_start()
        self.ws_user = WebSocketUser(self.environment)
        self.ws_user.client = self.client
        self.ws_user.on_start()

    @task(2)
    def run_export(self):
        """Run export workflow."""
        self.export_user.export_workflow()

    @task(1)
    def run_websocket(self):
        """Run WebSocket streaming."""
        self.ws_user.keep_connection_alive()


# Event hooks for capturing timing
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Track custom metrics."""
    pass


# Custom shape for load testing (optional - for more complex scenarios)
class StagesShape:
    """Load test stages: ramp up, sustain, spike, cool down."""

    stages = [
        {"duration": 30, "users": 10, "spawn_rate": 2},   # Warm up
        {"duration": 60, "users": 30, "spawn_rate": 5},   # Normal load
        {"duration": 30, "users": 50, "spawn_rate": 10},  # Peak load
        {"duration": 60, "users": 50, "spawn_rate": 0},   # Sustain peak
        {"duration": 30, "users": 10, "spawn_rate": -5},  # Cool down
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
            run_time -= stage["duration"]

        return None


# Export for Locust CLI usage
if __name__ == "__main__":
    print("Run with: locust -f tests/stress/locustfile.py --host=http://localhost:8000")
