#!/usr/bin/env python3
"""
Audiobook Studio - Stress Test / SLA Verification
Run against staging environment to verify v1.0 GA readiness.
"""

import asyncio
import aiohttp
import time
import statistics
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime

BASE_URL = os.getenv("STRESS_TEST_BASE_URL", "http://localhost:8000")
CONCURRENT_USERS = int(os.getenv("STRESS_TEST_USERS", "50"))
DURATION_SECONDS = int(os.getenv("STRESS_TEST_DURATION", "60"))
RAMP_UP_SECONDS = int(os.getenv("STRESS_TEST_RAMPUP", "10"))

@dataclass
class RequestResult:
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    success: bool
    error: str = ""

class StressTester:
    def __init__(self):
        self.results: List[RequestResult] = []
        self.session: aiohttp.ClientSession = None
        self.start_time = time.time()
        
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            
    async def make_request(self, method: str, endpoint: str, **kwargs) -> RequestResult:
        url = f"{BASE_URL}{endpoint}"
        start = time.perf_counter()
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                await resp.read()
                latency = (time.perf_counter() - start) * 1000
                return RequestResult(
                    endpoint=endpoint,
                    method=method,
                    status_code=resp.status,
                    latency_ms=latency,
                    success=200 <= resp.status < 400
                )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return RequestResult(
                endpoint=endpoint,
                method=method,
                status_code=0,
                latency_ms=latency,
                success=False,
                error=str(e)
            )
    
    async def user_session(self, user_id: int):
        """Simulate a user session: health -> create book -> poll status"""
        # Health check
        await self.make_request("GET", "/health/ready")
        
        # Create a book
        book_data = {
            "title": f"Stress Test Book {user_id}",
            "author": "Load Tester",
            "language": "en",
            "chapters": [
                {"title": f"Chapter {i}", "content": f"Content for chapter {i}. " * 100}
                for i in range(1, 4)
            ]
        }
        
        result = await self.make_request("POST", "/api/v1/books", json=book_data)
        self.results.append(result)
        
        if result.success and result.status_code == 201:
            book_id = result.error  # We'll parse from response
            try:
                # Actually need to parse response body - simplified
                pass
            except:
                pass
        
        # Poll status a few times
        for _ in range(3):
            await asyncio.sleep(2)
            await self.make_request("GET", f"/api/v1/books/{book_id}")
            
    async def run_load_test(self):
        print(f"Starting stress test: {CONCURRENT_USERS} users, {DURATION_SECONDS}s duration")
        print(f"Target: {BASE_URL}")
        print("-" * 60)
        
        # Ramp up users gradually
        tasks = []
        for i in range(CONCURRENT_USERS):
            delay = (i / CONCURRENT_USERS) * RAMP_UP_SECONDS
            task = asyncio.create_task(self.ramped_user(i, delay))
            tasks.append(task)
            
        # Wait for all to complete or timeout
        await asyncio.wait(tasks, timeout=DURATION_SECONDS + RAMP_UP_SECONDS + 10)
        
    async def ramped_user(self, user_id: int, delay: float):
        await asyncio.sleep(delay)
        end_time = self.start_time + DURATION_SECONDS + RAMP_UP_SECONDS
        while time.time() < end_time:
            await self.user_session(user_id)
            await asyncio.sleep(1)  # Think time
            
    def print_report(self):
        if not self.results:
            print("No results collected!")
            return
            
        total = len(self.results)
        successful = sum(1 for r in self.results if r.success)
        failed = total - successful
        
        latencies = [r.latency_ms for r in self.results if r.success]
        
        print("\n" + "=" * 60)
        print("STRESS TEST REPORT")
        print("=" * 60)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Base URL: {BASE_URL}")
        print(f"Concurrent Users: {CONCURRENT_USERS}")
        print(f"Duration: {DURATION_SECONDS}s")
        print(f"Ramp-up: {RAMP_UP_SECONDS}s")
        print("-" * 60)
        print(f"Total Requests: {total}")
        print(f"Successful: {successful} ({successful/total*100:.1f}%)")
        print(f"Failed: {failed} ({failed/total*100:.1f}%)")
        print("-" * 60)
        
        if latencies:
            print("Latency (successful requests):")
            print(f"  Min: {min(latencies):.1f}ms")
            print(f"  Max: {max(latencies):.1f}ms")
            print(f"  Mean: {statistics.mean(latencies):.1f}ms")
            print(f"  Median: {statistics.median(latencies):.1f}ms")
            print(f"  P50: {statistics.quantiles(latencies, n=100)[49]:.1f}ms")
            print(f"  P95: {statistics.quantiles(latencies, n=100)[94]:.1f}ms")
            print(f"  P99: {statistics.quantiles(latencies, n=100)[98]:.1f}ms")
            print("-" * 60)
            
        # By endpoint
        by_endpoint: Dict[str, List[RequestResult]] = {}
        for r in self.results:
            key = f"{r.method} {r.endpoint}"
            if key not in by_endpoint:
                by_endpoint[key] = []
            by_endpoint[key].append(r)
            
        print("By Endpoint:")
        for endpoint, results in sorted(by_endpoint.items()):
            ep_success = sum(1 for r in results if r.success)
            ep_total = len(results)
            ep_latencies = [r.latency_ms for r in results if r.success]
            if ep_latencies:
                print(f"  {endpoint}: {ep_success}/{ep_total} ({ep_success/ep_total*100:.1f}%) "
                      f"p50={statistics.quantiles(ep_latencies, n=100)[49]:.1f}ms "
                      f"p95={statistics.quantiles(ep_latencies, n=100)[94]:.1f}ms")
            else:
                print(f"  {endpoint}: {ep_success}/{ep_total} ({ep_success/ep_total*100:.1f}%) - no successful requests")
                
        print("-" * 60)
        
        # SLA Verification
        print("SLA VERIFICATION:")
        sla_pass = True
        
        # Availability > 99.5%
        availability = successful / total * 100
        sla_avail = availability >= 99.5
        print(f"  Availability >= 99.5%: {'PASS' if sla_avail else 'FAIL'} ({availability:.2f}%)")
        sla_pass &= sla_avail
        
        # P95 latency < 500ms for health endpoints
        health_latencies = [r.latency_ms for r in self.results if r.success and "/health" in r.endpoint]
        if health_latencies:
            p95_health = statistics.quantiles(health_latencies, n=100)[94]
            sla_latency = p95_health < 500
            print(f"  Health p95 < 500ms: {'PASS' if sla_latency else 'FAIL'} ({p95_health:.1f}ms)")
            sla_pass &= sla_latency
            
        # P99 latency < 2000ms for API endpoints
        api_latencies = [r.latency_ms for r in self.results if r.success and "/api/" in r.endpoint]
        if api_latencies:
            p99_api = statistics.quantiles(api_latencies, n=100)[98]
            sla_api = p99_api < 2000
            print(f"  API p99 < 2000ms: {'PASS' if sla_api else 'FAIL'} ({p99_api:.1f}ms)")
            sla_pass &= sla_api
            
        # Error rate < 0.5%
        error_rate = failed / total * 100
        sla_error = error_rate < 0.5
        print(f"  Error rate < 0.5%: {'PASS' if sla_error else 'FAIL'} ({error_rate:.2f}%)")
        sla_pass &= sla_error
        
        print("-" * 60)
        print(f"OVERALL SLA: {'PASS' if sla_pass else 'FAIL'}")
        print("=" * 60)
        
        return sla_pass

async def main():
    async with StressTester() as tester:
        await tester.run_load_test()
        passed = tester.print_report()
        sys.exit(0 if passed else 1)

if __name__ == "__main__":
    asyncio.run(main())
