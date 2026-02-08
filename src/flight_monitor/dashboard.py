"""Web dashboard for visualising flight price history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flight_monitor.config import load_config
from flight_monitor.models import RouteKey
from flight_monitor.storage.database import PriceDatabase

logger = logging.getLogger(__name__)

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight Price Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f5f5; padding: 20px; }
  h1 { margin-bottom: 20px; color: #333; }
  .route-card {
    background: white; border-radius: 8px; padding: 20px;
    margin-bottom: 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  }
  .route-card h2 { margin-bottom: 8px; color: #4a90d9; }
  .stats { display: flex; gap: 24px; margin-bottom: 16px; color: #555; }
  .stats span { font-weight: bold; }
  canvas { max-height: 300px; }
</style>
</head>
<body>
<h1>Flight Price Dashboard</h1>
{% for route in routes %}
<div class="route-card">
  <h2>{{ route.origin }} &rarr; {{ route.dest }}</h2>
  <div class="stats">
    <div>Avg: <span>{{ route.currency }} {{ route.avg }}</span></div>
    <div>Min: <span>{{ route.currency }} {{ route.min }}</span></div>
    <div>Max: <span>{{ route.currency }} {{ route.max }}</span></div>
    <div>Records: <span>{{ route.count }}</span></div>
  </div>
  <canvas id="chart-{{ route.origin }}-{{ route.dest }}"></canvas>
</div>
<script>
(function() {
  const ctx = document.getElementById('chart-{{ route.origin }}-{{ route.dest }}');
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: {{ route.labels | safe }},
      datasets: [
        {
          label: 'Avg Price',
          data: {{ route.avg_data | safe }},
          borderColor: '#4a90d9',
          backgroundColor: 'rgba(74,144,217,0.1)',
          fill: true, tension: 0.3
        },
        {
          label: 'Min Price',
          data: {{ route.min_data | safe }},
          borderColor: '#2ecc71',
          borderDash: [5, 5],
          fill: false, tension: 0.3
        }
      ]
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: false, title: { display: true, text: '{{ route.currency }}' } },
        x: { title: { display: true, text: 'Date' } }
      }
    }
  });
})();
</script>
{% endfor %}
{% if not routes %}
<p style="color: #888;">No price history found. Run a monitoring cycle first.</p>
{% endif %}
</body>
</html>
"""


def _build_route_data(db: PriceDatabase, trend_days: int = 90) -> list[dict]:
    """Build template data for all routes."""
    routes_data = []
    for origin, dest in db.get_all_routes():
        stats = db.get_route_stats(
            RouteKey(origin_code=origin, destination_code=dest)
        )
        if stats.count == 0:
            continue

        trend = db.get_price_trend(origin, dest, last_n_days=trend_days)
        labels = json.dumps([e["date"] for e in trend])
        avg_data = json.dumps([e["avg_price"] for e in trend])
        min_data = json.dumps([e["min_price"] for e in trend])

        routes_data.append({
            "origin": origin,
            "dest": dest,
            "avg": stats.avg_price,
            "min": stats.min_price,
            "max": stats.max_price,
            "count": stats.count,
            "currency": "EUR",
            "labels": labels,
            "avg_data": avg_data,
            "min_data": min_data,
        })
    return routes_data


def create_app(config_path: str | Path) -> object:
    """Create and return a Flask application for the dashboard."""
    try:
        from flask import Flask, render_template_string
    except ImportError as exc:
        raise ImportError(
            "Flask is required for the dashboard. "
            "Install it with: pip install flight-monitor[dashboard]"
        ) from exc

    app = Flask(__name__)
    cfg = load_config(config_path)
    db = PriceDatabase(cfg.storage.db_path)

    @app.route("/")
    def index():
        routes = _build_route_data(db)
        return render_template_string(DASHBOARD_HTML, routes=routes)

    @app.route("/api/routes")
    def api_routes():
        from flask import jsonify

        routes = _build_route_data(db)
        return jsonify(routes)

    return app
