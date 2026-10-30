# Quán cà phê và trà sữa — train_02

Dữ liệu giả lập, không có cá nhân thật. Định dạng: **XLSX**. Bảng: `Products`, `Customers`, `Orders`, `OrderLines`, `Purchases`.

Các trường giao dịch thường gặp: `OrderID` = `ma_don`, `OrderDate` = `ngay`, `SKU` = `ma_sp`, `Qty` = `so_luong`, `UnitPrice` = `don_gia`. Bảng sản phẩm, khách hàng, hóa đơn, chi tiết, phiếu nhập và công nợ liên kết qua mã.

**Đặc điểm:** ngày ở hai dạng ISO và DD/MM/YYYY; một số trường tiền là chuỗi có dấu phân cách hàng nghìn; tên sản phẩm trên dòng bán có teencode/Unicode NFC-NFD; bản ghi chi tiết cùng mã dòng có thể bị lặp; một số ô thông tin khách hàng bỏ trống; không theo dõi công nợ.

Cần đọc `../../rulebook.md` trước khi tính chỉ tiêu. Dòng trùng `dong_id` là lỗi xuất dữ liệu.
