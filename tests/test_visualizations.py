from analytics.visualizations import format_health, health_label


def test_sin_datos_no_es_saludable():
    # 1.0 neutro sin datos NO debe presentarse como saludable
    assert health_label(1.0, False)[0] == "Sin datos"
    assert format_health(1.0, False) == "Sin datos"
    assert health_label(None, True)[0] == "Sin datos"


def test_umbrales():
    assert health_label(1.0, True)[0] == "Saludable"
    assert health_label(0.9, True)[0] == "Saludable"
    assert health_label(0.8, True)[0] == "Algunas bajas"
    assert health_label(0.6, True)[0] == "Bajas importantes"
    assert health_label(0.2, True)[0] == "Plantel diezmado"


def test_format_health():
    assert format_health(0.85, True) == "85% (Algunas bajas)"
