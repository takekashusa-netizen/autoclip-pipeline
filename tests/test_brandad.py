"""Brand ad generator: frames render for a brief with no logo/product (fallback card) without a voice model."""
import json, os, sys
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "studio", "motion"))


def test_brandad_frames_and_score(tmp_path):
    import brandad as BA
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"brand": "Testco", "headline": "Your best day starts here", "goal": "book",
                                 "benefits": ["One", "Two", "Three"], "url": "testco.com"}))
    vo = tmp_path / "vo"; vo.mkdir(); meta = {}
    for k, txt in BA.lines_of(json.loads(brief.read_text())):
        sf.write(vo / f"vo_{k}.wav", np.zeros(24000, np.float32), 24000); meta[k] = {"text": txt, "dur": 1.0, "sr": 24000}
    (vo / "vo.json").write_text(json.dumps(meta))
    BA.load(str(brief), str(tmp_path))
    for t in (0.2, BA.AT["hook"] + 0.5, BA.AT["b2"] + 0.3, BA.AT["cta"] + 0.6, BA.DUR - 0.1):
        im = BA.frame(t); assert im.size == (1080, 1920) and im.mode == "RGB"
    BA.score(str(tmp_path)); a, sr = sf.read(tmp_path / "score.wav")
    assert abs(len(a) / sr - BA.DUR) < 0.05


def test_render_is_gated_on_an_approved_plan(tmp_path):
    import brandad as BA, pytest
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"brand": "Gate", "headline": "Lock it first", "benefits": ["a", "b", "c"]}))
    vo = tmp_path / "vo"; vo.mkdir(); meta = {}
    for k, txt in BA.lines_of(json.loads(brief.read_text())):
        sf.write(vo / f"vo_{k}.wav", np.zeros(12000, np.float32), 24000); meta[k] = {"text": txt, "dur": 0.5, "sr": 24000}
    (vo / "vo.json").write_text(json.dumps(meta))
    with pytest.raises(SystemExit):                       # no approval -> plan is produced, render refused
        BA.main(str(brief), str(tmp_path))
    assert (tmp_path / "storyboard.jpg").exists() and json.loads((tmp_path / "cutlist.json").read_text())["voice"][0]["start"] > 0
    BA.main(str(brief), str(tmp_path), mode="approve"); assert BA.approved(str(brief), str(tmp_path))
    brief.write_text(json.dumps({"brand": "Gate", "headline": "Changed after approval", "benefits": ["a", "b", "c"]}))
    assert not BA.approved(str(brief), str(tmp_path))     # edits after approval need a new approval
