# -*- coding: utf-8 -*-
"""Việc 3 — gợi ý VAI TRÒ cho cột (bản nháp v0, quy tắc đơn giản). Người duyệt phải xem lại từng dòng.

infer_role(cot_chuan, loai_gia_tri, tien_to_ma) -> (vai_tro, ly_do)
Nhận biết theo (1) tiền tố mã (ORD…, SP…, KH…) và (2) tên cột đã bỏ dấu + bỏ khoảng trắng (xử lý cả 'mahoadon', 'tongtien').
Vai trò mang tính TỔNG QUÁT (vd 'thoi_diem', 'so_luong'); bảng nào (bán / nhập / thu) do bước phân loại bảng quyết định.
"""
import re

PREFIX_ROLE = {"ORD": "ma_don", "SP": "ma_hang", "KH": "ma_khach", "NCC": "ma_ncc", "PN": "ma_phieu_nhap", "NV": "ma_nhan_vien",
               "PT": "ma_phieu_thu", "PAY": "ma_phieu_thu", "LO": "ma_lo", "HD": "ma_don", "GD": "ma_giao_dich", "CT": "ma_chung_tu", "BIZ": "ma_cua_hang", "DEV": "ma_cua_hang"}

# (vai trò, regex trên tên đã bỏ dấu, bỏ khoảng trắng). Thứ tự quan trọng: quy tắc cụ thể đứng trước.
NAME_RULES = [
    ("ma_cua_hang", r"^(idcuahang|macuahang)$"),
    ("chi_nhanh", r"^(machinhanh|chinhanh|khuvuc)$"),
    ("gia_cu_moi", r"^(giacu|giamoi)$"),
    ("ma_phieu_tra", r"^(maphieutra|tienhoantra)$"),
    ("khong_dung", r"^(ghichu.*|mauhoghichu|mauhoghichu|mauhogichu|baohanh|trongluong|thuoctinh|hinhanh.*|mota.*|email|cccd|mastue|masothue|mst|"
                   r"ngaysinh|sinhnhat|ngaykhaitruong|thuonghieu|nguoitao|vitri|hoatchat|thuockedon|dangkinhdoanh|conkinhdoanh|dinhmuc.*|ton(nho|lon)nhat.*|"
                   r"tondai|duocbantructiep|bantructiep|hanghoalienquan|mahhlienquan|congty|chucvu|ngaynhanviec|diemtichluy|tongdiem|diemhienco|diemhientai|"
                   r"loaihinhkh.*|loaihinhkhach|doituongkh|nhomkhachhang|trangthaikh|dienthoai|sdt|sodienthoai|phone|didong|diachi.*|addr|imei|tengoi|"
                   r"nhomhang3cap|loaisanpham|loaihanghoa|nhomhanghoa|nhomhang|danhmuc|phanloai|thanhphanchinh|hinhthuc|nguon|luuy|note)$"),
    ("han_dung", r"^(hansudung|hsd)$"),
    ("ma_vach", r"^(mavach.*|mabarcode|barcode|ean)$"),
    ("lo", r"^(malo|lo|idlo)$"),
    ("gia_von", r"^(giavon.*|giavonlucban|giavonhang)$"),
    ("gia_nhap", r"^(gianhap|dongianhap|gianiemyet)$"),
    ("tong_tien_hang", r"^(tongtienhang|tienhangtruocgiam|giatrihang|tienhang|tienban)$"),
    ("tong_don", r"^(tongtien|tongtienphieu|tongphieu|tongcong|tongthanhtoan|tongsaugiamgia|trigia|giatri|sotien|tien|tong)$"),
    ("giam_gia", r"^(giamgia.*|giamd|chietkhau|ck|tiengiam|khuyenmai|makhuyenmai|bot|giam)$"),
    ("phi_ship", r"^(phiship|phivanchuyen|phigiaohang)$"),
    ("thue", r"^(thuegtgt|tylethue)$"),
    ("thanh_tien_dong", r"^(thanhtien.*|amount|ttdong|thanhtiend|tt)$"),
    ("don_gia", r"^(dongia.*|giaban.*|gia1dv|giasanpham|giadonvi|giale|gia|dg|giabanle|giahientai|gianiemyet)$"),
    ("so_luong", r"^(soluong(ban|giao|sanpham|le|nhap|tra|hang|mua)?|sl(ban|nhap|le|tra|mua)?|sluong|slg|sl)$"),
    ("quy_doi", r"^(slqd|slquydoi|quydoi|tylequydoi|tilequydoi|hesoquydoi|hesoqd|heso|soluongquydoi|quyradvle|giabantheodonviquydoi|donviquydoi|donvicoban|donvigoc|dvgoc|dvlon|dvnho|dvt?nhap|dvtcoban|slnhapquydoi|sltraquydoi|soluongdvtcoban|soluongtradvtcoban)$"),
    ("don_vi", r"^(donvitinh|dvt|donvi|dv|dvtinh|dvi|dtinh|dvitinh)$"),
    ("ten_hang", r"^(tenhang(hoa)?|tensanpham|tensp|hang(hoa|ban)?|sanpham|product|mathang|tenmathang|chitiethang|hangapdung)$"),
    ("ma_hang", r"^(mahang(hoa|ban)?|masanpham(ban)?|masp|mahh|mahhoa|masku|sku|idsp|mahhoa)$"),
    ("ten_khach", r"^(tenkhachhang|khachhang(ten)?|khach|tenkh|hoten|customer|khachlesi|benmua|doitac)$"),
    ("ma_khach", r"^(makh(mua)?|makhachhang|makhach(mua)?|customerid|idkh)$"),
    ("nhan_vien", r"^(nguoiban|nhanvienban|manvban|manhanvien|nguoigiaohang)$"),
    ("kenh_ban", r"^(kenhban(hang)?|kenh)$"),
    ("phuong_thuc_tt", r"^(phuongthuc(tt|thanhtoan)?|pttt|hinhthucthanhtoan|cachhoantien)$"),
    ("trang_thai", r"^(trangthai(don(hang)?|xuly|phieu)?|status|tinhtrang|xuly)$"),
    ("cong_no", r"^(conno|no|congno|duno|chuatra|conphaithu|canphaitra|cantrancc|canstra)$"),
    ("da_tra", r"^(khachdatra|khachtra|datra|dathu|dagop|khachdatra|sotienthu|gopthang)$"),
    ("ton_kho", r"^(tonkho|toncuoiky|toncuoi|tonthuc)$"),
    ("thoi_diem", r"^(ngay(ban|dathang|giaodich|thang|nhap|nhapkho|thu|lap|tao|giao hang|giaohang|apdung|mua|phatsinh|giogiaodich)?|thoigian(tao|thu|lap)?|date|taoluc|gio(ban|taodon)?|ngaygio(phatsinh|thu|tra)?|denngay|hantra|giaodich)$"),
    ("ma_don", r"^(ma|so)?(don(hang)?|hoadon|hd|bill|ct|chungtu|phieu|giaodich|gd)(nhap)?$"),
    ("ma_ncc", r"^(mancc|manhacungcap|nhacungcap)$"),
    ("stt", r"^(stt|sothutu|lan giao|langiao|luotgiao)$"),
]
_RULES = [(r, re.compile(p)) for r, p in NAME_RULES]


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s)


def infer_role(cot_chuan, loai, tien_to_ma=""):
    if loai == "rong":
        return "rong", "cột trống toàn bộ"
    if tien_to_ma in PREFIX_ROLE and loai == "ma":
        return PREFIX_ROLE[tien_to_ma], "tiền tố mã " + tien_to_ma
    sq = squash(cot_chuan)
    for role, rx in _RULES:
        if rx.match(sq):
            return role, "tên cột"
    return "", ""
