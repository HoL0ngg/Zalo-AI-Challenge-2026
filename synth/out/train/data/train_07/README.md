# Tạp hóa khu dân cư — train_07

Dữ liệu giả lập, không có cá nhân thật. Định dạng: **CSV**. Bảng: `san_pham`, `khach_hang`, `don_hang`, `chi_tiet_don`, `phieu_nhap`, `cong_no`.

Các trường giao dịch thường gặp: `ma_don` = `ma_don`, `ngay` = `ngay`, `ma_sp` = `ma_sp`, `so_luong` = `so_luong`, `don_gia` = `don_gia`. Bảng sản phẩm, khách hàng, hóa đơn, chi tiết, phiếu nhập và công nợ liên kết qua mã.

**Đặc điểm:** ngày ở hai dạng ISO và DD/MM/YYYY; một số trường tiền là chuỗi có dấu phân cách hàng nghìn; tên sản phẩm trên dòng bán có teencode/Unicode NFC-NFD; bản ghi chi tiết cùng mã dòng có thể bị lặp; một số ô thông tin khách hàng bỏ trống.

Cần đọc `../../rulebook.md` trước khi tính chỉ tiêu. Dòng trùng `dong_id` là lỗi xuất dữ liệu.
