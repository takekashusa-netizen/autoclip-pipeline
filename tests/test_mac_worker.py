import os, plistlib, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worker import mac_customer_job as W


def test_plist_is_valid_and_runs_every_5_minutes():
    p = plistlib.loads(W.plist_xml("/usr/bin/python3", "/Users/x/autoclip-pipeline").encode())
    assert p["Label"] == W.LABEL and p["StartInterval"] == 300 and p["ProgramArguments"][-1] == "once"


def test_once_refuses_without_settings(tmp_path, monkeypatch):
    for k in W.REQUIRED: monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(W, "ENV_FILE", str(tmp_path / "none.env"))
    assert W.once() == 2                                  # tells the owner what's missing, claims nothing


def test_env_file_parsing(tmp_path, monkeypatch):
    for k in W.REQUIRED: monkeypatch.delenv(k, raising=False)
    f = tmp_path / "e.env"; f.write_text("# c\nTAKEKASH_TOKEN=abc\nBUCKET_NAME=\"b\"\n")
    missing = W.load_env(str(f))
    assert os.environ["TAKEKASH_TOKEN"] == "abc" and os.environ["BUCKET_NAME"] == "b" and "BUCKET_ENDPOINT" in missing
