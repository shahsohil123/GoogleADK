#!/usr/bin/env python3
"""Provisions the BigQuery dataset, table, and views for the ADK
`BigQueryAgentAnalyticsPlugin` and prints the exact connection settings for the
Looker Marketplace **Agent Analytics** Block:
https://marketplace.looker.com/marketplace/detail/agent_analytics

Usage:
    uv run python setup_bigquery_looker.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def main() -> None:
    project_id = (
        os.environ.get("BQ_ANALYTICS_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    if not project_id or project_id == "your-gcp-project-id":
        raise SystemExit("ERROR: Set GOOGLE_CLOUD_PROJECT or BQ_ANALYTICS_PROJECT_ID in .env first.")

    dataset_id = os.environ.get("BQ_ANALYTICS_DATASET_ID", "agent_analytics").strip()
    table_id = os.environ.get("BQ_ANALYTICS_TABLE_ID", "agent_events").strip()
    location = os.environ.get("BQ_ANALYTICS_LOCATION", "US").strip()

    client = bigquery.Client(project=project_id, location=location)

    # 1. Ensure Dataset exists
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = location
    dataset_ref.description = (
        "Google ADK + LangGraph + CrewAI Agent Analytics telemetry dataset "
        "for Looker Marketplace Agent Analytics Block."
    )
    client.create_dataset(dataset_ref, exists_ok=True)
    print(f"[1/3] BigQuery Dataset ready: {project_id}.{dataset_id} (location={location})")

    # 2. Initialize BigQueryAgentAnalyticsPlugin schema & per-event-type views
    from google.adk.plugins.bigquery_agent_analytics_plugin import (
        BigQueryAgentAnalyticsPlugin,
        BigQueryLoggerConfig,
        _get_events_schema,
    )

    config = BigQueryLoggerConfig(
        enabled=True,
        table_id=table_id,
        create_views=True,
        auto_schema_upgrade=True,
        log_multi_modal_content=True,
        log_session_metadata=True,
        enable_otel_correlation=True,
        custom_tags={"app": "travel_concierge"},
    )
    plugin = BigQueryAgentAnalyticsPlugin(
        project_id=project_id,
        dataset_id=dataset_id,
        table_id=table_id,
        location=location,
        config=config,
    )
    plugin.client = client
    plugin.full_table_id = f"{project_id}.{dataset_id}.{table_id}"
    plugin._schema = _get_events_schema()
    plugin._ensure_schema_exists()
    print(f"[2/3] BigQuery Table & Looker Views ready: {project_id}.{dataset_id}.{table_id}")

    # 3. Create a polyglot summary view across ADK, LangGraph, and CrewAI
    polyglot_view_id = f"{project_id}.{dataset_id}.v_polyglot_agent_metrics"
    polyglot_sql = f"""
    CREATE OR REPLACE VIEW `{polyglot_view_id}` AS
    SELECT
      timestamp,
      event_id,
      event_type,
      agent,
      COALESCE(
        JSON_VALUE(attributes, '$.custom_tags.framework'),
        CASE
          WHEN agent = 'booking_agent' THEN 'langgraph'
          WHEN agent = 'pre_trip_agent' THEN 'crewai'
          ELSE 'google_adk'
        END
      ) AS agent_framework,
      session_id,
      invocation_id,
      user_id,
      trace_id,
      span_id,
      parent_span_id,
      CAST(JSON_VALUE(latency_ms, '$.total_ms') AS INT64) AS total_latency_ms,
      status,
      JSON_VALUE(content, '$.text_summary') AS text_summary
    FROM `{project_id}.{dataset_id}.{table_id}`
    """
    client.query(polyglot_sql).result()
    print(f"[3/3] Polyglot Looker View ready: {polyglot_view_id}")

    print("\n" + "=" * 76)
    print("  LOOKER MARKETPLACE — AGENT ANALYTICS BLOCK CONFIGURATION")
    print("  URL: https://marketplace.looker.com/marketplace/detail/agent_analytics")
    print("=" * 76)
    print(f"  1. Looker BigQuery Connection Project : {project_id}")
    print(f"  2. BigQuery Dataset Name              : {dataset_id}")
    print(f"  3. Agent Events Table Name            : {table_id}")
    print(f"  4. Auto-Created Looker Views          : {dataset_id}.v_* (v_llm_request, v_llm_response,")
    print("                                          v_tool_starting, v_tool_completed,")
    print("                                          v_agent_starting, v_agent_completed,")
    print("                                          v_user_message_received, v_polyglot_agent_metrics)")
    print("=" * 76)


if __name__ == "__main__":
    main()
