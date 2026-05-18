import json
import logging
import time

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.claim_extractor import extract as extract_claims
from api.datawrapper import create_and_publish
from api.models import ChartSelection, ContextualizationRun, DatawrapperChart, ExtractedDataContext, ToolCall
from api.serializers import ContextualizeRequestSerializer, ContextualizeTextSerializer, CorrectionRequestSerializer
from pipeline.contextualize import run, correct_chart, correct_data

logger = logging.getLogger(__name__)


def _coerce_json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(value)}


def _serialize_data_context(data_ctx) -> dict:
    return {
        "indicator_code": data_ctx.indicator_code,
        "indicator_name": data_ctx.indicator_name,
        "database_id": data_ctx.database_id,
        "database_name": data_ctx.database_name,
        "definition": data_ctx.definition,
        "periodicity": data_ctx.periodicity,
        "unit": data_ctx.unit,
        "source_url": data_ctx.source_url,
        "area_codes": data_ctx.area_codes,
        "columns": data_ctx.columns,
        "time_range": {"start_year": data_ctx.start_year, "end_year": data_ctx.end_year},
    }


def _serialize_chart_selection(chart_sel) -> dict:
    return {
        "chart_spec": chart_sel.chart_spec,
        "chart_params": {
            "strategy": chart_sel.strategy,
            "x_field": chart_sel.x_field,
            "y_field": chart_sel.y_field,
            "color_field": chart_sel.color_field,
            "facet_field": chart_sel.facet_field,
            "highlight": chart_sel.highlight,
            "top_n": chart_sel.top_n,
        },
    }


def _serialize_dw_chart(dw) -> dict:
    return {
        "chart_id": dw.chart_id,
        "chart_url": dw.chart_url,
        "embed_code": dw.embed_code,
        "published_at": dw.published_at,
    }


def _run_and_save(
    claim: str,
    context: str | None,
    language: str,
    *,
    parent_run: ContextualizationRun | None = None,
    correction_instruction: str = "",
) -> ContextualizationRun:
    """Run the contextualization pipeline for a single claim and persist the result."""
    run_record = ContextualizationRun.objects.create(
        claim=claim,
        context=context or "",
        language=language,
        parent_run=parent_run,
        correction_instruction=correction_instruction,
        status=ContextualizationRun.Status.PENDING,
    )
    trace_id = str(run_record.id)

    t_start = time.monotonic()
    try:
        result = run(claim=claim, context=context, language=language, correction=correction_instruction or None)
    except Exception as exc:
        run_record.status = ContextualizationRun.Status.ERROR
        run_record.error_message = str(exc)
        run_record.completed_at = timezone.now()
        run_record.duration_ms = int((time.monotonic() - t_start) * 1000)
        run_record.save()
        logger.exception("[contextualize] pipeline error trace_id=%s", trace_id)
        return run_record

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

    tool_trace = result.get("tool_trace", [])
    if tool_trace:
        now = timezone.now()
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
    return run_record


