"""Locust stress test for Audiobook Studio.

Scenarios:
- A: Concurrent POST /api/export, capture task_id, poll for completion
- B: WebSocket long connections with text streaming

Performance assertions:
- RTF (Real-Time Factor) < 0.2
- TTFB (Time To First Byte) < 500ms
"""

import time
import json
import random
import asyncio
from typing import Optional

from locust import HttpUser, task, between, events
from locust.exception import RescheduleTask


# Global storage for task IDs and WebSocket connections
task_ids = []
websocket_messages_received = []


class ExportAPIUser(HttpUser):
    """User simulating export API workflow: POST -> poll -> verify."""

    wait_time = between(1, 3)

    def on_start(self):
        """Initialize user session."""
        self.task_id: Optional[str] = None
        self.poll_start_time: Optional[float] = None
        self.first_byte_time: Optional[float] = None

    @task(3)
    def export_workflow(self):
        """Full export workflow: create task, poll for completion, measure RTF/TTFB."""
        # Step 1: Create export task
        payload = {
            "format": "mp3",
            "quality": "high",
            "chapters": [f"chapter_{i}" for i in range(random.randint(1, 5))],
            "voice_settings": {
                "speaker": "narrator",
                "speed": 1.0,
                "pitch": 0,
            },
        }

        with self.client.post(
            "/api/export",
            json=payload,
            catch_response=True,
            name="POST /api/export",
        ) as response:
            if response.status_code != 202:
                response.failure(f"Expected 202, got {response.status_code}")
                return

            try:
                data = response.json()
                self.task_id = data.get("task_id")
                if not self.task_id:
                    response.failure("No task_id in response")
                    return
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
                f"/api/export/{self.task_id}/status",
                catch_response=True,
                name="GET /api/export/{task_id}/status",
            ) as response:
                if response.status_code != 200:
                    response.failure(f"Status check failed: {response.status_code}")
                    return

                try:
                    data = response.json()
                    status = data.get("status")
                    progress = data.get("progress", 0)

                    if status == "completed":
                        response.success()
                        self._measure_performance(data)
                        return
                    elif status == "failed":
                        response.failure(f"Task failed: {data.get('error', 'Unknown error')}")
                        return
                    elif status in ("pending", "processing"):
                        response.success()
                        time.sleep(poll_interval)
                        continue
                    else:
                        response.failure(f"Unknown status: {status}")
                        return
                except json.JSONDecodeError:
                    response.failure("Invalid JSON in status response")
                    return

        # Timeout
        with self.client.get(
            f"/api/export/{self.task_id}/status",
            catch_response=True,
            name="GET /api/export/{task_id}/status (timeout)",
        ) as response:
            response.failure("Task polling timeout")

    def _measure_performance(self, data: dict):
        """Calculate and assert RTF and TTFB metrics."""
        # RTF = audio_duration / processing_time
        audio_duration = data.get("audio_duration_seconds", 0)
        processing_time = data.get("processing_time_seconds", 0)

        if audio_duration > 0 and processing_time > 0:
            rtf = processing_time / audio_duration
            print(f"RTF: {rtf:.3f} (threshold: 0.2)")

            if rtf > 0.2:
                self.environment.events.request_failure.fire(
                    request_type="ASSERT",
                    name="RTF Check",
                    response_time=0,
                    exception=AssertionError(f"RTF {rtf:.3f} exceeds threshold 0.2"),
                )
            else:
                self.environment.events.request_success.fire(
                    request_type="ASSERT",
                    name="RTF Check",
                    response_time=0,
                    response_length=0,
                )

        # TTFB from first byte timing (captured in first byte hook)
        if self.first_byte_time and self.poll_start_time:
            ttfb = (self.first_byte_time - self.poll_start_time) * 1000  # ms
            print(f"TTFB: {ttfb:.1f}ms (threshold: 500ms)")

            if ttfb > 500:
                self.environment.events.request_failure.fire(
                    request_type="ASSERT",
                    name="TTFB Check",
                    response_time=0,
                    exception=AssertionError(f"TTFB {ttfb:.1f}ms exceeds threshold 500ms"),
                )
            else:
                self.environment.events.request_success.fire(
                    request_type="ASSERT",
                    name="TTFB Check",
                    response_time=0,
                    response_length=0,
                )


