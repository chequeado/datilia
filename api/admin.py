from django.contrib import admin
from .models import ContextualizationRun, ToolCall, ExtractedDataContext, ChartSelection, DatawrapperChart


class ToolCallInline(admin.TabularInline):
    model = ToolCall
    extra = 0
    readonly_fields = ("turn", "tool_name", "arguments", "result", "called_at")
    can_delete = False


class ExtractedDataContextInline(admin.StackedInline):
    model = ExtractedDataContext
    extra = 0
    readonly_fields = (
        "indicator_code", "indicator_name", "database_id", "database_name",
        "definition", "periodicity", "unit", "source_url",
        "start_year", "end_year", "area_codes", "columns", "records",
    )
    can_delete = False


class DatawrapperChartInline(admin.StackedInline):
    model = DatawrapperChart
    extra = 0
    readonly_fields = ("chart_id", "chart_url", "embed_code", "created_at", "published_at")
    can_delete = False


class ChartSelectionInline(admin.StackedInline):
    model = ChartSelection
    extra = 0
    readonly_fields = (
        "strategy", "x_field", "y_field", "color_field",
        "facet_field", "highlight", "top_n", "chart_spec",
    )
    can_delete = False


@admin.register(ContextualizationRun)
class ContextualizationRunAdmin(admin.ModelAdmin):
    list_display = ("claim_preview", "status", "is_verifiable", "language", "duration_ms", "created_at")
    list_filter = ("status", "is_verifiable", "language")
    search_fields = ("claim", "final_text", "error_message")
    readonly_fields = (
        "id", "claim", "context", "language", "status", "is_verifiable",
        "error_message", "created_at", "completed_at", "duration_ms", "final_text",
    )
    inlines = [ToolCallInline, ExtractedDataContextInline, ChartSelectionInline, DatawrapperChartInline]

    @admin.display(description="claim")
    def claim_preview(self, obj):
        return obj.claim[:80]
