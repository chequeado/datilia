from django.urls import path
from api.views import ContextualizeView, DatawrapperChartView

urlpatterns = [
    path("contextualize", ContextualizeView.as_view(), name="contextualize"),
    path("contextualize/<uuid:trace_id>/datawrapper", DatawrapperChartView.as_view(), name="datawrapper-chart"),
]