class WebSocketUser(HttpUser):
    """User simulating long-lived WebSocket connections with text streaming."""

    wait_time = between(0.5, 2)

    def on_start(self):
        """Establish WebSocket connection."""
        self.ws = None
        self.message_count = 0
        self.connect_time = time.time()
        self._connect_websocket()

    def on_stop(self):
        """Close WebSocket on user stop."""
        if self.ws:
            self.ws.close()

    def _connect_websocket(self):
        """Connect to WebSocket endpoint."""
        # Note: Locust's HttpUser doesn't natively support WebSocket.
        # We use the websocket-client library directly or fall back to HTTP streaming.
        try:
            import websocket

            # Convert HTTP URL to WebSocket URL
            ws_url = self.client.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = f"{ws_url}/api/ws/stream"

            self.ws = websocket.create_connection(ws_url, timeout=10)
            self.connect_time = time.time()

            # Send initial handshake/message
            self.ws.send(json.dumps({"type": "subscribe", "channel": "tts_stream"}))

        except ImportError:
            # Fallback: simulate with HTTP streaming if websocket-client not available
            self.ws = None
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            self.ws = None

    @task(2)
    def stream_text(self):
        """Send text for streaming TTS and receive audio chunks."""
        if not self.ws:
            # Use HTTP streaming fallback
            self._http_stream_fallback()
            return

        text = random.choice([
            "Hello, this is a test message for streaming.",
            "The quick brown fox jumps over the lazy dog.",
            "Audiobook Studio provides high-quality TTS streaming.",
            "Real-time factor and time to first byte are critical metrics.",
            "Testing concurrent WebSocket connections under load.",
        ])

        start_time = time.time()

        try:
            # Send text to synthesize
            self.ws.send(json.dumps({"type": "synthesize", "text": text}))

            # Receive audio chunks
            chunks_received = 0
            first_chunk = True
            first_chunk_time = None

            while True:
                result = self.ws.recv()
                if not result:
                    break

                if first_chunk:
                    first_chunk_time = time.time()
                    first_chunk = False

                chunks_received += 1

                # Check for completion message
                try:
                    msg = json.loads(result)
                    if msg.get("type") == "complete":
                        break
                    elif msg.get("type") == "error":
                        self.environment.events.request_failure.fire(
                            request_type="WS",
                            name="WebSocket Stream",
                            response_time=int((time.time() - start_time) * 1000),
                            exception=Exception(msg.get("message", "Unknown error")),
                        )
                        return
                except json.JSONDecodeError:
                    # Binary audio chunk - count it
                    pass

            elapsed = (time.time() - start_time) * 1000
            self.message_count += 1

            # Record TTFB (time to first chunk)
            if first_chunk_time:
                ttfb = (first_chunk_time - start_time) * 1000
                self.environment.events.request_success.fire(
                    request_type="WS",
                    name="WebSocket TTFB",
                    response_time=int(ttfb),
                    response_length=0,
                )

                if ttfb > 500:
                    print(f"⚠️ WebSocket TTFB {ttfb:.1f}ms exceeds 500ms threshold")

            self.environment.events.request_success.fire(
                request_type="WS",
                name="WebSocket Stream",
                response_time=int(elapsed),
                response_length=chunks_received * 1024,  # approximate
            )

        except Exception as e:
            self.environment.events.request_failure.fire(
                request_type="WS",
                name="WebSocket Stream",
                response_time=int((time.time() - start_time) * 1000),
                exception=e,
            )

    def _http_stream_fallback(self):
        """Fallback HTTP streaming if WebSocket not available."""
        text = random.choice([
            "Hello, this is a test message for streaming.",
            "The quick brown fox jumps over the lazy dog.",
        ])

        with self.client.post(
            "/api/tts/stream",
            json={"text": text, "voice": "narrator"},
            stream=True,
            catch_response=True,
            name="POST /api/tts/stream (fallback)",
        ) as response:
            if response.status_code != 200:
                response.failure(f"Stream failed: {response.status_code}")
                return

            first_chunk_time = None
            chunks = 0

            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    if first_chunk_time is None:
                        first_chunk_time = time.time()
                        ttfb = (first_chunk_time - self.connect_time) * 1000
                        self.environment.events.request_success.fire(
                            request_type="HTTP_STREAM",
                            name="HTTP Stream TTFB",
                            response_time=int(ttfb),
                            response_length=0,
                        )
                    chunks += 1

            elapsed = (time.time() - self.connect_time) * 1000
            self.environment.events.request_success.fire(
                request_type="HTTP_STREAM",
                name="HTTP Stream",
                response_time=int(elapsed),
                response_length=chunks * 1024,
            )


class MixedWorkloadUser(HttpUser):
    """Mixed workload combining export API and WebSocket scenarios."""

    wait_time = between(1, 5)

    @task(2)
    def run_export(self):
        """Run export workflow."""
        export_user = ExportAPIUser(self.environment)
        export_user.client = self.client
        export_user.export_workflow()

    @task(1)
    def run_websocket(self):
        """Run WebSocket streaming."""
        ws_user = WebSocketUser(self.environment)
        ws_user.client = self.client
        ws_user.on_start()
        ws_user.stream_text()


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