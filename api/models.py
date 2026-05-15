import uuid
from django.db import models


class ContextualizationRun(models.Model):
    class Status(models.TextChoices):
        PENDING        = "pending"
        OK             = "ok"
        NOT_VERIFIABLE = "not_verifiable"
        ERROR          = "error"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim         = models.TextField()
    context       = models.TextField(blank=True, default="")
    language      = models.CharField(max_length=10, default="es")

    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    is_verifiable = models.BooleanField(null=True)
    error_message = models.TextField(blank=True, default="")

    created_at    = models.DateTimeField(auto_now_add=True)
    completed_at  = models.DateTimeField(null=True)
    duration_ms   = models.IntegerField(null=True)

    final_text    = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.claim[:60]} [{self.status}]"


class ToolCall(models.Model):
    run       = models.ForeignKey(ContextualizationRun, on_delete=models.CASCADE, related_name="tool_calls")
    turn      = models.PositiveSmallIntegerField()
    tool_name = models.CharField(max_length=100)
    arguments = models.JSONField()
    result    = models.JSONField(null=True)
    called_at = models.DateTimeField()

    class Meta:
        ordering = ["turn"]

    def __str__(self):
        return f"turn {self.turn} — {self.tool_name}"


class ExtractedDataContext(models.Model):
    run            = models.OneToOneField(ContextualizationRun, on_delete=models.CASCADE, related_name="data_context")
    indicator_code = models.CharField(max_length=100)
    indicator_name = models.CharField(max_length=500)
    database_id    = models.CharField(max_length=50)
    database_name  = models.CharField(max_length=200)
    definition     = models.TextField(blank=True, default="")
    periodicity    = models.CharField(max_length=50, blank=True, default="")
    unit           = models.CharField(max_length=50, blank=True, default="")
    source_url     = models.URLField(max_length=500, blank=True, default="")
    start_year     = models.SmallIntegerField(null=True)
    end_year       = models.SmallIntegerField(null=True)
    area_codes     = models.JSONField(default=list)
    columns        = models.JSONField(default=list)
    records        = models.JSONField(default=list)

    def __str__(self):
        return f"{self.indicator_code} ({self.start_year}–{self.end_year})"


class ChartSelection(models.Model):
    run         = models.OneToOneField(ContextualizationRun, on_delete=models.CASCADE, related_name="chart_selection")
    strategy    = models.CharField(max_length=50)
    x_field     = models.CharField(max_length=100)
    y_field     = models.CharField(max_length=100)
    color_field = models.CharField(max_length=100, blank=True, null=True)
    facet_field = models.CharField(max_length=100, blank=True, null=True)
    highlight   = models.CharField(max_length=20, blank=True, null=True)
    top_n       = models.SmallIntegerField(null=True)
    chart_spec  = models.JSONField(null=True)

    def __str__(self):
        return f"{self.strategy} — {self.run_id}"


class DatawrapperChart(models.Model):
    run          = models.OneToOneField(ContextualizationRun, on_delete=models.CASCADE, related_name="datawrapper_chart")
    chart_id     = models.CharField(max_length=20)
    chart_url    = models.URLField(max_length=500)
    embed_code   = models.TextField(blank=True, default="")
    created_at   = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)

    def __str__(self):
        return f"{self.chart_id} — {self.run_id}"
