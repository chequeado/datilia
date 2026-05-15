import json
import logging
import time

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.datawrapper import create_and_publish
from api.models import ChartSelection, ContextualizationRun, DatawrapperChart, ExtractedDataContext, ToolCall
from api.serializers import ContextualizeRequestSerializer
from pipeline.contextualize import run

logger = logging.getLogger(__name__)


def _coerce_json(value):
    """Ensure a tool result value is JSON-serialisable (dict/list/None)."""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(value)}


class ContextualizeView(APIView):
    def post(self, request):
        serializer = ContextualizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        claim = data["claim"]
        context = data.get("context") or None
        language = data.get("language", "es")

        run_record = ContextualizationRun.objects.create(
            claim=claim,
            context=context or "",
            language=language,
            status=ContextualizationRun.Status.PENDING,
        )
        trace_id = str(run_record.id)

        logger.info(
            "[contextualize] request received claim=%r language=%s trace_id=%s",
            claim[:80],
            language,
            trace_id,
        )

        t_start = time.monotonic()
        try:
            result = run(claim=claim, context=context, language=language)
        except Exception as exc:
            run_record.status = ContextualizationRun.Status.ERROR
            run_record.error_message = str(exc)
            run_record.completed_at = timezone.now()
            run_record.duration_ms = int((time.monotonic() - t_start) * 1000)
            run_record.save()
            logger.exception("[contextualize] pipeline error trace_id=%s", trace_id)
            return Response(
                {"status": "error", "trace_id": trace_id, "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        duration_ms = int((time.monotonic() - t_start) * 1000)
        is_verifiable = result.get("is_verifiable", False)

        run_record.is_verifiable = is_verifiable
        run_record.final_text = result.get("final_text", "")
        run_record.status = (
            ContextualizationRun.Status.OK
            if is_verifiable
            else ContextualizationRun.Status.NOT_VERIFIABLE
        )
        run_record.completed_at = timezone.now()
        run_record.duration_ms = duration_ms
        run_record.save()

        now = timezone.now()
        tool_trace = result.get("tool_trace", [])
        if tool_trace:
            ToolCall.objects.bulk_create([
                ToolCall(
                    run=run_record,
                    turn=i,
                    tool_name=entry["tool"],
                    arguments=entry.get("arguments") or {},
                    result=_coerce_json(entry.get("result")),
                    called_at=now,
                )
                for i, entry in enumerate(tool_trace)
            ])

        if is_verifiable:
            time_range = result.get("time_range") or {}
            ExtractedDataContext.objects.create(
                run=run_record,
                indicator_code=result.get("indicator_code", ""),
                indicator_name=result.get("indicator_name", ""),
                database_id=result.get("database_id", ""),
                database_name=result.get("database_name", ""),
                definition=result.get("definition", ""),
                periodicity=result.get("periodicity", ""),
                unit=result.get("unit", ""),
                source_url=result.get("source_url", ""),
                start_year=time_range.get("start_year"),
                end_year=time_range.get("end_year"),
                area_codes=result.get("area_codes", []),
                columns=result.get("columns", []),
                records=result.get("records", []),
            )

            chart_params = result.get("chart_params") or {}
            ChartSelection.objects.create(
                run=run_record,
                strategy=chart_params.get("strategy", ""),
                x_field=chart_params.get("x_field", ""),
                y_field=chart_params.get("y_field", ""),
                color_field=chart_params.get("color_field"),
                facet_field=chart_params.get("facet_field"),
                highlight=chart_params.get("highlight"),
                top_n=chart_params.get("top_n"),
                chart_spec=result.get("chart_spec"),
            )

        logger.info(
            "[contextualize] saved run trace_id=%s is_verifiable=%s duration_ms=%d",
            trace_id,
            is_verifiable,
            duration_ms,
        )

        response_data = {k: v for k, v in result.items() if k != "records"}
        return Response({"status": "ok", "trace_id": trace_id, **response_data})


class DatawrapperChartView(APIView):
    def post(self, request, trace_id):
        try:
            run_record = ContextualizationRun.objects.get(pk=trace_id)
        except ContextualizationRun.DoesNotExist:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

        if not run_record.is_verifiable:
            return Response(
                {"detail": "Run is not verifiable; no chart data available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Return existing chart without recreating
        existing = getattr(run_record, "datawrapper_chart", None)
        if existing:
            return Response({
                "chart_id": existing.chart_id,
                "chart_url": existing.chart_url,
                "embed_code": existing.embed_code,
                "published_at": existing.published_at,
            })

        try:
            data_ctx = run_record.data_context
            chart_sel = run_record.chart_selection
        except (ExtractedDataContext.DoesNotExist, ChartSelection.DoesNotExist):
            return Response(
                {"detail": "Chart data not available for this run."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = create_and_publish(data_ctx, chart_sel)
        except Exception as exc:
            logger.exception("[datawrapper] chart creation failed trace_id=%s", trace_id)
            return Response(
                {"detail": f"Datawrapper API error: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        dw_chart = DatawrapperChart.objects.create(
            run=run_record,
            chart_id=result["chart_id"],
            chart_url=result["chart_url"],
            embed_code=result["embed_code"],
            published_at=result["published_at"],
        )

        logger.info(
            "[datawrapper] chart saved trace_id=%s chart_id=%s",
            trace_id,
            dw_chart.chart_id,
        )
        return Response({
            "chart_id": dw_chart.chart_id,
            "chart_url": dw_chart.chart_url,
            "embed_code": dw_chart.embed_code,
            "published_at": dw_chart.published_at,
        }, status=status.HTTP_201_CREATED)
