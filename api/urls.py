from django.urls import path
from api.views import (
    ContextualizeView,
    ExtractClaimsView,
    DatawrapperChartView,
    RunListView,
    RunDetailView,
    ChartCorrectionView,
    DataCorrectionView,
)

urlpatterns = [
    path("contextualize", ContextualizeView.as_view(), name="contextualize"),
    path("extract-claims", ExtractClaimsView.as_view(), name="extract-claims"),
    path("contextualize/<uuid:trace_id>/datawrapper", DatawrapperChartView.as_view(), name="datawrapper-chart"),
    path("runs", RunListView.as_view(), name="run-list"),
    path("runs/<uuid:trace_id>", RunDetailView.as_view(), name="run-detail"),
    path("runs/<uuid:trace_id>/corrections/chart", ChartCorrectionView.as_view(), name="correction-chart"),
    path("runs/<uuid:trace_id>/corrections/data", DataCorrectionView.as_view(), name="correction-data"),
]
