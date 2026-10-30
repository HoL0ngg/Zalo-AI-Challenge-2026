"""Tests for the Vietnamese normalizer: noise types, protected spans, idempotence."""
import json
import unicodedata
from pathlib import Path

import pytest

from datamate.understanding import build_lexicon_cached, build_teencode_cached
from datamate.understanding.normalizer import build_lexicon, build_teencode, normalize
from datamate.understanding.resources import load_homographs, load_lexicon, load_teencode
from datamate.understanding.textutil import clean, fold

LEXICON = build_lexicon_cached(tuple(load_lexicon()), tuple(sorted(load_homographs())))
TEENCODE = build_teencode_cached(load_teencode())


def norm(text, protected=None):
    return normalize(text, LEXICON, TEENCODE, protected).normalized


@pytest.mark.parametrize("noisy,expected", [
    # missing diacritics (whole sentence or some words)
    ("THANG nay chot duoc bao nhieu don hop le?", "tháng này chốt được bao nhiêu đơn hợp lệ?"),
    ("Tuan roi san pham nao ban nhiu nhat?", "tuần rồi sản phẩm nào bán nhiều nhất?"),
    ("Cung kỳ năm ngoái sản pham doanh thu cao nhat là gì?", "cùng kỳ năm ngoái sản phẩm doanh thu cao nhất là gì?"),
    ("Cùng kỳ nam ngoai sản phẩm doanh thu cao nhất là gì", "cùng kỳ năm ngoái sản phẩm doanh thu cao nhất là gì"),
    # abbreviations / teencode
    ("sp bn dc ko", "sản phẩm bao nhiêu được không"),
    ("Hôm qua có bán đc sản phẩm P0017 khôngg?", "Hôm qua có bán được sản phẩm P0017 không?"),
    ("hnay dthu bnhieu", "hôm nay doanh thu bao nhiêu"),
    ("Doanh thu tuần rồi tăng giảm bao nhiêu % so với tuần liền trước đó",
     "Doanh thu tuần rồi tăng giảm bao nhiêu phần trăm so với tuần liền trước đó"),
    ("sl 10% kh", "số lượng 10% khách hàng"),
    ("giá 5 k", "giá 5 k"),  # "k" after a number is a thousand suffix, never "không"
    # repeated letters
    ("Tổng doanh thu tháng này TÍNH đến hôm nay là bao nhiêuuu?", "Tổng doanh thu tháng này tính đến hôm nay là bao nhiêu?"),
    ("Thang trướcc cửa hàng thu được bao nhiêu tiền bán hàng?", "tháng trước cửa hàng thu được bao nhiêu tiền bán hàng?"),
    ("doanhhh thu nhiềuuu", "doanh thu nhiều"),
    ("xoong nồi", "xoong nồi"),  # legitimate double vowel in a word we do not know is kept
    # Telex / transposition slips, glued words
    ("thnags nay", "tháng này"),
    ("Trongdịp Tết gan nhất, sản phẩm nào bán chạy nhất?", "Trong dịp Tết gần nhất, sản phẩm nào bán chạy nhất?"),
    ("Nhânviên ca tối nào mang về doanh thu nhiều nhất tháng trước?", "Nhân viên ca tối nào mang về doanh thu nhiều nhất tháng trước?"),
    ("tăng trởưng thnags nay", "tăng trưởng tháng này"),
    # mixed noise
    ("Doanhthu dịp Tết gần nhất là bao nhiêu?", "doanh thu dịp Tết gần nhất là bao nhiêu?"),
    ("Doanh  thu   tháng này", "Doanh thu tháng này"),
    ("tăng trởưng thnags nay hnay bn ko", "tăng trưởng tháng này hôm nay bao nhiêu không"),
])
def test_noise_types(noisy, expected):
    assert norm(noisy) == expected


def test_unsure_tokens_are_kept():
    assert norm("bán voi bạn") == "bán voi bạn"      # homographs stay as typed
    assert norm("la ma do") == "la ma do"
    assert norm("sản phẩm nào bán chạy nhất tháng này") == "sản phẩm nào bán chạy nhất tháng này"


def test_ambiguous_keys_are_not_restored():
    assert norm("la") == "la" and norm("do") == "do" and norm("ma") == "ma"
    assert norm("tom chua cay") == "tom chua cay"  # "chua" may be sour, not "chưa"


def test_original_case_kept_unless_changed():
    assert norm("Trà Tắc Mật ONG M") == "Trà Tắc Mật ONG M"
    assert norm("PVC D21 NGK") == "PVC D21 NGK"
    assert norm("ĐƠN HÀNG") == "đơn hàng"  # known words typed in capitals are lowercased