class ContextualizeView(APIView):
    def post(self, request):
        serializer = ContextualizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        claim = data["claim"]
        context = data.get("context") or None
        language = data.get("language", "es")

        logger.info(
            "[contextualize] request received claim=%r language=%s",
            claim[:80],
            language,
        )

        run_record = _run_and_save(claim, context, language)
        trace_id = str(run_record.id)

        if run_record.status == ContextualizationRun.Status.ERROR:
            return Response(
                {"status": "error", "trace_id": trace_id, "detail": run_record.error_message},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result_data = {
            "status": "ok",
            "trace_id": trace_id,
            "is_verifiable": run_record.is_verifiable,
            "final_text": run_record.final_text,
        }

        data_ctx = getattr(run_record, "data_context", None)
        if data_ctx:
            result_data.update(_serialize_data_context(data_ctx))

        chart_sel = getattr(run_record, "chart_selection", None)
        if chart_sel:
            result_data.update(_serialize_chart_selection(chart_sel))

        return Response(result_data)


class ExtractClaimsView(APIView):
    def post(self, request):
        serializer = ContextualizeTextSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        text = data["text"]

        logger.info("[contextualize-text] extracting claims")

        try:
            extracted = extract_claims(text)
        except Exception as exc:
            logger.exception("[contextualize-text] claim extraction failed")
            return Response(
                {"status": "error", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info("[contextualize-text] found %d claims", len(extracted))
        return Response({
            "status": "ok",
            "claims": [{"claim": c.claim, "rationale": c.rationale} for c in extracted],
        })


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

        existing = getattr(run_record, "datawrapper_chart", None)
        if existing:
            return Response(_serialize_dw_chart(existing))

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
        return Response(_serialize_dw_chart(dw_chart), status=status.HTTP_201_CREATED)


def _get_latest_in_chain(run_record: ContextualizationRun) -> ContextualizationRun:
    """Walk correction chain and return the most recent run."""
    latest = run_record
    for correction in run_record.corrections.order_by("-created_at")[:1]:
        latest = _get_latest_in_chain(correction)
    return latest


class ChartCorrectionView(APIView):
    def post(self, request, trace_id):
        serializer = CorrectionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            parent = ContextualizationRun.objects.get(pk=trace_id)
        except ContextualizationRun.DoesNotExist:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

        if not parent.is_verifiable:
            return Response(
                {"detail": "Parent run is not verifiable; no chart data to correct."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parent_data_ctx = parent.data_context
            parent_chart_sel = parent.chart_selection
        except (ExtractedDataContext.DoesNotExist, ChartSelection.DoesNotExist):
            return Response(
                {"detail": "Chart data not available for this run."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instruction = serializer.validated_data["instruction"]

        # Resolve the root run for parent linkage
        root = parent if parent.parent_run_id is None else ContextualizationRun.objects.get(pk=parent.parent_run_id)

        run_record = ContextualizationRun.objects.create(
            parent_run=root,
            correction_instruction=instruction,
            claim=root.claim,
            context=root.context,
            language=root.language,
            status=ContextualizationRun.Status.PENDING,
        )

        parent_data_dict = {
            "indicator_code": parent_data_ctx.indicator_code,
            "indicator_name": parent_data_ctx.indicator_name,
            "database_id": parent_data_ctx.database_id,
            "database_name": parent_data_ctx.database_name,
            "definition": parent_data_ctx.definition,
            "periodicity": parent_data_ctx.periodicity,
            "unit": parent_data_ctx.unit,
            "source_url": parent_data_ctx.source_url,
            "area_codes": parent_data_ctx.area_codes,
            "columns": parent_data_ctx.columns,
            "time_range": {"start_year": parent_data_ctx.start_year, "end_year": parent_data_ctx.end_year},
            "records": parent_data_ctx.records,
        }

        t_start = time.monotonic()
        try:
            result = correct_chart(parent_data_dict, root.claim, parent.final_text, instruction)
        except Exception as exc:
            run_record.status = ContextualizationRun.Status.ERROR
            run_record.error_message = str(exc)
            run_record.completed_at = timezone.now()
            run_record.duration_ms = int((time.monotonic() - t_start) * 1000)
            run_record.save()
            logger.exception("[chart-correction] pipeline error trace_id=%s", run_record.id)
            return Response(
                {"status": "error", "trace_id": str(run_record.id), "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run_record.is_verifiable = True
        run_record.final_text = result["final_text"]
        run_record.status = ContextualizationRun.Status.OK
        run_record.completed_at = timezone.now()
        run_record.duration_ms = int((time.monotonic() - t_start) * 1000)
        run_record.save()

        time_range = result.get("time_range") or {}
        ExtractedDataContext.objects.create(
            run=run_record,
            indicator_code=result["indicator_code"],
            indicator_name=result["indicator_name"],
            database_id=result["database_id"],
            database_name=result["database_name"],
            definition=result["definition"],
            periodicity=result["periodicity"],
            unit=result["unit"],
            source_url=result["source_url"],
            start_year=time_range.get("start_year"),
            end_year=time_range.get("end_year"),
            area_codes=result["area_codes"],
            columns=result["columns"],
            records=result["records"],
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

        return Response({
            "status": "ok",
            "trace_id": str(run_record.id),
            "parent_trace_id": str(root.id),
            "correction_instruction": instruction,
            "is_verifiable": True,
            "final_text": run_record.final_text,
            **_serialize_data_context(run_record.data_context),
            **_serialize_chart_selection(run_record.chart_selection),
        }, status=status.HTTP_201_CREATED)


class DataCorrectionView(APIView):
    def post(self, request, trace_id):
        serializer = CorrectionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            parent = ContextualizationRun.objects.get(pk=trace_id)
        except ContextualizationRun.DoesNotExist:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

        instruction = serializer.validated_data["instruction"]

        root = parent if parent.parent_run_id is None else ContextualizationRun.objects.get(pk=parent.parent_run_id)

        run_record = _run_and_save(
            root.claim,
            root.context or None,
            root.language,
            parent_run=root,
            correction_instruction=instruction,
        )

        result_data = {
            "status": run_record.status,
            "trace_id": str(run_record.id),
            "parent_trace_id": str(root.id),
            "correction_instruction": instruction,
            "is_verifiable": run_record.is_verifiable,
            "final_text": run_record.final_text,
        }

        if run_record.status == ContextualizationRun.Status.ERROR:
            result_data["detail"] = run_record.error_message
            return Response(result_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        data_ctx = getattr(run_record, "data_context", None)
        if data_ctx:
            result_data.update(_serialize_data_context(data_ctx))

        chart_sel = getattr(run_record, "chart_selection", None)
        if chart_sel:
            result_data.update(_serialize_chart_selection(chart_sel))

        return Response(result_data, status=status.HTTP_201_CREATED)


class RunListView(APIView):
    def get(self, request):
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = 20
        # Only root runs — corrections are accessible via the corrections array on detail
        qs = ContextualizationRun.objects.filter(parent_run__isnull=True).order_by("-created_at")
        total = qs.count()
        offset = (page - 1) * page_size
        runs = list(qs[offset: offset + page_size])

        results = []
        for r in runs:
            latest = _get_latest_in_chain(r)
            results.append({
                "trace_id": str(r.id),
                "latest_trace_id": str(latest.id),
                "claim": r.claim,
                "status": latest.status,
                "is_verifiable": latest.is_verifiable,
                "language": r.language,
                "created_at": r.created_at,
                "duration_ms": latest.duration_ms,
            })

        return Response({
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": results,
        })


class RunDetailView(APIView):
    def get(self, request, trace_id):
        try:
            run_record = ContextualizationRun.objects.get(pk=trace_id)
        except ContextualizationRun.DoesNotExist:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = {
            "status": run_record.status,
            "trace_id": str(run_record.id),
            "is_verifiable": run_record.is_verifiable,
            "final_text": run_record.final_text,
            "claim": run_record.claim,
            "context": run_record.context,
            "language": run_record.language,
            "created_at": run_record.created_at,
            "duration_ms": run_record.duration_ms,
        }

        data_ctx = getattr(run_record, "data_context", None)
        if data_ctx:
            payload.update(_serialize_data_context(data_ctx))

        chart_sel = getattr(run_record, "chart_selection", None)
        if chart_sel:
            payload.update(_serialize_chart_selection(chart_sel))

        payload["tool_trace"] = [
            {
                "tool": tc.tool_name,
                "arguments": tc.arguments,
                "result": tc.result,
            }
            for tc in run_record.tool_calls.order_by("turn")
        ]

        dw = getattr(run_record, "datawrapper_chart", None)
        if dw:
            payload["datawrapper"] = _serialize_dw_chart(dw)

        if run_record.parent_run_id:
            payload["parent_trace_id"] = str(run_record.parent_run_id)
            payload["correction_instruction"] = run_record.correction_instruction
        else:
            payload["corrections"] = [
                {
                    "trace_id": str(c.id),
                    "correction_instruction": c.correction_instruction,
                    "status": c.status,
                    "created_at": c.created_at,
                }
                for c in run_record.corrections.order_by("created_at")
            ]

        return Response(payload)
