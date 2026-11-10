# -*- coding: utf-8 -*-
"""Làm sạch dữ liệu 1 shop: đọc mọi file -> tìm dòng tên cột -> đổi giá trị -> gộp sheet cùng cấu trúc.

Hàm chính:   load_clean_tables(shop_dir) -> (tables, meta)
  tables : dict {tên bảng: DataFrame}  (GIỮ tên cột gốc; chỉ làm sạch giá trị)
  meta   : dict {"warnings": [...], "tables": {tên bảng: thông tin}, "date_from", "date_to"}

Nguyên tắc: nhận biết cột bằng NỘI DUNG, không bằng tên shop/tên file; không hiểu thì để nguyên và ghi cảnh báo.
Chỉ đọc dữ liệu gốc, không bao giờ ghi vào thư mục shop.
"""
import csv
import math
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

from value_parsers import parse_money, parse_qty, parse_datetime, _core

_ERRORS = {"#value!", "#n/a", "#ref!", "#div/0!", "#name?", "#null!", "#num!"}
_TOTAL_WORDS = ("tổng", "tong", "total", "cộng", "cong", "ghi chú", "ghi chu", "lưu ý", "luu y", "note")
_MONEY_MARK = re.compile(r"(?i)\d\s*(k|tr|triệu|tỷ|tỉ)\b|\d\s*(đ|₫|đồng|vnd)\b|^\s*-?\d{1,3}([.,]\d{3})+\s*$|^\s*-?\d{1,3}( \d{3})+\s*$")
_QTY_UNIT = re.compile(r"^\d+(?:[.,]\d+)?\s*[^\W\d_]{1,10}\.?$")
_STATUS_NAME = re.compile(r"(?i)trang thai|trạng thái|status|tinh trang|tình trạng")


def _ascii(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class _NameMatcher:
    """So khớp TÊN CỘT theo từ nguyên (đã bỏ dấu, tách ở _ và khoảng trắng).
    v1 dùng chuỗi con nên 'han' bắt nhầm 'Thanh tien', 'Tien hang', 'Chi nhanh', 'Ma hang'."""
    def __init__(self, words, glued_prefix=()):
        self.words = tuple(words)
        self.glued_prefix = tuple(glued_prefix)
        self._rx = re.compile(r"(?:^| )(?:%s)(?: |$)" % "|".join(re.escape(w) for w in self.words))

    @staticmethod
    def _split(name):
        t = str(name)
        t = "".join((" " + ch) if (i and ch.isupper() and t[i - 1].islower()) else ch for i, ch in enumerate(t))  # NgayBan -> Ngay Ban
        return _ascii(t)

    def search(self, name):
        a = self._split(name)
        if self._rx.search(a):
            return True
        # tên dính liền kiểu 'ngayban', 'thoigianlap': chỉ chấp nhận tiền tố an toàn
        return bool(self.glued_prefix) and any(tok.startswith(self.glued_prefix) for tok in a.split())


_DATE_NAME = _NameMatcher(("ngay", "date", "datetime", "thoi gian", "gio", "time", "han", "hsd", "han su dung",
                           "created", "sinh nhat", "ngay sinh", "tao luc", "ap dung", "nhan viec"),
                          glued_prefix=("ngay", "thoigian"))
# cột KHÔNG phải ngày phát sinh giao dịch (hạn dùng, ngày sinh, ngày tạo danh mục...) -> loại khỏi date_from/date_to
_NON_EVENT_DATE = _NameMatcher(("han", "hsd", "han su dung", "sinh", "sinh nhat", "ngay sinh", "tao luc", "tao",
                                "created", "ap dung", "nhan viec", "han tra", "han thanh toan", "gio"))
_MONEY_NAME = _NameMatcher(("gia", "tien", "thanh tien", "tong tien", "amount", "price", "cost", "don gia",
                            "gia von", "gia ban", "gia nhap", "doanh thu", "revenue", "phi", "giam gia", "ck", "tong",
                            "khuyen mai", "con no", "da tra", "da thu", "khach tra", "so tien", "tri gia",
                            "tong bill", "tong tien", "tien hang", "cong no", "con lai", "gia tri", "ship", "tien thu"))
_QTY_NAME = _NameMatcher(("sl", "so luong", "quantity", "qty", "sl quy doi", "so luong ban"))
_NO_FILL_KEY = _NameMatcher(("barcode", "vach", "ean", "sinh", "sinh nhat", "ngay sinh", "birthday", "sdt",
                             "dien thoai", "phone", "email", "gia", "gia cu", "gia moi", "tien", "price", "amount",
                             "sku", "hsd", "han su dung"))


def _demojibake(text):
    """Tên file giải nén từ zip không cờ UTF-8 bị đọc theo cp437: 'Danh s├ích h├áng' -> 'Danh sách hàng'."""
    t = str(text)
    if t.isascii():
        return t
    try:
        fixed = t.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t
    return fixed if fixed != t else t


def _empty(v):
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    try:
        return bool(v != v)  # NaN, NaT
    except Exception:
        return False


# ───────────────────────── 1. ĐỌC FILE ─────────────────────────
def _read_xlsx(path):
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    out = []
    for name in wb.sheetnames:
        rows, empty_run = [], 0
        for r in wb[name].iter_rows(values_only=True):
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in r):
                empty_run += 1
                if empty_run > 300:  # sheet khai báo hàng triệu dòng trống -> dừng sớm
                    break
            else:
                empty_run = 0
            rows.append(list(r))
        while rows and all(_empty(v) for v in rows[-1]):
            rows.pop()
        out.append((name, rows))
    wb.close()
    return out


