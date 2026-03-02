# Toast POS → QuickBooks Desktop Enterprise Sync

## Công cụ đồng bộ doanh thu bán hàng MIỄN PHÍ

Script Python tự động lấy dữ liệu bán hàng từ Toast POS và tạo Journal Entry 
trong QuickBooks Desktop Enterprise — không cần xtraCHEF hay bất kỳ phần mềm trả phí nào.

---

## Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| OS | Windows 10/11 |
| QuickBooks | Desktop Enterprise (đã cài và có company file) |
| Python | 3.8+ (cùng kiến trúc 32/64-bit với QuickBooks) |
| Toast | Có subscription RMS Essentials trở lên |
| Mạng | Có kết nối Internet (để gọi Toast API) |

> **Lưu ý về Python 32/64-bit:**  
> - QuickBooks Desktop trước phiên bản 2022 là 32-bit → dùng Python 32-bit  
> - QuickBooks Desktop 2022+ (Enterprise 22.0+) là 64-bit → dùng Python 64-bit

---

## Cài đặt

### Bước 1: Cài Python packages

```cmd
pip install pywin32 requests schedule
```

### Bước 2: Tạo file cấu hình

```cmd
copy config.example.json config.json
```

Mở `config.json` và điền thông tin.

### Bước 3: Lấy Toast API Credentials

1. Đăng nhập **Toast Web** (https://pos.toasttab.com)
2. Vào **Integrations** → **Toast API access** → **Manage credentials**
3. Nhấn **Create new credentials** → chọn **Standard API**
4. Đặt tên (VD: "QuickBooks Sync"), chọn restaurant location
5. Sao chép **Client ID** và **Client Secret** vào `config.json`
6. **Restaurant GUID**: Lấy từ URL khi đăng nhập Toast Web, hoặc vào **Admin** → **Restaurant Info**

> ⚠️ Standard API Access chỉ có quyền **read-only** — đủ cho mục đích lấy dữ liệu bán hàng và hoàn toàn miễn phí.

### Bước 4: Cấu hình Account Mapping

Chạy lệnh sau để xem danh sách tài khoản trong QuickBooks:

```cmd
python toast_to_quickbooks.py --list-accounts
```

Sau đó chỉnh sửa phần `account_mapping` trong `config.json` cho khớp tên tài khoản.

---

## Sử dụng

### Test kết nối

```cmd
:: Test Toast API
python toast_to_quickbooks.py --test-toast

:: Test QuickBooks Desktop
python toast_to_quickbooks.py --test-qb
```

> **Lần đầu chạy test QuickBooks:** QuickBooks sẽ hiện hộp thoại hỏi quyền truy cập.  
> Chọn **"Yes, always; allow access even if QuickBooks is not running"**

### Đồng bộ thủ công

```cmd
:: Đồng bộ doanh thu ngày hôm qua
python toast_to_quickbooks.py --sync-yesterday

:: Đồng bộ ngày cụ thể
python toast_to_quickbooks.py --sync-date 2026-02-25

:: Đồng bộ nhiều ngày (backfill)
python toast_to_quickbooks.py --sync-range 2026-02-01 2026-02-25
```

### Chạy tự động hàng ngày

```cmd
python toast_to_quickbooks.py --auto
```

Script sẽ tự động đồng bộ mỗi ngày vào giờ được cấu hình trong `config.json` (mặc định 6:00 AM).

### Lên lịch bằng Windows Task Scheduler (khuyến nghị)

1. Mở **Task Scheduler** (tìm trong Start Menu)
2. Chọn **Create Basic Task**
3. Đặt tên: `Toast QuickBooks Sync`
4. Trigger: **Daily** → chọn giờ (VD: 6:00 AM)
5. Action: **Start a program**
   - Program: `C:\Path\To\python.exe`
   - Arguments: `C:\Path\To\toast_to_quickbooks.py --sync-yesterday`
   - Start in: `C:\Path\To\toast_to_qb\`
6. ✅ Tick "Open Properties dialog" → chọn "Run whether user is logged on or not"

---

## Journal Entry được tạo như thế nào?

Mỗi ngày, script tạo **1 Journal Entry** tổng hợp:

| Loại | Tài khoản | Debit | Credit |
|---|---|---|---|
| Tiền mặt | Cash in Drawer / Undeposited Funds | ✅ | |
| Thẻ tín dụng | Accounts Receivable | ✅ | |
| Gift Card | Gift Card Liability | ✅ | |
| Giảm giá | Discounts Given | ✅ | |
| Doanh thu | Food Sales | | ✅ |
| Thuế | Sales Tax Payable | | ✅ |
| Tips | Tips Payable | | ✅ |
| Phí dịch vụ | Service Charge Income | | ✅ |

**Ref Number:** `TOAST-YYYYMMDD` (VD: `TOAST-20260225`)

Script tự động kiểm tra trùng lặp — nếu Journal Entry cho ngày đó đã tồn tại, sẽ bỏ qua.

---

## Cấu trúc file

```
toast_to_qb/
├── toast_to_quickbooks.py    # Script chính
├── config.example.json       # Mẫu cấu hình
├── config.json               # Cấu hình của bạn (không commit lên git!)
├── README.md                 # File này
└── logs/                     # Thư mục log (tự động tạo)
    └── sync_20260226.log
```

---

## Troubleshooting

### Lỗi "Class not registered" hoặc "QBXMLRP2 not found"
→ QuickBooks Desktop chưa được cài hoặc Python không cùng kiến trúc (32/64-bit).

### Lỗi "Could not start QuickBooks"
→ QuickBooks Desktop phải đang mở và đã đăng nhập vào company file.

### Lỗi "Access denied"
→ Lần đầu chạy phải có người ngồi trước máy để chấp nhận quyền truy cập trong QuickBooks.

### Lỗi "Account not found"
→ Tên tài khoản trong `config.json` không khớp chính xác với tên trong QuickBooks.  
→ Chạy `--list-accounts` để kiểm tra.

### Lỗi Toast API 401
→ Client ID/Secret sai hoặc đã hết hạn. Tạo credentials mới trong Toast Web.

### Journal Entry không cân bằng
→ Script tự động thêm dòng điều chỉnh (rounding). Kiểm tra log để biết chi tiết.

---

## Bảo mật

- **KHÔNG** commit `config.json` lên Git (chứa API credentials)
- Toast API credentials nên được rotate định kỳ
- Log files có thể chứa thông tin tài chính — bảo vệ thư mục `logs/`
- Nên chạy script dưới tài khoản Windows riêng (không dùng admin)
