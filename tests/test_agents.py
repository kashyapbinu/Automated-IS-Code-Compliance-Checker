from src.agents import orchestrator, specialist, validator
from src.schemas import SCHEMAS, DrawingType, ParamStatus

from tests.conftest import make_extraction


def test_schema_sizes():
    for dtype, schema in SCHEMAS.items():
        keys = [p.key for p in schema]
        assert len(keys) == len(set(keys)), f"duplicate keys in {dtype}"
        assert 27 <= len(schema) <= 34, f"{dtype}: {len(schema)} params"


def test_parse_classification():
    c = orchestrator.parse_classification({"type": "Beam", "confidence": "0.9"})
    assert c.drawing_type == DrawingType.BEAM and c.confidence == 0.9
    c = orchestrator.parse_classification({"type": "staircase", "confidence": 2})
    assert c.drawing_type == DrawingType.UNKNOWN and c.confidence == 1.0


def test_to_extraction_fills_schema_and_flags_missing():
    data = {"params": [
        {"key": "concrete_grade", "value": "M25", "status": "found", "source_location": "NOTES 1"},
        {"key": "steel_grade", "value": None, "status": "found"},          # found without value -> missing
        {"key": "cover_slab", "value": "20 or 25?", "status": "ambiguous"},
        {"key": "made_up_key", "value": "x"},                               # dropped
    ]}
    ex = specialist.to_extraction(data, DrawingType.SLAB)
    assert [p.key for p in ex.params] == [s.key for s in SCHEMAS[DrawingType.SLAB]]
    d = ex.as_dict()
    assert d["concrete_grade"].status == ParamStatus.FOUND and d["concrete_grade"].clarification is None
    assert d["steel_grade"].status == ParamStatus.MISSING and d["steel_grade"].clarification
    assert d["cover_slab"].status == ParamStatus.AMBIGUOUS
    assert "made_up_key" not in d


def _messages(result):
    return " | ".join(i.message for i in result.issues)


def test_validator_column_steel_mismatch():
    ex = make_extraction(DrawingType.COLUMN, concrete_grade="M25", steel_grade="Fe500", column_size="300 x 450",
                         long_bar_count="8", long_bar_dia="16", steel_percentage="2.5", tie_dia="8")
    r = validator.rule_checks(ex)
    assert r.derived["steel_percentage_computed"] == 1.19
    assert any("does not match" in i.message and i.severity == "error" for i in r.issues), _messages(r)


def test_validator_slab_type_and_units():
    ex = make_extraction(DrawingType.SLAB, slab_thickness="125", short_span="3000", long_span="7000",
                         slab_type="two-way", cover_slab="200", main_bar_spacing="T10@150")
    r = validator.rule_checks(ex)
    assert r.derived["ly_lx"] == 2.33 and r.derived["slab_type_computed"] == "one-way"
    msgs = _messages(r)
    assert "implies one-way" in msgs
    assert "Cover (mm) = 200" in msgs


def test_validator_beam_derived():
    ex = make_extraction(DrawingType.BEAM, beam_width="230", beam_depth="800", bottom_bars="3-16 dia", cover_beam="25")
    r = validator.rule_checks(ex)
    assert r.derived["side_face_required"] is True
    assert r.derived["effective_depth_mm"] == 767


def test_validator_footing_smaller_than_column():
    ex = make_extraction(DrawingType.FOUNDATION, footing_size="300 x 300", column_size="300 x 450", sbc="20 t/m2")
    r = validator.rule_checks(ex)
    assert "not larger than the column" in _messages(r)
    assert r.derived["sbc_kN_m2"] == 200


def test_validator_flags_missing_required():
    ex = make_extraction(DrawingType.BEAM)
    r = validator.rule_checks(ex)
    assert any(i.params == ["beam_width"] and "missing" in i.message for i in r.issues)