def _read_csv(path):
    raw = Path(path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    delim = ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    rows = [r for r in csv.reader(text.splitlines(), delimiter=delim)]
    return [("csv", rows)]


def _read_sqlite(path):
    con = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True)
    out = []
    try:
        names = [r[0] for r in con.execute("select name from sqlite_master where type in ('table','view')")]
        for n in names:
            cur = con.execute('select * from "%s"' % n.replace('"', '""'))
            cols = [d[0] for d in cur.description]
            out.append((n, [cols] + [list(r) for r in cur.fetchall()]))
    finally:
        con.close()
    return out


def read_any(path):
    """Trả về list[(tên sheet/bảng, rows)] cho .xlsx/.xlsm/.csv/.tsv/.sqlite/.db."""
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext in (".csv", ".tsv", ".txt"):
        return _read_csv(path)
    if ext in (".sqlite", ".sqlite3", ".db"):
        return _read_sqlite(path)
    return []


# ───────────────────────── 2. TÌM DÒNG TÊN CỘT ─────────────────────────
def detect_header(rows, scan=15):
    """Trả về (chỉ số dòng tên cột, nhãn nhóm hoặc None, chữ ở các dòng tiêu đề phía trên)."""
    head = rows[:scan]
    sc = [sum(1 for v in r if isinstance(v, str) and v.strip()) for r in head]
    if not sc or max(sc) == 0:
        return None, None, ""
    need = max(2, math.ceil(0.7 * max(sc))) if max(sc) >= 2 else 1
    idx = next((i for i, c in enumerate(sc) if c >= need and i + 1 < len(rows)), None)
    if idx is None:
        return None, None, ""
    groups = None
    if idx > 0 and 2 <= sc[idx - 1] < sc[idx]:
        groups, last = [], None
        for v in rows[idx - 1]:
            if isinstance(v, str) and v.strip():
                last = v.strip()
            groups.append(last)
    title = " | ".join(str(v) for r in rows[:idx] for v in r if not _empty(v))
    return idx, groups, title


def _dedupe(names, groups):
    seen, out = {}, []
    for i, n in enumerate(names):
        key = n.casefold()
        if key in seen:
            seen[key] += 1
            g = groups[i] if groups and i < len(groups) and groups[i] else None
            cand = "%s_%s" % (g, n) if g else "%s_%d" % (n, seen[key])
            out.append(cand)
        else:
            seen[key] = 1
            out.append(n)
    return out


