# Cửa hàng điện thoại — dev_02

Dữ liệu giả lập, không có cá nhân thật. Định dạng: **SQLITE**. Bảng: `HangHoa`, `KhachHang`, `DonHang`, `ChiTietDon`, `NhapKho`, `CongNo`.

Các trường giao dịch thường gặp: `MaDon` = `ma_don`, `NgayBan` = `ngay`, `MaSP` = `ma_sp`, `SL` = `so_luong`, `DonGia` = `don_gia`. Bảng sản phẩm, khách hàng, hóa đơn, chi tiết, phiếu nhập và công nợ liên kết qua mã.

**Đặc điểm:** ngày ở hai dạng ISO và DD/MM/YYYY; một số trường tiền là chuỗi có dấu phân cách hàng nghìn; tên sản phẩm trên dòng bán có teencode/Unicode NFC-NFD; bản ghi chi tiết cùng mã dòng có thể bị lặp; một số ô thông tin khách hàng bỏ trống.

Cần đọc `../../rulebook.md` trước khi tính chỉ tiêu. Dòng trùng `dong_id` là lỗi xuất dữ liệu.