def test_protected_spans_are_untouched():
    protected = {"Nước ngọt Pepsi", "Cà phê sữa", "Trà Tắc Mật ONG"}
    out = norm("thang truoc nuoc ngot pepsi ban duoc bn, ca phe sua dc ko", protected)
    assert "nuoc ngot pepsi" in out and "ca phe sua" in out  # entity spans as typed
    assert out.startswith("tháng trước") and "bao nhiêu" in out and "được không" in out
    assert norm("Trà Tắc Mật ONG sp", protected) == "Trà Tắc Mật ONG sản phẩm"
    assert norm("san pham P0017 va SKU12ab", None) == "sản phẩm P0017 và SKU12ab"  # codes are always protected
    # protected values with fewer than three letters are ignored (they would block real words)
    assert norm("sp bn", {"sp"}) == "sản phẩm bao nhiêu"


def test_idempotent_on_noise_and_dictionaries():
    samples = [
        "THANG nay chot duoc bao nhieu don hop le?", "Trongdịp Tết gan nhất", "doanhhh thu", "thnags nay",
        "sp bn dc ko", "Cung kỳ nam ngoai", "bao nhiêuuu", "Nhânviên ca tối", "xoong nồi", "ONG M",
    ]
    for canonical, variants in load_teencode().items():
        samples.extend([canonical, *variants])
    dataset = Path("dataset/train/questions.jsonl")
    if dataset.exists():
        samples.extend(json.loads(line)["question"] for line in dataset.read_text(encoding="utf-8").splitlines())
    for text in samples:
        once = norm(text)
        assert norm(once) == once, text


def test_nfc_and_nfd_inputs_agree():
    text = "Doanh thu tháng này tăng trưởng bao nhiêu phần trăm so với tháng trước?"
    nfd = unicodedata.normalize("NFD", text)
    assert nfd != text
    assert norm(nfd) == norm(text) == text
    noisy = "Thang nay chot duoc bao nhieu đơn hợp lệ?"
    assert norm(unicodedata.normalize("NFD", noisy)) == norm(unicodedata.normalize("NFC", noisy))


def test_normalized_ascii_and_cleaning():
    result = normalize("  Tháng\tnày ​ chốt\x07 được  ", LEXICON, TEENCODE)
    assert result.normalized == "Tháng này chốt được"
    assert result.normalized_ascii == "thang nay chot duoc"
    assert len(fold("Đơn hàng Việt")) == len("Đơn hàng Việt") and fold("Đơn hàng Việt") == "don hang viet"
    assert clean("a b\n c") == "a b c"


def test_changes_are_reported_and_original_untouched():
    original = "sp  bn dc"
    result = normalize(original, LEXICON, TEENCODE)
    assert original == "sp  bn dc"
    assert [c[0] for c in result.changes] == ["teencode"] * 3
    assert ("teencode", "bn", "bao nhiêu") in result.changes


def test_teencode_table_integrity():
    table = TEENCODE.table
    assert table and all(isinstance(v, str) and v for v in table.values())
    # no variant maps to two different canonicals (they are dropped, never guessed)
    raw = {"a b": ["x"], "c d": ["x", "y"]}
    assert build_teencode(raw).table == {("y",): "c d"}
    # variants that are only the unaccented spelling go through the lexicon channel
    assert ("san", "pham") not in table and ("sp",) in table
    assert ("dt",) not in table and ("cn",) not in table  # ambiguous abbreviations are not expanded


def test_lexicon_file_is_clean_and_current():
    lines = list(load_lexicon())
    assert lines == sorted(set(lines))
    assert all(unicodedata.normalize("NFC", line) == line and line == line.lower() for line in lines)
    assert "tháng này" in lines and "bao nhiêu" in lines
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_lexicon", Path("scripts/build_lexicon.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build() == lines, "data/vi_lexicon.txt is stale: run python scripts/build_lexicon.py"


def test_lexicon_builder_unit():
    lexicon = build_lexicon(["tháng này", "bán chạy", "bàn", "bán", "xin chào"], homographs=["xin"])
    assert lexicon.phrases[("thang", "nay")] == (("tháng", "này"),)
    assert lexicon.unigrams["ban"] == frozenset({"bán", "bàn"})  # ambiguous key
    assert "xin" in lexicon.homographs
    tiny = normalize("thang nay ban chay", lexicon, build_teencode({})).normalized
    assert tiny == "tháng này bán chạy"