def rows_to_frame(rows):
    """Danh sách dòng thô -> (DataFrame, thông tin). Trả (None, info) nếu không có dữ liệu."""
    idx, groups, title = detect_header(rows)
    info = {"header_row": idx, "title": title[:200], "group_labels": bool(groups), "rows_raw": len(rows)}
    if idx is None:
        return None, info
    width = max(len(r) for r in rows[idx:]) if rows[idx:] else 0
    hdr = list(rows[idx]) + [None] * (width - len(rows[idx]))
    names = []
    for j, v in enumerate(hdr):
        names.append(str(v).strip() if not _empty(v) else "col_%d" % (j + 1))
    names = _dedupe(names, groups)
    body = [list(r) + [None] * (width - len(r)) for r in rows[idx + 1:]]
    df = pd.DataFrame(body, columns=names, dtype=object)
    df = df[~df.apply(lambda r: all(_empty(v) for v in r), axis=1)]
    hdr_cf = {str(n).strip().casefold() for n in hdr if not _empty(n)}

    def _is_repeat_header(r):
        vals = [str(v).strip().casefold() for v in r if not _empty(v)]
        return len(vals) >= 2 and sum(1 for v in vals if v in hdr_cf) >= max(2, 0.5 * len(vals))
    rep = df.apply(_is_repeat_header, axis=1) if len(df) else pd.Series([], dtype=bool)
    info["repeated_header_rows_dropped"] = int(rep.sum()) if len(df) else 0
    df = df[~rep] if len(df) else df
    empty_cols = [c for c in df.columns if c.startswith("col_") and df[c].map(_empty).all()]
    df = df.drop(columns=empty_cols).reset_index(drop=True)
    # bỏ dòng tổng ở cuối bảng
    dropped = 0
    while len(df):
        first = next((v for v in df.iloc[-1].tolist() if not _empty(v)), None)
        if isinstance(first, str) and first.strip().lower().startswith(_TOTAL_WORDS):
            df = df.iloc[:-1]
            dropped += 1
        else:
            break
    info["total_rows_dropped"] = dropped
    return df, info


# ───────────────────────── 3. LÀM SẠCH GIÁ TRỊ ─────────────────────────
def _clean_text(v):
    if isinstance(v, str):
        s = unicodedata.normalize("NFC", v.replace("\u00a0", " ")).strip()
        s = re.sub(r"[ \t]{2,}", " ", s)
        if not s or s.lower() in _ERRORS:
            return None
        return s
    return v


