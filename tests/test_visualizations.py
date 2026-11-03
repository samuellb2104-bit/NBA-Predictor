from analytics.visualizations import (
    filter_by_status,
    format_health,
    health_label,
    present_statuses,
    status_color,
    status_css,
    status_label_es,
)


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


def test_status_color_distingue_estados():
    assert status_color("Out") != status_color("Suspension")
    assert status_color("Out") != status_color("Day-To-Day")
    assert status_color("out") == status_color("Out")


def test_status_desconocido_es_neutro():
    for s in ("Questionable", "", None):
        assert status_color(s) == "#95a5a6"
        assert "rgba(149, 165, 166" in status_css(s)


def test_status_label_es():
    assert status_label_es("Out") == "Fuera"
    assert status_label_es("Day-To-Day") == "Día a día"
    assert status_label_es("Suspension") == "Suspendido"
    assert status_label_es("Doubtful") == "Doubtful"
    assert status_label_es(None) == "Sin estado"


def test_status_css_no_fija_color_de_texto():
    css = status_css("Out")
    assert "rgba(231, 76, 60" in css
    assert "color:" not in css.replace("background-color:", "")


def test_filtro_y_estados_presentes():
    ps = [{"status": "Out"}, {"status": "Day-To-Day"}, {"status": "Out"}, {"status": None}]
    assert present_statuses(ps) == ["Out", "Day-To-Day"]
    assert filter_by_status(ps, ["Out"]) == [ps[0], ps[2]]
    assert filter_by_status(ps, []) == []
