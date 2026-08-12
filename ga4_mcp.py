#!/usr/bin/env python3
"""
MCP Server for Google Analytics 4 (GA4) reporting.

Provides tools to query traffic, top pages, traffic sources, and custom
event/conversion data for a GA4 property via the Google Analytics Data API.

Authentication: uses a Google service account. Set GOOGLE_APPLICATION_CREDENTIALS
to the path of the service account JSON key file, and GA4_PROPERTY_ID to the
numeric GA4 property ID (Admin > Property Settings > Property ID). The service
account must be added as a Viewer on the GA4 property (Admin > Property Access
Management).
"""

import asyncio
import json
import os
from enum import Enum
from typing import List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)
from google.api_core.exceptions import GoogleAPIError, PermissionDenied
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, field_validator

mcp = MCPServer("ga4_mcp")

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

PROPERTY_ID_ENV_VAR = "GA4_PROPERTY_ID"
DEFAULT_ROW_LIMIT = 20
CONVERSION_EVENT_NAMES = ["form_submission", "cta_click", "project_click", "scroll_depth"]


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _get_property_id() -> str:
    property_id = os.environ.get(PROPERTY_ID_ENV_VAR)
    if not property_id:
        raise RuntimeError(
            f"Missing {PROPERTY_ID_ENV_VAR} environment variable. "
            "Set it to your numeric GA4 property ID (Admin > Property Settings)."
        )
    return property_id


def _get_client() -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient()


def _handle_api_error(e: Exception) -> str:
    if isinstance(e, PermissionDenied):
        return (
            "Error: Permission denied. Make sure the service account email has been "
            "added as a Viewer on this GA4 property (Admin > Property Access Management)."
        )
    if isinstance(e, GoogleAPIError):
        return f"Error: GA4 API request failed: {getattr(e, 'message', str(e))}"
    if isinstance(e, RuntimeError):
        return f"Error: {e}"
    return f"Error: Unexpected error occurred: {type(e).__name__}: {e}"


async def _run_report(request: RunReportRequest):
    client = _get_client()
    return await asyncio.to_thread(client.run_report, request)


def _resolve_date_range(start_date: str, end_date: str) -> DateRange:
    return DateRange(start_date=start_date, end_date=end_date)


def _format_rows_markdown(headers: List[str], rows: List[List[str]], title: str) -> str:
    lines = [f"# {title}", ""]
    if not rows:
        lines.append("No data found for this date range.")
        return "\n".join(lines)
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


DATE_FIELD_DESCRIPTION = (
    "Date in YYYY-MM-DD format, or a GA4 relative date keyword such as "
    "'today', 'yesterday', or 'NdaysAgo' (e.g. '28daysAgo')."
)


class TrafficOverviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    start_date: str = Field(default="28daysAgo", description=DATE_FIELD_DESCRIPTION)
    end_date: str = Field(default="today", description=DATE_FIELD_DESCRIPTION)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class TopPagesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    start_date: str = Field(default="28daysAgo", description=DATE_FIELD_DESCRIPTION)
    end_date: str = Field(default="today", description=DATE_FIELD_DESCRIPTION)
    limit: int = Field(default=DEFAULT_ROW_LIMIT, description="Maximum number of pages to return", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class TrafficSourcesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    start_date: str = Field(default="28daysAgo", description=DATE_FIELD_DESCRIPTION)
    end_date: str = Field(default="today", description=DATE_FIELD_DESCRIPTION)
    limit: int = Field(default=DEFAULT_ROW_LIMIT, description="Maximum number of sources to return", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class ConversionSummaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    start_date: str = Field(default="28daysAgo", description=DATE_FIELD_DESCRIPTION)
    end_date: str = Field(default="today", description=DATE_FIELD_DESCRIPTION)
    event_names: Optional[List[str]] = Field(
        default=None,
        description=(
            "Specific GA4 event names to summarize (e.g. ['form_submission', 'cta_click']). "
            "Defaults to the site's tracked engagement/conversion events if omitted."
        ),
        max_length=20,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class RunReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    dimensions: List[str] = Field(
        ...,
        description="GA4 dimension names (e.g. ['date', 'pagePath', 'sessionDefaultChannelGroup']).",
        min_length=1,
        max_length=9,
    )
    metrics: List[str] = Field(
        ...,
        description="GA4 metric names (e.g. ['sessions', 'activeUsers', 'screenPageViews', 'eventCount']).",
        min_length=1,
        max_length=10,
    )
    start_date: str = Field(default="28daysAgo", description=DATE_FIELD_DESCRIPTION)
    end_date: str = Field(default="today", description=DATE_FIELD_DESCRIPTION)
    limit: int = Field(default=DEFAULT_ROW_LIMIT, description="Maximum number of rows to return", ge=1, le=250)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")

    @field_validator("dimensions", "metrics")
    @classmethod
    def _non_empty_names(cls, v: List[str]) -> List[str]:
        cleaned = [item.strip() for item in v if item.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty name is required")
        return cleaned


@mcp.tool(
    name="ga4_traffic_overview",
    title="GA4 Traffic Overview",
    annotations=READ_ONLY_ANNOTATIONS,
)
async def ga4_traffic_overview(params: TrafficOverviewInput) -> str:
    """Get a high-level traffic summary for the site over a date range.

    Returns total sessions, active users, new users, engaged sessions, average
    engagement time, and engagement rate. Use this as the first tool to check
    "how is the site doing" before drilling into pages, sources, or events.

    Args:
        params (TrafficOverviewInput): start_date, end_date, response_format.

    Returns:
        str: Markdown table or JSON object with sessions, activeUsers,
        newUsers, engagedSessions, averageSessionDuration, engagementRate.
        Returns "Error: <message>" on failure.
    """
    try:
        property_id = _get_property_id()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[_resolve_date_range(params.start_date, params.end_date)],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
                Metric(name="newUsers"),
                Metric(name="engagedSessions"),
                Metric(name="averageSessionDuration"),
                Metric(name="engagementRate"),
            ],
        )
        response = await _run_report(request)

        if not response.rows:
            return "No traffic data found for this date range."

        row = response.rows[0]
        values = {
            "sessions": row.metric_values[0].value,
            "activeUsers": row.metric_values[1].value,
            "newUsers": row.metric_values[2].value,
            "engagedSessions": row.metric_values[3].value,
            "averageSessionDuration": f"{float(row.metric_values[4].value):.1f}s",
            "engagementRate": f"{float(row.metric_values[5].value) * 100:.1f}%",
        }

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"start_date": params.start_date, "end_date": params.end_date, **values}, indent=2)

        lines = [
            f"# Traffic Overview ({params.start_date} to {params.end_date})",
            "",
            f"- **Sessions**: {values['sessions']}",
            f"- **Active Users**: {values['activeUsers']}",
            f"- **New Users**: {values['newUsers']}",
            f"- **Engaged Sessions**: {values['engagedSessions']}",
            f"- **Avg. Session Duration**: {values['averageSessionDuration']}",
            f"- **Engagement Rate**: {values['engagementRate']}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="ga4_top_pages",
    title="GA4 Top Pages",
    annotations=READ_ONLY_ANNOTATIONS,
)
async def ga4_top_pages(params: TopPagesInput) -> str:
    """List the site's top pages by views over a date range.

    Args:
        params (TopPagesInput): start_date, end_date, limit, response_format.

    Returns:
        str: Markdown table or JSON array of {page, views, activeUsers}
        sorted by views descending. Returns "Error: <message>" on failure.
    """
    try:
        property_id = _get_property_id()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[_resolve_date_range(params.start_date, params.end_date)],
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="screenPageViews"), Metric(name="activeUsers")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
            limit=params.limit,
        )
        response = await _run_report(request)

        rows = [
            {
                "page": r.dimension_values[0].value,
                "views": r.metric_values[0].value,
                "activeUsers": r.metric_values[1].value,
            }
            for r in response.rows
        ]

        if not rows:
            return "No page view data found for this date range."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"start_date": params.start_date, "end_date": params.end_date, "pages": rows}, indent=2)

        return _format_rows_markdown(
            ["Page", "Views", "Active Users"],
            [[r["page"], r["views"], r["activeUsers"]] for r in rows],
            f"Top Pages ({params.start_date} to {params.end_date})",
        )
    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="ga4_traffic_sources",
    title="GA4 Traffic Sources",
    annotations=READ_ONLY_ANNOTATIONS,
)
async def ga4_traffic_sources(params: TrafficSourcesInput) -> str:
    """Break down sessions by channel/source (organic search, direct, referral, social, etc.).

    Args:
        params (TrafficSourcesInput): start_date, end_date, limit, response_format.

    Returns:
        str: Markdown table or JSON array of {channel, sessions, activeUsers}
        sorted by sessions descending. Returns "Error: <message>" on failure.
    """
    try:
        property_id = _get_property_id()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[_resolve_date_range(params.start_date, params.end_date)],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[Metric(name="sessions"), Metric(name="activeUsers")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=params.limit,
        )
        response = await _run_report(request)

        rows = [
            {
                "channel": r.dimension_values[0].value,
                "sessions": r.metric_values[0].value,
                "activeUsers": r.metric_values[1].value,
            }
            for r in response.rows
        ]

        if not rows:
            return "No traffic source data found for this date range."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"start_date": params.start_date, "end_date": params.end_date, "sources": rows}, indent=2)

        return _format_rows_markdown(
            ["Channel", "Sessions", "Active Users"],
            [[r["channel"], r["sessions"], r["activeUsers"]] for r in rows],
            f"Traffic Sources ({params.start_date} to {params.end_date})",
        )
    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="ga4_conversion_summary",
    title="GA4 Conversion & Engagement Event Summary",
    annotations=READ_ONLY_ANNOTATIONS,
)
async def ga4_conversion_summary(params: ConversionSummaryInput) -> str:
    """Summarize counts for key custom events (form submissions, CTA clicks, project clicks, scroll depth).

    These correspond to the custom GA4 events tracked on goldvalleysolutions.com
    (see frontend/src/assets/js/analytics.js and contact.js). Use this to see
    which calls-to-action and content are actually driving engagement, not just
    raw pageviews.

    Args:
        params (ConversionSummaryInput): start_date, end_date, event_names
            (defaults to ['form_submission', 'cta_click', 'project_click', 'scroll_depth']),
            response_format.

    Returns:
        str: Markdown table or JSON array of {eventName, count} sorted by
        count descending. Returns "Error: <message>" on failure.
    """
    try:
        property_id = _get_property_id()
        event_names = params.event_names or CONVERSION_EVENT_NAMES
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[_resolve_date_range(params.start_date, params.end_date)],
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            dimension_filter={
                "filter": {
                    "field_name": "eventName",
                    "in_list_filter": {"values": event_names},
                }
            },
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
            limit=100,
        )
        response = await _run_report(request)

        rows = [
            {"eventName": r.dimension_values[0].value, "count": r.metric_values[0].value}
            for r in response.rows
        ]

        if not rows:
            return f"No events found matching {event_names} for this date range."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(
                {"start_date": params.start_date, "end_date": params.end_date, "events": rows}, indent=2
            )

        return _format_rows_markdown(
            ["Event", "Count"],
            [[r["eventName"], r["count"]] for r in rows],
            f"Conversion & Engagement Events ({params.start_date} to {params.end_date})",
        )
    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="ga4_run_report",
    title="GA4 Custom Report",
    annotations=READ_ONLY_ANNOTATIONS,
)
async def ga4_run_report(params: RunReportInput) -> str:
    """Run an arbitrary GA4 report with any combination of dimensions and metrics.

    Use this for questions the higher-level tools (ga4_traffic_overview,
    ga4_top_pages, ga4_traffic_sources, ga4_conversion_summary) don't directly
    answer. Common dimensions: date, pagePath, sessionDefaultChannelGroup,
    deviceCategory, country, eventName. Common metrics: sessions, activeUsers,
    screenPageViews, engagementRate, eventCount, conversions.

    Args:
        params (RunReportInput): dimensions (1-9), metrics (1-10), start_date,
            end_date, limit, response_format.

    Returns:
        str: Markdown table or JSON array of rows keyed by the requested
        dimension/metric names. Returns "Error: <message>" on failure
        (e.g. invalid dimension/metric name).
    """
    try:
        property_id = _get_property_id()
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[_resolve_date_range(params.start_date, params.end_date)],
            dimensions=[Dimension(name=d) for d in params.dimensions],
            metrics=[Metric(name=m) for m in params.metrics],
            limit=params.limit,
        )
        response = await _run_report(request)

        headers = list(params.dimensions) + list(params.metrics)
        rows = [
            [dv.value for dv in r.dimension_values] + [mv.value for mv in r.metric_values]
            for r in response.rows
        ]

        if not rows:
            return "No data found for this dimension/metric combination and date range."

        if params.response_format == ResponseFormat.JSON:
            json_rows = [dict(zip(headers, row)) for row in rows]
            return json.dumps(
                {"start_date": params.start_date, "end_date": params.end_date, "rows": json_rows}, indent=2
            )

        return _format_rows_markdown(headers, rows, f"Custom Report ({params.start_date} to {params.end_date})")
    except Exception as e:
        return _handle_api_error(e)


if __name__ == "__main__":
    mcp.run()