def _sample(col, n=500):
    vals = [v for v in col.tolist() if not _empty(v)]
    return vals if len(vals) <= n else vals[:: max(1, len(vals) // n)][:n]


def _year_from(text):
    m = re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(text))
    return int(m[0]) if m else None


def _is_plain_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return isinstance(v, str) and bool(re.fullmatch(r"-?\d+(?:[.,]\d+)?", v.strip()))


def _fail_note(warnings, tag, kind, c, orig, out):
    bad = [o for o, v in zip(orig, out) if not _empty(o) and v is None]
    if bad:
        warnings.append("%s: cột %s '%s' có %d ô không đổi được, ví dụ %s" % (tag, kind, c, len(bad), [str(x) for x in bad[:3]]))
    return len(bad)


def clean_columns(df, year_hint, warnings, tag):
    """Đổi cột tiền / ngày / số lượng theo NỘI DUNG (+ tên cột khi nội dung chỉ là số thuần).
    Trả về (df, done). done['unparsed'] = {cột: số ô lỗi}; cột nhìn giống tiền/ngày/SL nhưng không đổi được thì có cảnh báo."""
    done = {"money": [], "date": [], "qty": [], "autoyear": [], "unparsed": {}, "skipped": {}, "numeric_text": []}
    for c in list(df.columns):
        df[c] = df[c].map(_clean_text)
    for c in list(df.columns):
        col = df[c]
        smp = _sample(col)
        if len(smp) < 3:
            continue
        strs = [v for v in smp if isinstance(v, str)]
        name_date = bool(_DATE_NAME.search(c))
        name_qty = bool(_QTY_NAME.search(c))
        name_money = bool(_MONEY_NAME.search(c)) and not name_date and not name_qty
        # --- ngày ---
        strong = sum(1 for v in smp if hasattr(v, "year") or (isinstance(v, str) and (name_date or not re.fullmatch(r"\d+(\.\d+)?", v)) and _core(v, year_hint) is not None))
        serial = sum(1 for v in smp if isinstance(v, (int, float)) and not isinstance(v, bool) and _core(v) is not None)
        if (strong / len(smp) >= 0.5 and (strong + (serial if name_date else 0)) / len(smp) >= 0.85) \
                or (name_date and serial / len(smp) >= 0.85):
            orig = col.tolist()
            parsed = [_core(v, year_hint) if not _empty(v) else None for v in orig]
            # Excel tự đoán năm khi gõ '1/1' -> năm hiện tại: nếu mọi ngày kiểu datetime nửa đêm lệch cùng 1 năm so với năm của sheet thì sửa
            if year_hint:
                mid = [(o, p) for o, p in zip(orig, parsed)
                       if p and hasattr(o, "year") and not isinstance(o, str) and p[1] is None]
                yrs = {p[0].year for _, p in mid}
                if mid and len(yrs) == 1 and yrs != {year_hint} and len(mid) >= 0.9 * sum(1 for p in parsed if p):
                    fixed = []
                    for p in parsed:
                        if p and p[1] is None:
                            try:
                                p = (p[0].replace(year=year_hint), None)
                            except ValueError:
                                pass
                        fixed.append(p)
                    parsed = fixed
                    done["autoyear"].append(c)
                    warnings.append("%s: cột '%s' có năm %s khác năm của sheet (%s) -> đã sửa về %s (Excel tự đoán năm?). Cần kiểm tra."
                                    % (tag, c, sorted(yrs)[0], year_hint, year_hint))
            out = []
            for o, p in zip(orig, parsed):
                if p is None:
                    out.append(None)
                else:
                    out.append(p[0].isoformat() if p[1] is None else "%s %s" % (p[0].isoformat(), p[1].strftime("%H:%M:%S")))
            n_bad = _fail_note(warnings, tag, "ngày", c, orig, out)
            if n_bad:
                done["unparsed"][c] = n_bad
            df[c] = out
            done["date"].append(c)
            continue
        # --- tiền ---
        marked = sum(1 for v in strs if _MONEY_MARK.search(v))
        plain = sum(1 for v in smp if _is_plain_num(v))
        # v1 chỉ nhận cột có ký hiệu (k/tr/đ/dấu ngăn nghìn) nên cột giá toàn số thuần ('7000') bị bỏ sót, nằm lại dạng chuỗi.
        # v2: cột có tên giống tiền và >=85% giá trị là số/ký hiệu tiền cũng được đổi thành số nguyên VND.
        money_like = marked >= 1 or (name_money and (plain + marked) / len(smp) >= 0.85)
        if money_like:
            ok = sum(1 for v in smp if parse_money(v) is not None)
            if ok / len(smp) >= 0.85:
                orig = col.tolist()
                out = [parse_money(v) if not _empty(v) else None for v in orig]
                n_bad = _fail_note(warnings, tag, "tiền", c, orig, out)
                if n_bad:
                    done["unparsed"][c] = n_bad
                df[c] = pd.array(out, dtype="Int64")
                done["money"].append(c)
                continue
            # nhìn giống tiền nhưng quá nhiều ô lỗi -> KHÔNG đổi, nhưng phải báo (v1 im lặng)
            bad_ex = [str(v) for v in smp if parse_money(v) is None][:3]
            warnings.append("%s: cột '%s' trông như tiền nhưng chỉ %d/%d ô đổi được -> để nguyên. Ví dụ lỗi %s"
                            % (tag, c, ok, len(smp), bad_ex))
            done["skipped"][c] = "tien"
        # --- số lượng (có thể kèm đơn vị) ---
        with_unit = sum(1 for v in strs if _QTY_UNIT.match(v) and not _is_plain_num(v))
        n_plain = sum(1 for v in smp if _is_plain_num(v))   # v1 không tính chuỗi '1','2' -> cột lẫn '1' và '1 ly' bị bỏ sót
        if with_unit / len(smp) >= 0.3 and (with_unit + n_plain) / len(smp) >= 0.85:
            orig = col.tolist()
            parsed = [parse_qty(v) if not _empty(v) else None for v in orig]
            n_bad = sum(1 for o, p in zip(orig, parsed) if not _empty(o) and p is None)
            if n_bad:
                ex = [str(o) for o, p in zip(orig, parsed) if not _empty(o) and p is None][:3]
                warnings.append("%s: cột số lượng '%s' có %d ô không đổi được (đã để trống), ví dụ %s" % (tag, c, n_bad, ex))
                done["unparsed"][c] = n_bad
            df[c] = [p[0] if p else None for p in parsed]
            df[c + "__don_vi"] = [(p[1] or None) if p else None for p in parsed]
            done["qty"].append(c)
            continue
        # cột chuỗi toàn số nhưng tên không giống tiền/SL: không tự đổi (có thể là mã/SĐT), chỉ LIỆT KÊ để người kiểm tra
        if strs and sum(1 for v in strs if re.fullmatch(r"-?\d+(?:[.,]\d+)?", v)) / len(smp) >= 0.95:
            done["numeric_text"].append(c)
    return df, done


def fill_order_level(df):
    """Điền ô trống cấp ĐƠN (mã đơn, ngày, khách…) xuống các dòng hàng bên dưới. Trả về (df, các cột đã điền)."""
    n = len(df)
    if n < 6:
        return df, []
    key = None
    for c in list(df.columns)[:8]:
        if _NO_FILL_KEY.search(c):   # v1 điền nhầm 'Mã barcode', 'Ngày sinh', 'Giá cũ' ở bảng danh mục
            continue
        col = df[c]
        blank = col.map(_empty).mean()
        nn = col.dropna()
        if 0.10 <= blank <= 0.90 and len(nn) >= 3 and nn.astype(str).nunique() / len(nn) >= 0.9 \
                and nn.map(lambda v: isinstance(v, str)).mean() >= 0.8:
            key = c
            break
    if key is None:
        return df, []
    starts = ~df[key].map(_empty)
    grp = starts.cumsum()
    filled = []
    for c in df.columns:
        col = df[c]
        first_nb = (~col.map(_empty))[starts].mean()
        later_blank = col.map(_empty)[~starts].mean() if (~starts).any() else 0
        if c != key and _NO_FILL_KEY.search(c):
            continue
        if c == key or (first_nb >= 0.5 and later_blank >= 0.95):
            df[c] = col.where(~col.map(_empty), None).groupby(grp).ffill()
            filled.append(c)
    return df, filled


# ───────────────────────── 4. GỘP SHEET & CHẠY CẢ SHOP ─────────────────────────
def _base_name(stem):
    s = stem
    for _ in range(4):
        s2 = re.sub(r"(?i)[_\-\s]*(?:t|thang|thg|th)?\d{1,4}$", "", s)
        if s2 == s:
            break
        s = s2
    return s or stem


def _sig(df):
    return {_ascii(c) for c in df.columns if not c.endswith("__don_vi")}


def _similar(a, b):
    return len(a & b) / max(1, len(a | b)) >= 0.9


def load_clean_tables(shop_dir):
    shop_dir = Path(shop_dir)
    warnings, parts = [], []
    for f in sorted(shop_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".tsv", ".sqlite", ".sqlite3", ".db"):
            continue
        try:
            sheets = read_any(f)
        except Exception as e:  # không để 1 file hỏng làm sập cả shop
            warnings.append("%s: không đọc được (%s)" % (f.name, str(e)[:120]))
            continue
        for sname, rows in sheets:
            tag = "%s/%s" % (f.name, sname)
            if f.suffix.lower() in (".sqlite", ".sqlite3", ".db"):
                df, info = (pd.DataFrame(rows[1:], columns=rows[0], dtype=object), {"header_row": 0, "title": "", "rows_raw": len(rows)})
            else:
                df, info = rows_to_frame(rows)
            if df is None or df.empty:
                continue
            year = _year_from(sname) or _year_from(f.stem) or _year_from(info.get("title", ""))
            df, filled = fill_order_level(df)
            df, done = clean_columns(df, year, warnings, tag)
            status_vals = {}
            for c in df.columns:  # chỉ LIỆT KÊ giá trị trạng thái; ý nghĩa do rulebook quyết định (việc 3), không đoán ở đây
                if _STATUS_NAME.search(c):
                    status_vals[c] = df[c].dropna().astype(str).value_counts().head(15).to_dict()
            info.update({"year_hint": year, "ffilled": filled, "status_values": status_vals, **done, "rows": len(df)})
            parts.append({"file": f, "sheet": sname, "df": df, "sig": _sig(df), "info": info})

    # gom nhóm theo cấu trúc giống nhau
    clusters = []
    for p in parts:
        for cl in clusters:
            if _similar(cl[0]["sig"], p["sig"]):
                cl.append(p)
                break
        else:
            clusters.append([p])

    tables, meta_tables, used = {}, {}, set()
    for cl in clusters:
        files = {p["file"] for p in cl}
        base = _base_name(_demojibake(cl[0]["file"].stem))
        same_file_clusters = [c2 for c2 in clusters if {p["file"] for p in c2} & files]
        name = base
        if len(files) == 1 and len(same_file_clusters) > 1:
            name = "%s__%s" % (base, _base_name(_demojibake(str(cl[0]["sheet"]))) or _demojibake(str(cl[0]["sheet"])))
        k, final = 2, name
        while final in used:
            final = "%s_%d" % (name, k)
            k += 1
        used.add(final)
        frames = []
        for p in cl:
            d = p["df"].copy()
            d["_source_file"] = p["file"].name
            d["_source_sheet"] = p["sheet"]
            d["_sheet_year"] = p["info"].get("year_hint")
            frames.append(d)
        full = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        tables[final] = full
        dates = {}
        for c in full.columns:
            if c.startswith("_"):
                continue
            if any(c in p["info"].get("date", []) for p in cl):
                vals = full[c].dropna().astype(str)
                if len(vals):
                    dates[c] = (vals.min()[:10], vals.max()[:10])
        meta_tables[final] = {
            "rows": len(full), "n_parts": len(cl), "files": sorted(f.name for f in files),
            "money": sorted({c for p in cl for c in p["info"].get("money", [])}),
            "date": sorted({c for p in cl for c in p["info"].get("date", [])}),
            "qty": sorted({c for p in cl for c in p["info"].get("qty", [])}),
            "ffilled": sorted({c for p in cl for c in p["info"].get("ffilled", [])}),
            "date_ranges": dates,
            "status_values": {c: v for p in cl for c, v in p["info"].get("status_values", {}).items()},
            "unparsed": {c: n for p in cl for c, n in p["info"].get("unparsed", {}).items()},
            "skipped": {c: v for p in cl for c, v in p["info"].get("skipped", {}).items()},
            "numeric_text": sorted({c for p in cl for c in p["info"].get("numeric_text", [])}),
        }
    def _span(skip_non_event):
        lo, hi = [], []
        for t in meta_tables.values():
            for c, v in t["date_ranges"].items():
                if skip_non_event and _NON_EVENT_DATE.search(c):
                    continue
                if "2015" <= v[0] <= "2035":
                    lo.append(v[0])
                if "2015" <= v[1] <= "2035":
                    hi.append(v[1])
        return (min(lo) if lo else None), (max(hi) if hi else None)
    all_from, all_to = _span(False)
    ev_from, ev_to = _span(True)
    ev_from, ev_to = ev_from or all_from, ev_to or all_to
    meta = {"warnings": warnings, "tables": meta_tables,
            "date_from": ev_from, "date_to": ev_to,          # ngày phát sinh giao dịch (đã loại HSD, ngày sinh, ngày tạo...)
            "date_from_all": all_from, "date_to_all": all_to}  # như v1: mọi cột ngày
    return tables, meta
