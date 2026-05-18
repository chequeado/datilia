from rest_framework import serializers


class ContextualizeRequestSerializer(serializers.Serializer):
    claim = serializers.CharField()
    context = serializers.CharField(required=False, allow_blank=True, default="")
    language = serializers.CharField(required=False, default="es")


class ContextualizeTextSerializer(serializers.Serializer):
    text = serializers.CharField()


class CorrectionRequestSerializer(serializers.Serializer):
    instruction = serializers.CharField()
